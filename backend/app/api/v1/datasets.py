from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select

from app.api import serializers as ser
from app.api.deps import DB, Admin, Editor, Paging, Viewer, owned_dataset, owned_version, paged
from app.core.config import get_settings
from app.core.errors import APIError, bad_request, not_found
from app.core.ratelimit import rate_limit
from app.db import models as m
from app.services import analysis, audit, monitoring
from app.services import datasets as dsvc
from app.services import lineage as lsvc
from datasentry_core import io as dio
from datasentry_core.drift import DriftConfig

router = APIRouter(tags=["datasets"])
NAME_RE = r"^[A-Za-z0-9][A-Za-z0-9_.\- ]{0,119}$"
Criticality = Literal["low", "medium", "high", "critical"]


class DatasetIn(BaseModel):
    name: str = Field(pattern=NAME_RE)
    description: str | None = Field(None, max_length=2000)
    owner: str | None = Field(None, max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=20)
    domain: str | None = Field(None, max_length=80)
    criticality: Criticality = "medium"
    primary_key: list[str] = Field(default_factory=list, max_length=10)
    freshness_column: str | None = Field(None, max_length=128)

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return [t.strip()[:40] for t in v if t.strip()]


class DatasetPatch(BaseModel):
    description: str | None = Field(None, max_length=2000)
    owner: str | None = Field(None, max_length=120)
    tags: list[str] | None = Field(None, max_length=20)
    domain: str | None = Field(None, max_length=80)
    criticality: Criticality | None = None
    primary_key: list[str] | None = None
    freshness_column: str | None = None
    reference_version_id: int | None = None


class DatasetSettings(BaseModel):
    gate_mode: Literal["warn", "block"] | None = None
    drift: dict[str, Any] | None = None
    schema_changes: dict[str, Any] | None = None
    remediation: dict[str, Any] | None = None
    profiling: dict[str, Any] | None = None
    type_overrides: dict[str, Literal["numeric", "categorical", "datetime", "boolean", "text"]] | None = None
    store_failure_samples: bool | None = None
    consumer_costs_per_hour: dict[str, float] | None = None
    assumed_disruption_hours: float | None = Field(None, gt=0, le=720)


def _parse_meta(metadata: str | None) -> DatasetIn | None:
    if not metadata:
        return None
    try:
        return DatasetIn.model_validate(json.loads(metadata))
    except (json.JSONDecodeError, ValueError) as exc:
        raise bad_request(f"Invalid dataset metadata: {exc}") from exc


