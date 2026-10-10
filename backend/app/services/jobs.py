"""Database-backed job scheduler.

Claiming uses ``SELECT … FOR UPDATE SKIP LOCKED`` plus a lease (``locked_until``), so several workers
(or the embedded scheduler and an external trigger) never run the same job concurrently. A crashed
worker's lease simply expires and the job becomes claimable again; executions stuck in ``running``
past their timeout are marked ``timed_out`` by the maintenance sweep.

Retries: a failed run is retried after ``retry_backoff_seconds * 2**(attempt-1)`` up to
``max_retries`` times; after that a failure notification is raised and the job returns to its normal
interval.
"""

from __future__ import annotations

import logging
import os
import socket
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import bad_request
from app.db import models as m
from app.services import analysis, audit, monitoring, notifications
from app.services import datasets as dsvc
from app.services import models as msvc
from app.services.storage import storage

log = logging.getLogger("datasentry.jobs")
JOB_TYPES = ("profile", "validate", "drift", "monitor", "model_eval")
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def _target_dataset(db: Session, job: m.ScheduledJob) -> m.Dataset:
    ds = db.get(m.Dataset, job.target_id)
    if ds is None or ds.workspace_id != job.workspace_id:
        raise ValueError("target dataset no longer exists")
    if not ds.current_version_id:
        raise ValueError("dataset has no active version")
    return ds


def run_job_body(db: Session, job: m.ScheduledJob) -> dict[str, Any]:
    if job.job_type in ("profile", "validate", "drift", "monitor"):
        ds = _target_dataset(db, job)
        ver = db.get(m.DatasetVersion, ds.current_version_id)
        if job.job_type == "profile":
            p = dsvc.profile_version(db, ds, ver)
            return {"profile_id": p.id, "freshness_seconds": p.summary.get("freshness_seconds")}
        if job.job_type == "validate":
            from app.services import quality

            run = quality.run_rules(db, ds, ver, "schedule")
            return {"check_run_id": run.id, **run.summary}
        if job.job_type == "drift":
            ref_id = job.params.get("reference_version_id") or ds.reference_version_id
            if not ref_id or ref_id == ver.id:
                return {"skipped": "no distinct reference version"}
            ev = analysis.run_drift(db, ds, db.get(m.DatasetVersion, ref_id), ver, job.params.get("config"), trigger="schedule")
            return {"drift_evaluation_id": ev.id, **ev.summary}
        ev = monitoring.evaluate_version(db, ds, ver, "schedule")
        from app.services import incidents

        inc, _ = incidents.upsert_dataset_incident(db, ds, ver, ev.findings, {"trigger": "schedule", "check_run_id": ev.run.id})
        incidents.resolve_if_cleared(db, ds, ver, ev.findings, "Scheduled monitoring found none of the incident's findings.")
        monitoring.update_health(ds, ev)
        return {"status": ev.worst, "findings": len(ev.findings), "incident_id": inc.id if inc else None}
    if job.job_type == "model_eval":
        mv = db.get(m.ModelVersion, job.target_id)
        model = db.get(m.MLModel, mv.model_id) if mv else None
        if model is None or model.workspace_id != job.workspace_id:
            raise ValueError("target model version no longer exists")
        hours = int(job.params.get("window_hours", 24))
        end = datetime.now(UTC)
        ev = msvc.evaluate(db, model, mv, end - timedelta(hours=hours), end, trigger="schedule")
        return {"evaluation_id": ev.id, "status": ev.status, "n_predictions": ev.n_predictions}
    raise ValueError(f"unknown job type {job.job_type}")


def execute_job(db: Session, job: m.ScheduledJob, trigger: str, attempt: int = 1) -> m.JobExecution:
    exe = m.JobExecution(job_id=job.id, workspace_id=job.workspace_id, job_type=job.job_type, trigger=trigger,
                         status="running", attempt=attempt, started_at=datetime.now(UTC), worker=WORKER_ID)
    db.add(exe)
    db.commit()
    started = time.perf_counter()
    try:
        result = run_job_body(db, job)
        elapsed = time.perf_counter() - started
        if elapsed > job.timeout_seconds:
            raise TimeoutError(f"run took {elapsed:.0f}s, above the {job.timeout_seconds}s timeout")
        exe.status, exe.result = "succeeded", result
        job.last_success_at = datetime.now(UTC)
        job.consecutive_failures = 0
        job.next_run_at = datetime.now(UTC) + timedelta(seconds=job.interval_seconds)
    except Exception as exc:  # noqa: BLE001 - recorded on the execution
        db.rollback()
        exe = db.get(m.JobExecution, exe.id)
        job = db.get(m.ScheduledJob, job.id)
        exe.status = "timed_out" if isinstance(exc, TimeoutError) else "failed"
        exe.error = str(exc)[:1000]
        job.consecutive_failures += 1
        if attempt <= job.max_retries:
            job.next_run_at = datetime.now(UTC) + timedelta(seconds=job.retry_backoff_seconds * 2 ** (attempt - 1))
            job.params = {**job.params, "_pending_attempt": attempt + 1}
        else:
            job.next_run_at = datetime.now(UTC) + timedelta(seconds=job.interval_seconds)
            job.params = {k: v for k, v in job.params.items() if k != "_pending_attempt"}
            notifications.notify(db, job.workspace_id, "job_failed", f"Scheduled job '{job.name}' failed",
                                 body=f"{exe.error} (after {attempt} attempt(s))", severity="warning",
                                 link="/jobs", dedup_key=f"job-failed:{job.id}")
        log.warning("job %s failed attempt=%s: %s", job.id, attempt, exc)
    if exe.status == "succeeded":
        job.params = {k: v for k, v in job.params.items() if k != "_pending_attempt"}
    exe.finished_at = datetime.now(UTC)
    exe.duration_ms = round((time.perf_counter() - started) * 1000, 2)
    job.last_run_at = datetime.now(UTC)
    job.last_status = exe.status
    job.locked_until, job.locked_by = None, None
    db.commit()
    return exe


