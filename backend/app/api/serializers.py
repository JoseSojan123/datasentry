"""Explicit serializers: only whitelisted fields leave the API (no password hashes, key hashes, storage keys)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.db import models as m


def iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def user(u: m.User) -> dict[str, Any]:
    return {"id": u.id, "email": u.email, "display_name": u.display_name, "role": u.role, "workspace_id": u.workspace_id,
            "preferences": u.preferences or {}, "created_at": iso(u.created_at), "last_login_at": iso(u.last_login_at)}


def api_key(k: m.ApiKey) -> dict[str, Any]:
    return {"id": k.id, "name": k.name, "prefix": f"dsk_{k.prefix}_…", "role": k.role, "created_at": iso(k.created_at),
            "last_used_at": iso(k.last_used_at), "expires_at": iso(k.expires_at), "revoked_at": iso(k.revoked_at),
            "active": k.revoked_at is None}


def version(v: m.DatasetVersion, with_columns: bool = False) -> dict[str, Any]:
    d = {"id": v.id, "dataset_id": v.dataset_id, "version_number": v.version_number, "status": v.status,
         "ingestion_status": v.ingestion_status, "ingestion_error": v.ingestion_error, "ingestion_duration_ms": v.ingestion_duration_ms,
         "original_filename": v.original_filename, "file_format": v.file_format, "checksum": v.checksum, "size_bytes": v.size_bytes,
         "row_count": v.row_count, "column_count": v.column_count, "malformed_rows": v.malformed_rows,
         "schema_fingerprint": v.schema_fingerprint, "parse_warnings": v.parse_warnings, "is_known_good": v.is_known_good,
         "parent_version_id": v.parent_version_id, "origin": v.origin, "origin_detail": v.origin_detail,
         "created_at": iso(v.created_at)}
    if with_columns:
        d["columns"] = [c.to_dict() for c in v.columns]
    return d


def dataset(ds: m.Dataset, current: m.DatasetVersion | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": ds.id, "name": ds.name, "description": ds.description, "owner": ds.owner, "tags": ds.tags or [],
            "domain": ds.domain, "criticality": ds.criticality, "source_type": ds.source_type, "primary_key": ds.primary_key or [],
            "freshness_column": ds.freshness_column, "reference_version_id": ds.reference_version_id,
            "current_version_id": ds.current_version_id, "health": ds.health, "settings": ds.settings or {},
            "created_at": iso(ds.created_at), "updated_at": iso(ds.updated_at),
            "current_version": version(current) if current else None, **(extra or {})}


def profile(p: m.Profile) -> dict[str, Any]:
    return {"id": p.id, "dataset_id": p.dataset_id, "version_id": p.version_id, "summary": p.summary, "columns": p.columns,
            "config": p.config, "duration_ms": p.duration_ms, "created_at": iso(p.created_at)}


def rule(r: m.QualityRule, last: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": r.id, "dataset_id": r.dataset_id, "name": r.name, "rule_type": r.rule_type, "columns": r.columns,
            "config": r.config, "severity": r.severity, "enabled": r.enabled, "created_at": iso(r.created_at),
            "updated_at": iso(r.updated_at), "last_result": last}


def check_result(r: m.CheckResult) -> dict[str, Any]:
    return {"id": r.id, "run_id": r.run_id, "rule_id": r.rule_id, "rule": r.rule_snapshot, "status": r.status,
            "rows_evaluated": r.rows_evaluated, "failed_rows": r.failed_rows, "failure_pct": r.failure_pct,
            "duration_ms": r.duration_ms, "observed": r.observed, "expected": r.expected, "explanation": r.explanation,
            "sample_failures": r.sample_failures, "created_at": iso(r.created_at)}


def check_run(run: m.CheckRun, results: list[m.CheckResult] | None = None) -> dict[str, Any]:
    d = {"id": run.id, "dataset_id": run.dataset_id, "version_id": run.version_id, "trigger": run.trigger,
         "summary": run.summary, "duration_ms": run.duration_ms, "created_at": iso(run.created_at)}
    if results is not None:
        d["results"] = [check_result(r) for r in results]
    return d


def drift_eval(ev: m.DriftEvaluation, with_features: bool = True) -> dict[str, Any]:
    d = {"id": ev.id, "dataset_id": ev.dataset_id, "reference_version_id": ev.reference_version_id,
         "current_version_id": ev.current_version_id, "config": ev.config, "windows": ev.windows, "summary": ev.summary,
         "other_findings": ev.other_findings, "overall_severity": ev.overall_severity, "trigger": ev.trigger,
         "created_at": iso(ev.created_at)}
    if with_features:
        d["features"] = [{"id": f.id, "feature": f.feature, "semantic_type": f.semantic_type, "method": f.method,
                          "status": f.status, "severity": f.severity, "n_reference": f.n_reference, "n_current": f.n_current,
                          "significant": f.significant, "statistics": f.statistics, "evidence": f.evidence,
                          "explanation": f.explanation} for f in ev.features]
    return d


def comparison(c: m.VersionComparison) -> dict[str, Any]:
    return {"id": c.id, "dataset_id": c.dataset_id, "base_version_id": c.base_version_id, "target_version_id": c.target_version_id,
            "result": c.result, "overall_severity": c.overall_severity, "created_at": iso(c.created_at)}


def model(mo: m.MLModel, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": mo.id, "name": mo.name, "description": mo.description, "task": mo.task, "target": mo.target,
            "positive_label": mo.positive_label, "reference_dataset_id": mo.reference_dataset_id, "criticality": mo.criticality,
            "owner": mo.owner, "created_at": iso(mo.created_at), **(extra or {})}


def model_version(mv: m.ModelVersion) -> dict[str, Any]:
    ref = mv.reference_profile or {}
    return {"id": mv.id, "model_id": mv.model_id, "version": mv.version, "input_schema": mv.input_schema,
            "baseline_metrics": mv.baseline_metrics, "artifact": mv.artifact, "feature_logging": mv.feature_logging,
            "retention_days": mv.retention_days, "reference_source": ref.get("source"),
            "reference_features": sorted((ref.get("features") or {}).keys()), "created_at": iso(mv.created_at)}


def model_eval(e: m.ModelEvaluation) -> dict[str, Any]:
    return {"id": e.id, "model_version_id": e.model_version_id, "window_start": iso(e.window_start), "window_end": iso(e.window_end),
            "n_predictions": e.n_predictions, "n_labelled": e.n_labelled, "label_coverage": e.label_coverage,
            "metrics": e.metrics, "input_drift": e.input_drift, "prediction_drift": e.prediction_drift,
            "performance": e.performance, "schema_violation_count": e.schema_violation_count, "status": e.status,
            "trigger": e.trigger, "created_at": iso(e.created_at)}


def node(n: m.LineageNode) -> dict[str, Any]:
    return {"id": n.id, "node_type": n.node_type, "name": n.name, "description": n.description, "dataset_id": n.dataset_id,
            "model_id": n.model_id, "criticality": n.criticality, "owner": n.owner, "meta": n.meta, "created_at": iso(n.created_at)}


def edge(e: m.LineageEdge) -> dict[str, Any]:
    return {"id": e.id, "source_id": e.source_id, "target_id": e.target_id, "dependency_type": e.dependency_type,
            "provenance": e.provenance, "meta": e.meta, "created_at": iso(e.created_at)}


def incident(i: m.Incident) -> dict[str, Any]:
    from app.services.incidents import resolution_seconds

    return {"id": i.id, "title": i.title, "severity": i.severity, "status": i.status, "dataset_id": i.dataset_id,
            "version_id": i.version_id, "model_id": i.model_id, "findings": i.findings, "impact": i.impact,
            "priority": i.priority, "priority_score": i.priority_score, "assigned_to": i.assigned_to,
            "occurrence_count": i.occurrence_count, "first_seen_at": iso(i.first_seen_at), "last_seen_at": iso(i.last_seen_at),
            "acknowledged_at": iso(i.acknowledged_at), "resolved_at": iso(i.resolved_at), "resolution": i.resolution,
            "resolution_seconds": resolution_seconds(i), "created_at": iso(i.created_at)}


def event(e: m.IncidentEvent) -> dict[str, Any]:
    return {"id": e.id, "event_type": e.event_type, "message": e.message, "data": e.data, "actor": e.actor_label,
            "created_at": iso(e.created_at)}


def comment(c: m.IncidentComment, author: str | None) -> dict[str, Any]:
    return {"id": c.id, "body": c.body, "author": author, "user_id": c.user_id, "created_at": iso(c.created_at)}


def proposal(p: m.RemediationProposal, executions: list[m.RemediationExecution] | None = None) -> dict[str, Any]:
    from datasentry_core.remediation import CATALOG

    spec = CATALOG.get(p.action)
    d = {"id": p.id, "incident_id": p.incident_id, "dataset_id": p.dataset_id, "version_id": p.version_id, "action": p.action,
         "title": spec.title if spec else p.action, "description": spec.description if spec else "", "params": p.params,
         "reason": p.reason, "evidence": p.evidence, "preconditions": p.preconditions, "expected_outcome": p.expected_outcome,
         "rollback": p.rollback, "risk_level": p.risk_level, "changes_data": spec.changes_data if spec else None,
         "execution_mode": p.execution_mode, "approval_required": p.approval_required, "status": p.status,
         "approved_by": p.approved_by, "approved_at": iso(p.approved_at), "created_at": iso(p.created_at),
         "updated_at": iso(p.updated_at)}
    if executions is not None:
        d["executions"] = [execution(x) for x in executions]
    return d


def execution(x: m.RemediationExecution) -> dict[str, Any]:
    return {"id": x.id, "proposal_id": x.proposal_id, "attempt": x.attempt, "status": x.status, "started_at": iso(x.started_at),
            "finished_at": iso(x.finished_at), "result": x.result, "verification": x.verification, "error": x.error}


def job(j: m.ScheduledJob) -> dict[str, Any]:
    return {"id": j.id, "name": j.name, "job_type": j.job_type, "target_id": j.target_id,
            "params": {k: v for k, v in (j.params or {}).items() if not k.startswith("_")},
            "pending_retry_attempt": (j.params or {}).get("_pending_attempt"), "interval_seconds": j.interval_seconds,
            "enabled": j.enabled, "max_retries": j.max_retries, "retry_backoff_seconds": j.retry_backoff_seconds,
            "timeout_seconds": j.timeout_seconds, "next_run_at": iso(j.next_run_at), "last_run_at": iso(j.last_run_at),
            "last_success_at": iso(j.last_success_at), "last_status": j.last_status,
            "consecutive_failures": j.consecutive_failures, "running": bool(j.locked_until), "created_at": iso(j.created_at)}


def job_execution(x: m.JobExecution) -> dict[str, Any]:
    return {"id": x.id, "job_id": x.job_id, "job_type": x.job_type, "trigger": x.trigger, "status": x.status, "attempt": x.attempt,
            "started_at": iso(x.started_at), "finished_at": iso(x.finished_at), "duration_ms": x.duration_ms, "result": x.result,
            "error": x.error, "created_at": iso(x.created_at)}


def notification(n: m.Notification) -> dict[str, Any]:
    return {"id": n.id, "kind": n.kind, "severity": n.severity, "title": n.title, "body": n.body, "link": n.link,
            "read": n.read_at is not None, "created_at": iso(n.created_at)}


def audit_event(a: m.AuditEvent) -> dict[str, Any]:
    return {"id": a.id, "action": a.action, "entity_type": a.entity_type, "entity_id": a.entity_id, "actor": a.actor_label,
            "data": a.data, "created_at": iso(a.created_at)}
