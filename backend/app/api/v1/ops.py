"""Jobs, notifications, dashboard overview, activity, audit log, demo helpers and health."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text, update

from app.api import serializers as ser
from app.api.deps import DB, Admin, CurrentPrincipal, Editor, Paging, Viewer, owned, paged
from app.core.config import get_settings
from app.core.errors import APIError
from app.db import models as m
from app.services import audit, jobs
from app.services import seed as seedsvc
from datasentry_core import synthetic as syn

router = APIRouter()
ACTIVE = ("open", "acknowledged", "investigating", "reopened")


# ---------------------------------------------------------------- health


@router.get("/health", tags=["health"], summary="Liveness (no configuration exposed)")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "datasentry-api", "time": datetime.now(UTC).isoformat()}


@router.get("/ready", tags=["health"], summary="Readiness: database reachable and migrated")
def ready(db: DB) -> dict[str, Any]:
    try:
        db.execute(text("SELECT 1"))
        rev = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception as exc:  # noqa: BLE001
        raise APIError(503, "not_ready", "Database unavailable or not migrated.") from exc
    return {"status": "ready", "database": "ok", "migration": rev, "scheduler_mode": get_settings().scheduler_mode}


# ---------------------------------------------------------------- jobs


class JobIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    job_type: Literal["profile", "validate", "drift", "monitor", "model_eval"]
    target_id: int
    interval_seconds: int = Field(ge=60, le=30 * 86400)
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    max_retries: int = Field(2, ge=0, le=10)
    retry_backoff_seconds: int = Field(60, ge=10, le=3600)
    timeout_seconds: int = Field(300, ge=10, le=3600)
    start_at: datetime | None = None


class JobPatch(BaseModel):
    name: str | None = Field(None, max_length=160)
    interval_seconds: int | None = Field(None, ge=60, le=30 * 86400)
    enabled: bool | None = None
    max_retries: int | None = Field(None, ge=0, le=10)
    params: dict[str, Any] | None = None


@router.get("/jobs", tags=["jobs"], summary="Scheduled jobs with last/next run")
def list_jobs(p: Viewer, db: DB) -> dict[str, Any]:
    rows = db.scalars(select(m.ScheduledJob).where(m.ScheduledJob.workspace_id == p.workspace_id).order_by(m.ScheduledJob.id))
    return {"items": [ser.job(j) for j in rows], "scheduler_mode": get_settings().scheduler_mode}


@router.post("/jobs", status_code=201, tags=["jobs"], summary="Create a scheduled job")
def create_job(body: JobIn, p: Editor, db: DB) -> dict[str, Any]:
    jobs.validate_job(db, p.workspace_id, body.job_type, body.target_id)
    j = m.ScheduledJob(workspace_id=p.workspace_id, name=body.name, job_type=body.job_type, target_id=body.target_id,
                       interval_seconds=body.interval_seconds, params=body.params, enabled=body.enabled,
                       max_retries=body.max_retries, retry_backoff_seconds=body.retry_backoff_seconds,
                       timeout_seconds=body.timeout_seconds,
                       next_run_at=body.start_at or datetime.now(UTC) + timedelta(seconds=body.interval_seconds))
    db.add(j)
    db.flush()
    audit.record(db, p.workspace_id, "job.created", "scheduled_job", j.id, {"type": j.job_type}, p)
    db.commit()
    return ser.job(j)


@router.patch("/jobs/{job_id}", tags=["jobs"], summary="Update or pause a job")
def patch_job(job_id: int, body: JobPatch, p: Editor, db: DB) -> dict[str, Any]:
    j = owned(db, m.ScheduledJob, job_id, p, "Job")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(j, k, v)
    audit.record(db, p.workspace_id, "job.updated", "scheduled_job", j.id, body.model_dump(exclude_unset=True), p)
    db.commit()
    return ser.job(j)


@router.delete("/jobs/{job_id}", tags=["jobs"], summary="Delete a job")
def delete_job(job_id: int, p: Editor, db: DB) -> dict[str, Any]:
    j = owned(db, m.ScheduledJob, job_id, p, "Job")
    db.delete(j)
    audit.record(db, p.workspace_id, "job.deleted", "scheduled_job", job_id, {}, p)
    db.commit()
    return {"deleted": True}


@router.post("/jobs/{job_id}/run", tags=["jobs"], summary="Run a job now (overlap-protected)")
def run_job(job_id: int, p: Editor, db: DB) -> dict[str, Any]:
    j = owned(db, m.ScheduledJob, job_id, p, "Job")
    exe = jobs.run_now(db, j, p)
    return ser.job_execution(exe)


@router.get("/jobs/executions", tags=["jobs"], summary="Job execution history")
def list_executions(p: Viewer, db: DB, page: Paging, job_id: int | None = None, status: str | None = None) -> dict[str, Any]:
    stmt = select(m.JobExecution).where(m.JobExecution.workspace_id == p.workspace_id)
    if job_id:
        stmt = stmt.where(m.JobExecution.job_id == job_id)
    if status:
        stmt = stmt.where(m.JobExecution.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(m.JobExecution.id.desc()).offset(page.offset).limit(page.page_size))
    return paged([ser.job_execution(x) for x in rows], total, page)


@router.post("/jobs/run-due", tags=["jobs"], summary="Run due jobs (for external cron triggers; needs X-Cron-Secret)")
def run_due(db: DB, x_cron_secret: str | None = Header(None)) -> dict[str, Any]:
    secret = get_settings().cron_secret
    if not secret or not x_cron_secret or not hmac.compare_digest(secret, x_cron_secret):
        raise APIError(401, "unauthorized", "Invalid cron secret.")
    ran = jobs.run_due(db, limit=20)
    maint = jobs.maintenance(db)
    return {"ran": ran, "maintenance": maint}


# ---------------------------------------------------------------- notifications


@router.get("/notifications", tags=["notifications"], summary="In-app notifications")
def list_notifications(p: CurrentPrincipal, db: DB, page: Paging, unread_only: bool = False) -> dict[str, Any]:
    stmt = select(m.Notification).where(m.Notification.workspace_id == p.workspace_id,
                                        (m.Notification.user_id.is_(None)) | (m.Notification.user_id == p.user_id))
    u = db.get(m.User, p.user_id) if p.user_id else None
    min_sev = (u.preferences or {}).get("in_app_min_severity", "info") if u else "info"
    allowed = {"info": ["info", "warning", "critical"], "warning": ["warning", "critical"], "critical": ["critical"]}[min_sev]
    stmt = stmt.where(m.Notification.severity.in_(allowed))
    if unread_only:
        stmt = stmt.where(m.Notification.read_at.is_(None))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    unread = db.scalar(select(func.count()).select_from(stmt.where(m.Notification.read_at.is_(None)).subquery())) or 0
    rows = db.scalars(stmt.order_by(m.Notification.id.desc()).offset(page.offset).limit(page.page_size))
    return {**paged([ser.notification(n) for n in rows], total, page), "unread": unread}


@router.post("/notifications/{notification_id}/read", tags=["notifications"])
def mark_read(notification_id: int, p: CurrentPrincipal, db: DB) -> dict[str, Any]:
    n = owned(db, m.Notification, notification_id, p, "Notification")
    n.read_at = n.read_at or datetime.now(UTC)
    db.commit()
    return ser.notification(n)


@router.post("/notifications/read-all", tags=["notifications"])
def mark_all_read(p: CurrentPrincipal, db: DB) -> dict[str, Any]:
    res = db.execute(update(m.Notification).where(m.Notification.workspace_id == p.workspace_id, m.Notification.read_at.is_(None))
                     .values(read_at=datetime.now(UTC)))
    db.commit()
    return {"updated": res.rowcount}


# ---------------------------------------------------------------- overview / activity / audit


@router.get("/overview", tags=["overview"], summary="Dashboard metrics computed from stored records")
def overview(p: Viewer, db: DB) -> dict[str, Any]:
    ws = p.workspace_id
    ds_health = dict(db.execute(select(m.Dataset.health, func.count()).where(m.Dataset.workspace_id == ws)
                                .group_by(m.Dataset.health)).all())
    inc_rows = db.execute(select(m.Incident.severity, func.count()).where(m.Incident.workspace_id == ws, m.Incident.status.in_(ACTIVE))
                          .group_by(m.Incident.severity)).all()
    open_by_sev = dict(inc_rows)
    since = datetime.now(UTC) - timedelta(days=7)
    drift_events = db.execute(
        select(m.DriftEvaluation.id, m.DriftEvaluation.dataset_id, m.Dataset.name, m.DriftEvaluation.overall_severity,
               m.DriftEvaluation.summary, m.DriftEvaluation.created_at)
        .join(m.Dataset, m.Dataset.id == m.DriftEvaluation.dataset_id)
        .where(m.Dataset.workspace_id == ws, m.DriftEvaluation.overall_severity.in_(("warning", "critical")),
               m.DriftEvaluation.trigger != "remediation_verification")
        .order_by(m.DriftEvaluation.id.desc()).limit(5)).all()
    job_fail = db.scalars(select(m.JobExecution).where(m.JobExecution.workspace_id == ws,
                                                       m.JobExecution.status.in_(("failed", "timed_out")))
                          .order_by(m.JobExecution.id.desc()).limit(5))
    models = list(db.scalars(select(m.MLModel).where(m.MLModel.workspace_id == ws)))
    model_status = []
    for mo in models:
        e = db.scalar(select(m.ModelEvaluation).join(m.ModelVersion, m.ModelVersion.id == m.ModelEvaluation.model_version_id)
                      .where(m.ModelVersion.model_id == mo.id).order_by(m.ModelEvaluation.window_end.desc().nulls_last()).limit(1))
        model_status.append({"model_id": mo.id, "name": mo.name, "status": e.status if e else "unknown",
                             "label_coverage": e.label_coverage if e else None,
                             "input_drift_features": (e.input_drift or {}).get("features_drifted") if e else None,
                             "performance": (e.performance or {}).get("status") if e else None})
    rem = dict(db.execute(select(m.RemediationProposal.status, func.count()).where(m.RemediationProposal.workspace_id == ws)
                          .group_by(m.RemediationProposal.status)).all())
    top = db.scalars(select(m.Incident).where(m.Incident.workspace_id == ws, m.Incident.status.in_(ACTIVE))
                     .order_by(m.Incident.priority_score.desc()).limit(5))
    day = func.date_trunc("day", m.Incident.first_seen_at)
    trend = db.execute(select(day, m.Incident.severity, func.count()).where(m.Incident.workspace_id == ws,
                                                                            m.Incident.first_seen_at >= datetime.now(UTC) - timedelta(days=14))
                       .group_by(day, m.Incident.severity).order_by(day)).all()
    check_day = func.date_trunc("day", m.CheckResult.created_at)
    checks = db.execute(select(check_day, m.CheckResult.status, func.count()).join(m.CheckRun, m.CheckRun.id == m.CheckResult.run_id)
                        .join(m.Dataset, m.Dataset.id == m.CheckRun.dataset_id)
                        .where(m.Dataset.workspace_id == ws, m.CheckResult.created_at >= datetime.now(UTC) - timedelta(days=14))
                        .group_by(check_day, m.CheckResult.status).order_by(check_day)).all()
    ws_row = db.get(m.Workspace, ws)
    return {
        "datasets": {"total": sum(ds_health.values()), "healthy": ds_health.get("healthy", 0), "warning": ds_health.get("warning", 0),
                     "failing": ds_health.get("failing", 0), "unknown": ds_health.get("unknown", 0)},
        "incidents": {"open": sum(open_by_sev.values()), "critical": open_by_sev.get("critical", 0),
                      "warning": open_by_sev.get("warning", 0),
                      "resolved_7d": db.scalar(select(func.count()).select_from(m.Incident).where(
                          m.Incident.workspace_id == ws, m.Incident.status == "resolved", m.Incident.resolved_at >= since)) or 0},
        "top_incidents": [ser.incident(i) for i in top],
        "recent_drift": [{"id": r[0], "dataset_id": r[1], "dataset_name": r[2], "severity": r[3],
                          "features_drifted": (r[4] or {}).get("features_drifted"), "created_at": ser.iso(r[5])} for r in drift_events],
        "recent_job_failures": [ser.job_execution(x) for x in job_fail],
        "models": model_status,
        "remediation": rem,
        "incident_trend": [{"day": r[0].date().isoformat(), "severity": r[1], "count": r[2]} for r in trend],
        "check_trend": [{"day": r[0].date().isoformat(), "status": r[1], "count": r[2]} for r in checks],
        "sample_data_loaded": bool((ws_row.settings or {}).get("sample_data_loaded")),
    }


@router.get("/activity", tags=["overview"], summary="Recent activity feed")
def activity(p: Viewer, db: DB, limit: int = Query(30, ge=1, le=100)) -> dict[str, Any]:
    rows = db.scalars(select(m.AuditEvent).where(m.AuditEvent.workspace_id == p.workspace_id,
                                                 m.AuditEvent.action.notin_(("user.login",)))
                      .order_by(m.AuditEvent.id.desc()).limit(limit))
    return {"items": [ser.audit_event(a) for a in rows]}


@router.get("/audit", tags=["overview"], summary="Audit log (admin)")
def audit_log(p: Admin, db: DB, page: Paging, entity_type: str | None = None, entity_id: str | None = None,
              action: str | None = None) -> dict[str, Any]:
    stmt = select(m.AuditEvent).where(m.AuditEvent.workspace_id == p.workspace_id)
    if entity_type:
        stmt = stmt.where(m.AuditEvent.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(m.AuditEvent.entity_id == entity_id)
    if action:
        stmt = stmt.where(m.AuditEvent.action.like(f"{action}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(m.AuditEvent.id.desc()).offset(page.offset).limit(page.page_size))
    return paged([ser.audit_event(a) for a in rows], total, page)


@router.get("/search", tags=["overview"], summary="Search datasets, models, incidents and lineage nodes")
def search(p: Viewer, db: DB, q: str = Query(min_length=1, max_length=100)) -> dict[str, Any]:
    like = f"%{q.lower()}%"
    ws = p.workspace_id
    ds = db.scalars(select(m.Dataset).where(m.Dataset.workspace_id == ws, func.lower(m.Dataset.name).like(like)).limit(8))
    mo = db.scalars(select(m.MLModel).where(m.MLModel.workspace_id == ws, func.lower(m.MLModel.name).like(like)).limit(5))
    inc = db.scalars(select(m.Incident).where(m.Incident.workspace_id == ws, func.lower(m.Incident.title).like(like))
                     .order_by(m.Incident.id.desc()).limit(8))
    nodes = db.scalars(select(m.LineageNode).where(m.LineageNode.workspace_id == ws, func.lower(m.LineageNode.name).like(like),
                                                   m.LineageNode.dataset_id.is_(None), m.LineageNode.model_id.is_(None)).limit(5))
    return {"datasets": [{"id": d.id, "name": d.name, "health": d.health} for d in ds],
            "models": [{"id": x.id, "name": x.name} for x in mo],
            "incidents": [{"id": i.id, "title": i.title, "severity": i.severity, "status": i.status} for i in inc],
            "lineage_nodes": [{"id": n.id, "name": n.name, "node_type": n.node_type} for n in nodes]}


# ---------------------------------------------------------------- demo helpers


@router.get("/demo/scenarios", tags=["demo"], summary="Synthetic anomaly scenarios that can be loaded")
def scenarios() -> dict[str, Any]:
    out = []
    for name in syn.SCENARIOS:
        sc = syn.scenario(name, n=50)
        out.append({"name": name, "title": sc.title, "description": sc.description, "injected": sc.injected})
    return {"items": out, "label": syn.SYNTHETIC_LABEL}


@router.post("/demo/sample-data", status_code=201, tags=["demo"], summary="Load the labelled synthetic sample data")
def load_sample(p: Editor, db: DB) -> dict[str, Any]:
    return seedsvc.seed_workspace(db, p.workspace_id, p)


@router.post("/demo/scenarios/{name}", status_code=201, tags=["demo"], summary="Load one synthetic scenario as a dataset")
def load_scenario(name: str, p: Editor, db: DB) -> dict[str, Any]:
    return seedsvc.load_scenario(db, p.workspace_id, name, p)
