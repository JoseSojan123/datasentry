from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api import serializers as ser
from app.api.deps import DB, Editor, Paging, Viewer, owned, paged
from app.core.config import get_settings
from app.core.errors import bad_request, not_found
from app.core.ratelimit import rate_limit
from app.db import models as m
from app.services import audit
from app.services import models as msvc

router = APIRouter(tags=["models"])


class ModelIn(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,119}$")
    description: str | None = Field(None, max_length=2000)
    task: Literal["classification", "regression"]
    target: str | None = Field(None, max_length=200)
    positive_label: str | None = Field(None, max_length=64)
    reference_dataset_id: int | None = None
    criticality: Literal["low", "medium", "high", "critical"] = "medium"
    owner: str | None = Field(None, max_length=120)


class FeatureSpec(BaseModel):
    name: str = Field(max_length=128)
    type: Literal["numeric", "categorical"] = "numeric"
    nullable: bool = True


class ModelVersionIn(BaseModel):
    version: str = Field(min_length=1, max_length=40)
    input_schema: list[FeatureSpec] = Field(default_factory=list, max_length=500)
    baseline_metrics: dict[str, Any] = Field(default_factory=dict)
    artifact: dict[str, Any] = Field(default_factory=dict, description="Optional artifact metadata (URI, framework, hash)")
    feature_logging: Literal["none", "aggregate", "full"] | None = None
    retention_days: int | None = Field(None, ge=1, le=3650)


class PredictionIn(BaseModel):
    record_id: str = Field(min_length=1, max_length=128, description="Non-sensitive identifier")
    timestamp: datetime | None = None
    features: dict[str, Any] | None = None
    prediction: str | int | float | bool
    score: float | None = Field(None, description="Positive-class probability (classification)")
    label: str | int | float | bool | None = None


class PredictionsIn(BaseModel):
    model_version: str
    predictions: list[PredictionIn] = Field(min_length=1, max_length=5000)


class LabelIn(BaseModel):
    record_id: str = Field(max_length=128)
    label: str | int | float | bool | None
    labeled_at: datetime | None = None


class LabelsIn(BaseModel):
    model_version: str
    labels: list[LabelIn] = Field(min_length=1, max_length=10000)


class EvaluateIn(BaseModel):
    model_version: str
    current_start: datetime | None = None
    current_end: datetime | None = None
    reference_start: datetime | None = None
    reference_end: datetime | None = None


def _version(db: DB, model: m.MLModel, version: str) -> m.ModelVersion:
    mv = db.scalar(select(m.ModelVersion).where(m.ModelVersion.model_id == model.id, m.ModelVersion.version == version))
    if mv is None:
        raise not_found(f"Version '{version}' of model", model.id)
    return mv


def _model_out(db: DB, mo: m.MLModel) -> dict[str, Any]:
    versions = list(db.scalars(select(m.ModelVersion).where(m.ModelVersion.model_id == mo.id).order_by(m.ModelVersion.id.desc())))
    latest_eval = None
    if versions:
        e = db.scalar(select(m.ModelEvaluation).where(m.ModelEvaluation.model_version_id.in_([v.id for v in versions]))
                      .order_by(m.ModelEvaluation.window_end.desc().nulls_last(), m.ModelEvaluation.id.desc()).limit(1))
        latest_eval = ser.model_eval(e) if e else None
    n_pred = db.scalar(select(func.count()).select_from(m.PredictionRecord).where(
        m.PredictionRecord.model_version_id.in_([v.id for v in versions]))) if versions else 0
    open_inc = db.scalar(select(func.count()).select_from(m.Incident).where(
        m.Incident.model_id == mo.id, m.Incident.status.in_(("open", "acknowledged", "investigating", "reopened")))) or 0
    return ser.model(mo, {"versions": [ser.model_version(v) for v in versions], "latest_evaluation": latest_eval,
                          "prediction_count": n_pred or 0, "open_incidents": open_inc})


@router.get("/models", summary="Model registry")
def list_models(p: Viewer, db: DB, page: Paging) -> dict[str, Any]:
    stmt = select(m.MLModel).where(m.MLModel.workspace_id == p.workspace_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(m.MLModel.name).offset(page.offset).limit(page.page_size))
    return paged([_model_out(db, x) for x in rows], total, page)


@router.post("/models", status_code=201, summary="Register a model")
def create_model(body: ModelIn, p: Editor, db: DB) -> dict[str, Any]:
    mo = msvc.register_model(db, p.workspace_id, p, **body.model_dump())
    db.commit()
    return _model_out(db, mo)


@router.get("/models/{model_id}", summary="Model detail")
def get_model(model_id: int, p: Viewer, db: DB) -> dict[str, Any]:
    return _model_out(db, owned(db, m.MLModel, model_id, p, "Model"))


