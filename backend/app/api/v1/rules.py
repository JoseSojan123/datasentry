from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api import serializers as ser
from app.api.deps import DB, Editor, Paging, Viewer, owned, owned_dataset, owned_version, paged
from app.core.errors import bad_request, not_found
from app.db import models as m
from app.services import audit, quality
from datasentry_core.rules import CONFIG_MODELS, RULE_TYPES, validate_rule

router = APIRouter(tags=["quality rules"])
Severity = Literal["info", "warning", "critical"]


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    rule_type: str
    columns: list[str] = Field(default_factory=list, max_length=20)
    config: dict[str, Any] = Field(default_factory=dict)
    severity: Severity = "warning"
    enabled: bool = True


class RulePatch(BaseModel):
    name: str | None = Field(None, max_length=160)
    columns: list[str] | None = None
    config: dict[str, Any] | None = None
    severity: Severity | None = None
    enabled: bool | None = None


def _validated(rule_type: str, columns: list[str], config: dict[str, Any]) -> dict[str, Any]:
    try:
        return validate_rule(rule_type, columns, config)
    except ValueError as exc:
        raise bad_request(str(exc), code="invalid_rule") from exc


def _last_results(db: DB, rule_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not rule_ids:
        return {}
    sub = select(m.CheckResult.rule_id, func.max(m.CheckResult.id).label("mid")).where(
        m.CheckResult.rule_id.in_(rule_ids)).group_by(m.CheckResult.rule_id).subquery()
    rows = db.scalars(select(m.CheckResult).join(sub, m.CheckResult.id == sub.c.mid))
    return {r.rule_id: {"status": r.status, "failure_pct": r.failure_pct, "failed_rows": r.failed_rows,
                        "explanation": r.explanation, "run_id": r.run_id, "created_at": ser.iso(r.created_at)} for r in rows}


@router.get("/rule-types", summary="Supported rule types with their JSON configuration schemas")
def rule_types() -> dict[str, Any]:
    return {"items": [{"rule_type": t, "config_schema": CONFIG_MODELS[t].model_json_schema()} for t in RULE_TYPES]}


@router.get("/datasets/{dataset_id}/rules", summary="Rules of a dataset with their latest result")
def list_rules(dataset_id: int, p: Viewer, db: DB) -> dict[str, Any]:
    ds = owned_dataset(db, dataset_id, p)
    rules = list(db.scalars(select(m.QualityRule).where(m.QualityRule.dataset_id == ds.id).order_by(m.QualityRule.id)))
    last = _last_results(db, [r.id for r in rules])
    return {"items": [ser.rule(r, last.get(r.id)) for r in rules]}


@router.post("/datasets/{dataset_id}/rules", status_code=201, summary="Create a rule")
def create_rule(dataset_id: int, body: RuleIn, p: Editor, db: DB) -> dict[str, Any]:
    ds = owned_dataset(db, dataset_id, p)
    cfg = _validated(body.rule_type, body.columns, body.config)
    if body.rule_type == "referential_integrity":
        owned_dataset(db, int(cfg["reference_dataset_id"]), p)
    r = m.QualityRule(workspace_id=p.workspace_id, dataset_id=ds.id, name=body.name, rule_type=body.rule_type, columns=body.columns,
                      config=cfg, severity=body.severity, enabled=body.enabled, created_by=p.user_id)
    db.add(r)
    db.flush()
    audit.record(db, p.workspace_id, "rule.created", "quality_rule", r.id, {"dataset_id": ds.id, "rule_type": r.rule_type}, p)
    db.commit()
    return ser.rule(r)


@router.patch("/rules/{rule_id}", summary="Update a rule")
def patch_rule(rule_id: int, body: RulePatch, p: Editor, db: DB) -> dict[str, Any]:
    r = owned(db, m.QualityRule, rule_id, p, "Rule")
    data = body.model_dump(exclude_unset=True)
    columns = data.get("columns", r.columns)
    config = data.get("config", r.config)
    if "columns" in data or "config" in data:
        data["config"] = _validated(r.rule_type, columns, config)
    for k, v in data.items():
        setattr(r, k, v)
    audit.record(db, p.workspace_id, "rule.updated", "quality_rule", r.id, {"fields": sorted(data)}, p)
    db.commit()
    return ser.rule(r)


@router.delete("/rules/{rule_id}", summary="Delete a rule (its execution history is removed too)")
def delete_rule(rule_id: int, p: Editor, db: DB) -> dict[str, Any]:
    r = owned(db, m.QualityRule, rule_id, p, "Rule")
    audit.record(db, p.workspace_id, "rule.deleted", "quality_rule", r.id, {"name": r.name}, p)
    db.delete(r)
    db.commit()
    return {"deleted": True}


@router.get("/rules/{rule_id}/history", summary="Execution history of one rule")
def rule_history(rule_id: int, p: Viewer, db: DB, page: Paging) -> dict[str, Any]:
    r = owned(db, m.QualityRule, rule_id, p, "Rule")
    stmt = select(m.CheckResult).where(m.CheckResult.rule_id == r.id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(m.CheckResult.id.desc()).offset(page.offset).limit(page.page_size))
    return paged([ser.check_result(x) for x in rows], total, page)


class ValidateIn(BaseModel):
    version_id: int | None = None
    rules: list[dict[str, Any]] | None = Field(None, description="Inline rules; created if they do not exist yet",
                                               max_length=100)
    only_inline: bool = Field(False, description="Run only the inline rules instead of all enabled rules")


@router.post("/datasets/{dataset_id}/validate", status_code=201, summary="Execute rules against a version")
def validate(dataset_id: int, body: ValidateIn, p: Editor, db: DB) -> dict[str, Any]:
    ds = owned_dataset(db, dataset_id, p)
    vid = body.version_id or ds.current_version_id
    if not vid:
        raise bad_request("The dataset has no active version to validate.")
    v, vds = owned_version(db, vid, p)
    if vds.id != ds.id:
        raise bad_request("version_id belongs to another dataset.")
    selected = None
    if body.rules:
        try:
            inline = quality.upsert_inline_rules(db, ds, body.rules, p)
        except ValueError as exc:
            raise bad_request(str(exc), code="invalid_rule") from exc
        if body.only_inline:
            selected = inline
    run = quality.run_rules(db, ds, v, "api", selected)
    audit.record(db, p.workspace_id, "rules.executed", "check_run", run.id, {"dataset_id": ds.id, **run.summary}, p)
    db.commit()
    return ser.check_run(run, quality.run_results(db, run.id))


@router.get("/datasets/{dataset_id}/check-runs", summary="Rule execution runs for a dataset")
def list_runs(dataset_id: int, p: Viewer, db: DB, page: Paging) -> dict[str, Any]:
    ds = owned_dataset(db, dataset_id, p)
    stmt = select(m.CheckRun).where(m.CheckRun.dataset_id == ds.id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(m.CheckRun.id.desc()).offset(page.offset).limit(page.page_size))
    return paged([ser.check_run(r) for r in rows], total, page)


@router.get("/check-runs/{run_id}", summary="One rule execution run with all results")
def get_run(run_id: int, p: Viewer, db: DB) -> dict[str, Any]:
    run = db.get(m.CheckRun, run_id)
    if run is None:
        raise not_found("Check run", run_id)
    owned_dataset(db, run.dataset_id, p)
    return ser.check_run(run, quality.run_results(db, run.id))