def claim_due(db: Session, limit: int = 5) -> list[int]:
    now = datetime.now(UTC)
    ids = list(db.scalars(select(m.ScheduledJob.id).where(
        m.ScheduledJob.enabled.is_(True), m.ScheduledJob.next_run_at <= now,
        (m.ScheduledJob.locked_until.is_(None)) | (m.ScheduledJob.locked_until < now),
    ).order_by(m.ScheduledJob.next_run_at).limit(limit).with_for_update(skip_locked=True)))
    for jid in ids:
        job = db.get(m.ScheduledJob, jid)
        job.locked_until = now + timedelta(seconds=job.timeout_seconds + 60)
        job.locked_by = WORKER_ID
    db.commit()
    return ids


def run_due(db: Session, limit: int = 5) -> list[dict[str, Any]]:
    out = []
    for jid in claim_due(db, limit):
        job = db.get(m.ScheduledJob, jid)
        attempt = int(job.params.get("_pending_attempt", 1))
        exe = execute_job(db, job, "retry" if attempt > 1 else "schedule", attempt)
        out.append({"job_id": jid, "execution_id": exe.id, "status": exe.status})
    return out


def run_now(db: Session, job: m.ScheduledJob, principal: Any) -> m.JobExecution:
    now = datetime.now(UTC)
    if job.locked_until and job.locked_until > now:
        from app.core.errors import conflict

        raise conflict("This job is already running; overlapping runs are prevented.")
    job.locked_until, job.locked_by = now + timedelta(seconds=job.timeout_seconds + 60), WORKER_ID
    db.commit()
    audit.record(db, job.workspace_id, "job.run_now", "scheduled_job", job.id, {}, principal)
    return execute_job(db, job, "manual")


def validate_job(db: Session, workspace_id: int, job_type: str, target_id: int | None) -> None:
    if job_type not in JOB_TYPES:
        raise bad_request(f"job_type must be one of {', '.join(JOB_TYPES)}")
    if job_type == "model_eval":
        mv = db.get(m.ModelVersion, target_id) if target_id else None
        model = db.get(m.MLModel, mv.model_id) if mv else None
        if model is None or model.workspace_id != workspace_id:
            raise bad_request("target_id must be a model version in this workspace")
    else:
        ds = db.get(m.Dataset, target_id) if target_id else None
        if ds is None or ds.workspace_id != workspace_id:
            raise bad_request("target_id must be a dataset in this workspace")


def maintenance(db: Session) -> dict[str, Any]:
    """Global housekeeping: expire demo workspaces, apply prediction retention, close stale runs."""
    now = datetime.now(UTC)
    expired = list(db.scalars(select(m.Workspace).where(m.Workspace.is_demo.is_(True), m.Workspace.expires_at < now)))
    for ws in expired:
        storage.delete_workspace(db, ws.id)
        db.delete(ws)
    db.commit()
    purged = msvc.purge_old_predictions(db)
    stale = db.execute(update(m.JobExecution).where(
        m.JobExecution.status == "running", m.JobExecution.started_at < now - timedelta(hours=1)
    ).values(status="timed_out", error="Worker stopped before the run finished (lease expired).", finished_at=now))
    db.commit()
    return {"expired_demo_workspaces": len(expired), "purged_predictions": purged, "stale_executions": stale.rowcount}


def worker_loop(stop_event: Any = None) -> None:
    """Poll for due jobs forever (used by the worker container and the embedded scheduler thread)."""
    from app.db.session import SessionLocal

    settings = get_settings()
    last_maintenance = 0.0
    log.info("scheduler started worker=%s poll=%ss", WORKER_ID, settings.scheduler_poll_seconds)
    while not (stop_event and stop_event.is_set()):
        db = SessionLocal()
        try:
            ran = run_due(db)
            if ran:
                log.info("ran %d job(s)", len(ran))
            if time.monotonic() - last_maintenance > 600:
                res = maintenance(db)
                last_maintenance = time.monotonic()
                if any(res.values()):
                    log.info("maintenance %s", res)
        except Exception:  # noqa: BLE001 - keep the loop alive
            log.exception("scheduler iteration failed")
            db.rollback()
        finally:
            db.close()
        if stop_event:
            stop_event.wait(settings.scheduler_poll_seconds)
        else:
            time.sleep(settings.scheduler_poll_seconds)