@router.post("/models/{model_id}/versions", status_code=201, summary="Register a model version with schema and baseline metrics")
def create_version(model_id: int, body: ModelVersionIn, p: Editor, db: DB) -> dict[str, Any]:
    mo = owned(db, m.MLModel, model_id, p, "Model")
    s = get_settings()
    mv = msvc.create_version(db, mo, p, version=body.version, input_schema=[f.model_dump() for f in body.input_schema],
                             baseline_metrics=body.baseline_metrics, artifact=body.artifact,
                             feature_logging=body.feature_logging or s.prediction_feature_logging,
                             retention_days=body.retention_days or s.prediction_retention_days)
    db.commit()
    return ser.model_version(mv)


@router.post("/models/{model_id}/predictions", status_code=201, dependencies=[Depends(rate_limit("predictions"))],
             summary="Log a batch of predictions (idempotent on record_id)")
def log_predictions(model_id: int, body: PredictionsIn, p: Editor, db: DB) -> dict[str, Any]:
    mo = owned(db, m.MLModel, model_id, p, "Model")
    mv = _version(db, mo, body.model_version)
    res = msvc.log_predictions(db, mv, [x.model_dump() for x in body.predictions], p)
    db.commit()
    return res


@router.post("/models/{model_id}/labels", summary="Attach (possibly delayed) ground-truth labels")
def log_labels(model_id: int, body: LabelsIn, p: Editor, db: DB) -> dict[str, Any]:
    mo = owned(db, m.MLModel, model_id, p, "Model")
    mv = _version(db, mo, body.model_version)
    res = msvc.log_labels(db, mv, [x.model_dump() for x in body.labels])
    audit.record(db, p.workspace_id, "model.labels_logged", "model_version", mv.id, {"updated": res["updated"]}, p)
    db.commit()
    return res


@router.post("/models/{model_id}/evaluate", status_code=201, summary="Evaluate performance, input drift and prediction drift")
def evaluate(model_id: int, body: EvaluateIn, p: Editor, db: DB) -> dict[str, Any]:
    mo = owned(db, m.MLModel, model_id, p, "Model")
    mv = _version(db, mo, body.model_version)
    if body.current_start and body.current_end and body.current_start >= body.current_end:
        raise bad_request("current_start must be before current_end")
    ev = msvc.evaluate(db, mo, mv, body.current_start, body.current_end, body.reference_start, body.reference_end, "manual")
    db.commit()
    return ser.model_eval(ev)


@router.get("/models/{model_id}/evaluations", summary="Evaluation history")
def list_evaluations(model_id: int, p: Viewer, db: DB, page: Paging, model_version: str | None = None) -> dict[str, Any]:
    mo = owned(db, m.MLModel, model_id, p, "Model")
    ids = [v.id for v in db.scalars(select(m.ModelVersion).where(m.ModelVersion.model_id == mo.id))]
    if model_version:
        ids = [_version(db, mo, model_version).id]
    stmt = select(m.ModelEvaluation).where(m.ModelEvaluation.model_version_id.in_(ids or [-1]))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(m.ModelEvaluation.window_end.desc().nulls_last(), m.ModelEvaluation.id.desc())
                      .offset(page.offset).limit(page.page_size))
    return paged([ser.model_eval(e) for e in rows], total, page)


@router.get("/models/{model_id}/series", summary="Daily prediction volume, label coverage and mean score")
def series(model_id: int, p: Viewer, db: DB, model_version: str) -> dict[str, Any]:
    mo = owned(db, m.MLModel, model_id, p, "Model")
    return {"items": msvc.daily_series(db, _version(db, mo, model_version))}


@router.get("/models/{model_id}/predictions", summary="Recent prediction records (features shown only with full logging)")
def list_predictions(model_id: int, p: Viewer, db: DB, page: Paging, model_version: str,
                     labelled: bool | None = None) -> dict[str, Any]:
    mo = owned(db, m.MLModel, model_id, p, "Model")
    mv = _version(db, mo, model_version)
    stmt = select(m.PredictionRecord).where(m.PredictionRecord.model_version_id == mv.id)
    if labelled is not None:
        stmt = stmt.where(m.PredictionRecord.label.isnot(None) if labelled else m.PredictionRecord.label.is_(None))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(m.PredictionRecord.predicted_at.desc()).offset(page.offset).limit(page.page_size))
    return paged([{"record_id": r.record_id, "predicted_at": ser.iso(r.predicted_at), "prediction": r.prediction, "score": r.score,
                   "label": r.label, "labeled_at": ser.iso(r.labeled_at), "features": r.features,
                   "schema_violations": r.schema_violations} for r in rows], total, page)