async def _spool(upload: UploadFile, tmpdir: str) -> Path:
    """Stream an upload to disk in 1 MB chunks, enforcing the size limit without buffering it in memory."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    name = dio.safe_filename(upload.filename or "upload.csv")
    dio.detect_format(name)
    path = Path(tmpdir) / name
    size = 0
    with path.open("wb") as fh:
        while chunk := await upload.read(1 << 20):
            size += len(chunk)
            if size > limit:
                raise APIError(413, "payload_too_large", f"File exceeds the {get_settings().max_upload_mb} MB upload limit.")
            fh.write(chunk)
    return path


def _dataset_out(db: DB, ds: m.Dataset) -> dict[str, Any]:
    cur = db.get(m.DatasetVersion, ds.current_version_id) if ds.current_version_id else None
    open_inc = db.scalar(select(func.count()).select_from(m.Incident).where(
        m.Incident.dataset_id == ds.id, m.Incident.status.in_(("open", "acknowledged", "investigating", "reopened")))) or 0
    n_versions = db.scalar(select(func.count()).select_from(m.DatasetVersion).where(m.DatasetVersion.dataset_id == ds.id)) or 0
    n_rules = db.scalar(select(func.count()).select_from(m.QualityRule).where(m.QualityRule.dataset_id == ds.id)) or 0
    return ser.dataset(ds, cur, {"open_incidents": open_inc, "version_count": n_versions, "rule_count": n_rules})


@router.get("/datasets", summary="List datasets with search, filters and sorting")
def list_datasets(p: Viewer, db: DB, page: Paging, q: str | None = Query(None, max_length=100),
                  health: str | None = None, domain: str | None = None, source_type: str | None = None,
                  sort: Literal["name", "updated", "criticality", "health"] = "updated") -> dict[str, Any]:
    stmt = select(m.Dataset).where(m.Dataset.workspace_id == p.workspace_id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(m.Dataset.name).like(like), func.lower(m.Dataset.description).like(like),
                              func.lower(m.Dataset.owner).like(like)))
    if health:
        stmt = stmt.where(m.Dataset.health == health)
    if domain:
        stmt = stmt.where(m.Dataset.domain == domain)
    if source_type:
        stmt = stmt.where(m.Dataset.source_type == source_type)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order = {"name": m.Dataset.name, "updated": m.Dataset.updated_at.desc(), "criticality": m.Dataset.criticality,
             "health": m.Dataset.health}[sort]
    rows = db.scalars(stmt.order_by(order, m.Dataset.id).offset(page.offset).limit(page.page_size))
    return paged([_dataset_out(db, d) for d in rows], total, page)


@router.post("/datasets", status_code=201, summary="Register a dataset (metadata only)")
def create_dataset(body: DatasetIn, p: Editor, db: DB) -> dict[str, Any]:
    ds = dsvc.create_dataset(db, p.workspace_id, p, **body.model_dump(), source_type="upload")
    db.commit()
    return _dataset_out(db, ds)


@router.post("/datasets/upload", status_code=201, dependencies=[Depends(rate_limit("upload"))],
             summary="Register a dataset and upload its first version in one request")
async def upload_new(p: Editor, db: DB, file: UploadFile = File(...), metadata: str = Form(..., description="DatasetIn JSON"),
                     encoding: str = Form("utf-8")) -> dict[str, Any]:
    meta = _parse_meta(metadata)
    with tempfile.TemporaryDirectory() as tmp:
        path = await _spool(file, tmp)
        ds = dsvc.create_dataset(db, p.workspace_id, p, **meta.model_dump(), source_type="upload")
        v = dsvc.ingest_file(db, ds, path, path.name, p, encoding=encoding, origin_detail={"encoding": encoding})
    result = monitoring.process_version(db, ds, v, "upload", p)
    db.commit()
    return {"dataset": _dataset_out(db, ds), "version": ser.version(v, True), "monitoring": result}


@router.get("/datasets/{dataset_id}", summary="Dataset detail")
def get_dataset(dataset_id: int, p: Viewer, db: DB) -> dict[str, Any]:
    return _dataset_out(db, owned_dataset(db, dataset_id, p))


@router.patch("/datasets/{dataset_id}", summary="Update dataset metadata")
def patch_dataset(dataset_id: int, body: DatasetPatch, p: Editor, db: DB) -> dict[str, Any]:
    ds = owned_dataset(db, dataset_id, p)
    data = body.model_dump(exclude_unset=True)
    if "reference_version_id" in data and data["reference_version_id"] is not None:
        v, vds = owned_version(db, data["reference_version_id"], p)
        if vds.id != ds.id or v.ingestion_status != "succeeded":
            raise bad_request("reference_version_id must be a successfully ingested version of this dataset.")
    for k, v in data.items():
        setattr(ds, k, v)
    dsvc.ensure_dataset_node(db, ds)
    audit.record(db, p.workspace_id, "dataset.updated", "dataset", ds.id, {"fields": sorted(data)}, p)
    db.commit()
    return _dataset_out(db, ds)


@router.put("/datasets/{dataset_id}/settings", summary="Update monitoring, drift, schema-change and remediation policy")
def put_settings(dataset_id: int, body: DatasetSettings, p: Editor, db: DB) -> dict[str, Any]:
    ds = owned_dataset(db, dataset_id, p)
    data = body.model_dump(exclude_none=True)
    if "drift" in data:
        try:
            DriftConfig.from_dict(data["drift"])
        except (TypeError, ValueError) as exc:
            raise bad_request(f"Invalid drift settings: {exc}") from exc
    if "schema_changes" in data:
        pol = data["schema_changes"].get("policy", {})
        if any(v not in ("info", "warning", "critical") for v in pol.values()):
            raise bad_request("Schema-change policy severities must be info, warning or critical.")
    if "remediation" in data:
        rem = data["remediation"]
        for col, pol in (rem.get("missing_value_policies") or {}).items():
            if pol.get("strategy") not in ("mean", "median", "mode", "constant", "drop_rows"):
                raise bad_request(f"Invalid missing-value strategy for '{col}'.")
        for col, t in (rem.get("type_conversions") or {}).items():
            if t not in {s.value for s in dio.SemanticType}:
                raise bad_request(f"Invalid conversion target for '{col}'.")
    ds.settings = {**(ds.settings or {}), **data}
    audit.record(db, p.workspace_id, "dataset.settings_updated", "dataset", ds.id, {"keys": sorted(data)}, p)
    db.commit()
    return _dataset_out(db, ds)


@router.delete("/datasets/{dataset_id}", summary="Delete a dataset and its history (admin)")
def delete_dataset(dataset_id: int, p: Admin, db: DB, confirm: str = Query(..., description="Must equal the dataset name")) -> dict[str, Any]:
    ds = owned_dataset(db, dataset_id, p)
    if confirm != ds.name:
        raise bad_request("Confirmation does not match the dataset name.")
    audit.record(db, p.workspace_id, "dataset.deleted", "dataset", ds.id, {"name": ds.name}, p)
    ds.current_version_id = None
    ds.reference_version_id = None
    db.flush()
    db.delete(ds)
    db.commit()
    return {"deleted": True}


# ---------------------------------------------------------------- versions


@router.get("/datasets/{dataset_id}/versions", summary="Version history")
def list_versions(dataset_id: int, p: Viewer, db: DB, page: Paging) -> dict[str, Any]:
    ds = owned_dataset(db, dataset_id, p)
    stmt = select(m.DatasetVersion).where(m.DatasetVersion.dataset_id == ds.id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(m.DatasetVersion.version_number.desc()).offset(page.offset).limit(page.page_size))
    return paged([ser.version(v) for v in rows], total, page)


@router.post("/datasets/{dataset_id}/versions", status_code=201, dependencies=[Depends(rate_limit("upload"))],
             summary="Upload a new version (file) and run monitoring")
async def upload_version(dataset_id: int, p: Editor, db: DB, file: UploadFile = File(...), encoding: str = Form("utf-8"),
                         run_monitoring: bool = Form(True)) -> dict[str, Any]:
    ds = owned_dataset(db, dataset_id, p)
    with tempfile.TemporaryDirectory() as tmp:
        path = await _spool(file, tmp)
        v = dsvc.ingest_file(db, ds, path, path.name, p, encoding=encoding, origin_detail={"encoding": encoding})
    result = monitoring.process_version(db, ds, v, "upload", p) if run_monitoring else None
    db.commit()
    return {"version": ser.version(v, True), "monitoring": result}


class RecordsIn(BaseModel):
    records: list[dict[str, Any]] = Field(min_length=1, max_length=200_000)
    run_monitoring: bool = True


@router.post("/datasets/{dataset_id}/versions/records", status_code=201, dependencies=[Depends(rate_limit("upload"))],
             summary="Create a version from JSON records (used by the SDK)")
def upload_records(dataset_id: int, body: RecordsIn, p: Editor, db: DB) -> dict[str, Any]:
    ds = owned_dataset(db, dataset_id, p)
    df = pd.DataFrame.from_records(body.records)
    v = dsvc.ingest_frame(db, ds, df, p, "sdk", f"{ds.name}.csv")
    result = monitoring.process_version(db, ds, v, "sdk", p) if body.run_monitoring else None
    db.commit()
    return {"version": ser.version(v, True), "monitoring": result}


@router.get("/versions/{version_id}", summary="Version detail with schema")
def get_version(version_id: int, p: Viewer, db: DB) -> dict[str, Any]:
    v, _ = owned_version(db, version_id, p)
    return ser.version(v, True)


@router.get("/versions/{version_id}/preview", summary="Paginated rows of a version (nulls preserved)")
def preview(version_id: int, p: Viewer, db: DB, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    v, _ = owned_version(db, version_id, p)
    return dsvc.preview(db, v, offset, limit)


@router.post("/versions/{version_id}/monitor", summary="Re-run the full monitoring pipeline on a version")
def monitor_version(version_id: int, p: Editor, db: DB) -> dict[str, Any]:
    v, ds = owned_version(db, version_id, p)
    if v.ingestion_status != "succeeded":
        raise APIError(409, "not_ingested", "This version failed ingestion; retry ingestion first.")
    ev = monitoring.evaluate_version(db, ds, v, "manual")
    from app.services import incidents

    inc, _ = incidents.upsert_dataset_incident(db, ds, v, ev.findings, {"trigger": "manual", "check_run_id": ev.run.id})
    if ds.current_version_id == v.id:
        incidents.resolve_if_cleared(db, ds, v, ev.findings, "Manual re-check found none of the incident's findings.")
        monitoring.update_health(ds, ev)
    db.commit()
    return {**ev.to_summary(), "incident_id": inc.id if inc else None}


class PromoteIn(BaseModel):
    note: str = Field(min_length=3, max_length=500)


@router.post("/versions/{version_id}/promote", summary="Make a version active (manual override, audited)")
def promote(version_id: int, body: PromoteIn, p: Editor, db: DB) -> dict[str, Any]:
    v, ds = owned_version(db, version_id, p)
    if v.ingestion_status != "succeeded":
        raise APIError(409, "not_ingested", "Only successfully ingested versions can be activated.")
    prev = ds.current_version_id
    monitoring.activate(db, ds, v)
    audit.record(db, p.workspace_id, "dataset.version_promoted", "dataset_version", v.id,
                 {"dataset_id": ds.id, "previous_version_id": prev, "note": body.note}, p)
    db.commit()
    return ser.version(v)


@router.get("/versions/{version_id}/download", summary="Download the normalised data of a version as CSV")
def download(version_id: int, p: Viewer, db: DB):
    from fastapi.responses import StreamingResponse

    v, ds = owned_version(db, version_id, p)
    df = dsvc.load_frame(db, v)
    audit.record(db, p.workspace_id, "dataset.version_downloaded", "dataset_version", v.id, {"dataset_id": ds.id}, p)
    db.commit()
    fname = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{ds.name}_v{v.version_number}.csv")
    return StreamingResponse(iter([df.to_csv(index=False)]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---------------------------------------------------------------- profiling


@router.get("/versions/{version_id}/profile", summary="Latest profile of a version")
def get_profile(version_id: int, p: Viewer, db: DB) -> dict[str, Any]:
    v, _ = owned_version(db, version_id, p)
    prof = dsvc.latest_profile(db, v.id)
    if prof is None:
        raise not_found("Profile for version", version_id)
    return ser.profile(prof)


@router.post("/versions/{version_id}/profile", status_code=201, summary="Recompute the profile of a version")
def run_profile(version_id: int, p: Editor, db: DB) -> dict[str, Any]:
    v, ds = owned_version(db, version_id, p)
    prof = dsvc.profile_version(db, ds, v)
    db.commit()
    return ser.profile(prof)


@router.get("/datasets/{dataset_id}/profile-history", summary="Dataset-level profile metrics over versions")
def profile_history(dataset_id: int, p: Viewer, db: DB, limit: int = Query(30, le=200)) -> dict[str, Any]:
    ds = owned_dataset(db, dataset_id, p)
    rows = db.execute(select(m.Profile, m.DatasetVersion.version_number).join(m.DatasetVersion, m.Profile.version_id == m.DatasetVersion.id)
                      .where(m.Profile.dataset_id == ds.id).order_by(m.Profile.id.desc()).limit(limit)).all()
    seen: set[int] = set()
    items = []
    for prof, num in rows:
        if prof.version_id in seen:
            continue
        seen.add(prof.version_id)
        items.append({"version_id": prof.version_id, "version_number": num, "created_at": ser.iso(prof.created_at),
                      **{k: prof.summary.get(k) for k in ("row_count", "missing_cell_pct", "duplicate_row_pct", "freshness_seconds")}})
    return {"items": list(reversed(items))}


# ---------------------------------------------------------------- comparison and drift


class CompareIn(BaseModel):
    base_version_id: int
    target_version_id: int


@router.post("/datasets/{dataset_id}/compare", status_code=201, summary="Compare two versions (schema, nulls, categories, rows)")
def compare(dataset_id: int, body: CompareIn, p: Editor, db: DB) -> dict[str, Any]:
    ds = owned_dataset(db, dataset_id, p)
    base, bds = owned_version(db, body.base_version_id, p)
    tgt, tds = owned_version(db, body.target_version_id, p)
    if bds.id != ds.id or tds.id != ds.id:
        raise bad_request("Both versions must belong to this dataset.")
    if base.id == tgt.id:
        raise bad_request("Choose two different versions.")
    comp = analysis.run_comparison(db, ds, base, tgt)
    db.commit()
    return ser.comparison(comp)


@router.get("/datasets/{dataset_id}/comparisons", summary="Comparison history")
def list_comparisons(dataset_id: int, p: Viewer, db: DB, page: Paging) -> dict[str, Any]:
    ds = owned_dataset(db, dataset_id, p)
    stmt = select(m.VersionComparison).where(m.VersionComparison.dataset_id == ds.id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(m.VersionComparison.id.desc()).offset(page.offset).limit(page.page_size))
    return paged([ser.comparison(c) for c in rows], total, page)


class RenameIn(BaseModel):
    from_column: str = Field(max_length=128)
    to_column: str = Field(max_length=128)
    decision: Literal["confirmed", "rejected"]


@router.post("/datasets/{dataset_id}/rename-decisions", status_code=201, summary="Confirm or reject a potential column rename")
def rename_decision(dataset_id: int, body: RenameIn, p: Editor, db: DB) -> dict[str, Any]:
    ds = owned_dataset(db, dataset_id, p)
    row = db.scalar(select(m.RenameDecision).where(m.RenameDecision.dataset_id == ds.id, m.RenameDecision.from_column == body.from_column,
                                                   m.RenameDecision.to_column == body.to_column))
    if row is None:
        row = m.RenameDecision(dataset_id=ds.id, from_column=body.from_column, to_column=body.to_column)
        db.add(row)
    row.decision, row.decided_by = body.decision, p.user_id
    audit.record(db, p.workspace_id, f"dataset.rename_{body.decision}", "dataset", ds.id, body.model_dump(), p)
    db.commit()
    return {"from_column": row.from_column, "to_column": row.to_column, "decision": row.decision}


@router.get("/datasets/{dataset_id}/rename-decisions", summary="Rename decisions for a dataset")
def list_renames(dataset_id: int, p: Viewer, db: DB) -> dict[str, Any]:
    ds = owned_dataset(db, dataset_id, p)
    rows = db.scalars(select(m.RenameDecision).where(m.RenameDecision.dataset_id == ds.id))
    return {"items": [{"from_column": r.from_column, "to_column": r.to_column, "decision": r.decision,
                       "created_at": ser.iso(r.created_at)} for r in rows]}


class DriftIn(BaseModel):
    reference_version_id: int | None = None
    current_version_id: int | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    window_column: str | None = None
    reference_start: str | None = None
    reference_end: str | None = None
    current_start: str | None = None
    current_end: str | None = None


@router.post("/datasets/{dataset_id}/drift", status_code=201,
             summary="Run a drift comparison between two versions or time windows")
def run_drift(dataset_id: int, body: DriftIn, p: Editor, db: DB) -> dict[str, Any]:
    ds = owned_dataset(db, dataset_id, p)
    ref_id = body.reference_version_id or ds.reference_version_id
    cur_id = body.current_version_id or ds.current_version_id
    if not ref_id or not cur_id:
        raise bad_request("Need a reference and a current version (set a reference version or pass both ids).")
    ref, rds = owned_version(db, ref_id, p)
    cur, cds = owned_version(db, cur_id, p)
    if rds.id != ds.id or cds.id != ds.id:
        raise bad_request("Both versions must belong to this dataset.")
    if ref.id == cur.id and not body.window_column:
        raise bad_request("Reference and current are the same version; pass time windows to compare periods.")
    windows = {k: v for k, v in {"column": body.window_column, "reference_start": body.reference_start,
                                 "reference_end": body.reference_end, "current_start": body.current_start,
                                 "current_end": body.current_end}.items() if v}
    ev = analysis.run_drift(db, ds, ref, cur, body.config, windows, "manual")
    audit.record(db, p.workspace_id, "drift.evaluated", "drift_evaluation", ev.id, {"dataset_id": ds.id}, p)
    db.commit()
    return ser.drift_eval(ev)


@router.get("/datasets/{dataset_id}/drift", summary="Drift evaluation history")
def list_drift(dataset_id: int, p: Viewer, db: DB, page: Paging) -> dict[str, Any]:
    ds = owned_dataset(db, dataset_id, p)
    stmt = select(m.DriftEvaluation).where(m.DriftEvaluation.dataset_id == ds.id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(m.DriftEvaluation.id.desc()).offset(page.offset).limit(page.page_size))
    return paged([ser.drift_eval(e, with_features=False) for e in rows], total, page)


@router.get("/drift", summary="Recent drift evaluations across the workspace")
def recent_drift(p: Viewer, db: DB, page: Paging, severity: str | None = None) -> dict[str, Any]:
    stmt = (select(m.DriftEvaluation, m.Dataset.name).join(m.Dataset, m.Dataset.id == m.DriftEvaluation.dataset_id)
            .where(m.Dataset.workspace_id == p.workspace_id, m.DriftEvaluation.trigger != "remediation_verification"))
    if severity:
        stmt = stmt.where(m.DriftEvaluation.overall_severity == severity)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(m.DriftEvaluation.id.desc()).offset(page.offset).limit(page.page_size)).all()
    return paged([{**ser.drift_eval(e, with_features=False), "dataset_name": n} for e, n in rows], total, page)


@router.get("/drift/{evaluation_id}", summary="Drift evaluation with per-feature evidence")
def get_drift(evaluation_id: int, p: Viewer, db: DB) -> dict[str, Any]:
    ev = db.get(m.DriftEvaluation, evaluation_id)
    if ev is None:
        raise not_found("Drift evaluation", evaluation_id)
    owned_dataset(db, ev.dataset_id, p)
    return ser.drift_eval(ev)


@router.get("/datasets/{dataset_id}/lineage-impact", summary="Downstream impact if this dataset fails")
def impact(dataset_id: int, p: Viewer, db: DB) -> dict[str, Any]:
    return lsvc.dataset_impact(db, owned_dataset(db, dataset_id, p))
