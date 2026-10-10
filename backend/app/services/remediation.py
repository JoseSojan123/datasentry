"""Remediation proposals, approval, guarded execution and post-action verification.

See datasentry_core.remediation for the safety model. This module adds persistence, idempotency
(unique idempotency keys, row locks, terminal states), retry limits, execution timeouts and the
verification step that decides whether an incident can be resolved.
"""

from __future__ import annotations

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import APIError, conflict
from app.db import models as m
from app.services import audit, incidents, notifications
from app.services import datasets as dsvc
from datasentry_core import remediation as core
from datasentry_core.io import SemanticType
from datasentry_core.rules import numpy_safe

log = logging.getLogger("datasentry.remediation")
MAX_ATTEMPTS = 3
DEFAULT_TIMEOUT_S = 60
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="remediation")


def workspace_policy(db: Session, workspace_id: int) -> dict[str, Any]:
    ws = db.get(m.Workspace, workspace_id)
    r = (ws.settings or {}).get("remediation", {}) if ws else {}
    return {"mode": r.get("mode", "approval"), "auto_allowlist": r.get("auto_allowlist", []),
            "timeout_seconds": int(r.get("timeout_seconds", DEFAULT_TIMEOUT_S))}


def last_known_good(db: Session, ds: m.Dataset, exclude: int | None = None) -> m.DatasetVersion | None:
    q = select(m.DatasetVersion).where(
        m.DatasetVersion.dataset_id == ds.id, m.DatasetVersion.is_known_good.is_(True),
        m.DatasetVersion.status.notin_(("quarantined", "rejected", "failed")), m.DatasetVersion.storage_key.isnot(None))
    if exclude:
        q = q.where(m.DatasetVersion.id != exclude)
    return db.scalar(q.order_by(m.DatasetVersion.version_number.desc()).limit(1))


def _check(name: str, passed: bool, detail: str, blocking: bool = True) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail, "blocking": blocking}


def preconditions(db: Session, ds: m.Dataset, version: m.DatasetVersion | None, action: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if version is None:
        return [_check("version exists", False, "The version referenced by this proposal no longer exists.")]
    lkg = last_known_good(db, ds, exclude=version.id)
    if action in ("quarantine_version", "reject_version"):
        checks.append(_check("version not already isolated", version.status not in ("quarantined", "rejected"),
                             f"Version {version.version_number} status is '{version.status}'."))
        checks.append(_check("original data retained", bool(version.raw_storage_key),
                             "The raw upload stays in storage; nothing is deleted."))
        if ds.current_version_id == version.id:
            checks.append(_check("fallback version available", lkg is not None,
                                 f"Consumers will switch to v{lkg.version_number}." if lkg else
                                 "No earlier known-good version: the dataset will have no active version.", blocking=False))
    elif action == "restore_last_known_good":
        checks.append(_check("known-good version exists", lkg is not None,
                             f"Last known good is v{lkg.version_number}." if lkg else "No earlier version passed all critical checks."))
        checks.append(_check("restore changes the active version", lkg is not None and ds.current_version_id != lkg.id,
                             "The known-good version is already active." if lkg and ds.current_version_id == lkg.id else "OK"))
    elif action in ("apply_type_conversion", "apply_missing_value_policy"):
        col = params.get("column")
        names = {c.name: c for c in version.columns}
        checks.append(_check("column present", col in names, f"Column '{col}' {'exists' if col in names else 'is missing'} in v{version.version_number}."))
        checks.append(_check("version has data", bool(version.storage_key), "Ingested data is available."))
        checks.append(_check("writes a new version", True, "Output is stored as a new derived version; the original is untouched.",
                             blocking=False))
        if action == "apply_type_conversion":
            ok = params.get("target_type") in {t.value for t in SemanticType}
            checks.append(_check("target type valid", ok, f"Target type '{params.get('target_type')}'."))
        else:
            prof = dsvc.latest_profile(db, version.id)
            pct = (prof.columns.get(col, {}) if prof else {}).get("missing_pct")
            limit = float(params.get("max_affected_pct", 20))
            checks.append(_check("share of rows changed within limit", pct is not None and pct <= limit,
                                 f"{pct}% of rows are missing '{col}'; limit {limit}%." if pct is not None else "Profile unavailable."))
    elif action == "retry_ingestion":
        checks.append(_check("ingestion failed", version.ingestion_status == "failed", f"Ingestion status '{version.ingestion_status}'."))
        checks.append(_check("raw upload retained", bool(version.raw_storage_key), "Raw file available for re-parsing."))
    elif action in ("rerun_validation", "rerun_profiling"):
        checks.append(_check("version has data", bool(version.storage_key), "Ingested data is available."))
    return checks


def _idem_key(incident_id: int, version_id: int | None, action: str, params: dict[str, Any]) -> str:
    raw = json.dumps([incident_id, version_id, action, params], sort_keys=True, default=str)
    return "rem_" + hashlib.sha256(raw.encode()).hexdigest()[:40]


def propose_for_incident(db: Session, inc: m.Incident, ds: m.Dataset, version: m.DatasetVersion,
                         findings: list[dict[str, Any]], ingestion_failed: bool = False) -> list[m.RemediationProposal]:
    policy = workspace_policy(db, ds.workspace_id)
    sig = incidents.significant(findings)
    recs = core.recommend(sig, version_is_active=ds.current_version_id == version.id,
                          has_last_known_good=last_known_good(db, ds, exclude=version.id) is not None,
                          remediation_policy=(ds.settings or {}).get("remediation", {}), ingestion_failed=ingestion_failed)
    created = []
    by_id = {f.get("id"): f for f in sig}
    for rec in recs:
        key = _idem_key(inc.id, version.id, rec["action"], rec["params"])
        if db.scalar(select(m.RemediationProposal.id).where(m.RemediationProposal.idempotency_key == key)):
            continue
        spec = core.CATALOG[rec["action"]]
        mode = core.execution_mode(rec["action"], policy["mode"], policy["auto_allowlist"])
        status = {"recommend": "recommended_only", "approval": "proposed", "auto": "approved"}[mode]
        evidence = [by_id[a] for a in rec["addresses"] if a in by_id] or sig
        p = m.RemediationProposal(
            workspace_id=ds.workspace_id, incident_id=inc.id, dataset_id=ds.id, version_id=version.id, action=rec["action"],
            params=rec["params"], reason=rec["reason"], evidence=numpy_safe(evidence),
            preconditions=preconditions(db, ds, version, rec["action"], rec["params"]),
            expected_outcome=spec.expected_outcome, rollback=spec.rollback, risk_level=spec.risk, execution_mode=mode,
            approval_required=mode == "approval", status=status, idempotency_key=key)
        db.add(p)
        db.flush()
        created.append(p)
    if created:
        incidents.add_event(db, inc, "remediation_proposed",
                            f"{len(created)} remediation option(s) proposed: " + ", ".join(core.CATALOG[p.action].title for p in created) + ".",
                            {"proposal_ids": [p.id for p in created]})
    return created


def run_auto_actions(db: Session, proposals: list[m.RemediationProposal]) -> None:
    for p in proposals:
        if p.execution_mode == "auto" and p.status == "approved":
            try:
                execute(db, p, None, trigger="auto")
            except APIError as exc:
                log.info("auto remediation %s not executed: %s", p.id, exc.message)


def approve(db: Session, p: m.RemediationProposal, principal: Any, note: str | None = None) -> None:
    if p.status != "proposed":
        raise conflict(f"Only proposals awaiting approval can be approved (status is '{p.status}').")
    p.status, p.approved_by, p.approved_at = "approved", principal.user_id, datetime.now(UTC)
    inc = db.get(m.Incident, p.incident_id)
    incidents.add_event(db, inc, "remediation_approved", f"'{core.CATALOG[p.action].title}' approved." + (f" Note: {note}" if note else ""),
                        {"proposal_id": p.id}, principal)
    audit.record(db, p.workspace_id, "remediation.approved", "remediation_proposal", p.id, {"action": p.action, "note": note}, principal)


def reject(db: Session, p: m.RemediationProposal, principal: Any, note: str | None = None) -> None:
    if p.status not in ("proposed", "approved", "recommended_only"):
        raise conflict(f"A proposal in status '{p.status}' cannot be rejected.")
    p.status = "rejected"
    inc = db.get(m.Incident, p.incident_id)
    incidents.add_event(db, inc, "remediation_rejected", f"'{core.CATALOG[p.action].title}' rejected." + (f" Note: {note}" if note else ""),
                        {"proposal_id": p.id}, principal)
    audit.record(db, p.workspace_id, "remediation.rejected", "remediation_proposal", p.id, {"action": p.action, "note": note}, principal)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _with_timeout(fn, timeout: int):
    fut = _pool.submit(fn)
    try:
        return fut.result(timeout=timeout)
    except FutureTimeout as exc:
        raise TimeoutError(f"Action exceeded the {timeout}s execution timeout.") from exc


def _derived_version(db: Session, ds: m.Dataset, parent: m.DatasetVersion, df, schema, detail: dict[str, Any]) -> m.DatasetVersion:
    number = (db.scalar(select(func.max(m.DatasetVersion.version_number)).where(m.DatasetVersion.dataset_id == ds.id)) or 0) + 1
    v = m.DatasetVersion(dataset_id=ds.id, version_number=number, file_format="parquet", ingestion_status="succeeded",
                         status="pending", parent_version_id=parent.id, origin="remediation", origin_detail=numpy_safe(detail),
                         original_filename=f"derived-from-v{parent.version_number}.parquet")
    db.add(v)
    db.flush()
    dsvc.store_frame(db, ds, v, df, schema)
    return v


def _isolate(db: Session, ds: m.Dataset, version: m.DatasetVersion, status: str) -> dict[str, Any]:
    from app.services.monitoring import activate

    prev_active = ds.current_version_id
    version.status = status
    version.is_known_good = False
    new_active = None
    if prev_active == version.id:
        lkg = last_known_good(db, ds, exclude=version.id)
        if lkg:
            activate(db, ds, lkg)
            new_active = lkg.version_number
        else:
            ds.current_version_id = None
    return {"version": version.version_number, "new_status": status, "active_version_before":
            db.get(m.DatasetVersion, prev_active).version_number if prev_active else None,
            "active_version_after": new_active if prev_active == version.id else
            (db.get(m.DatasetVersion, ds.current_version_id).version_number if ds.current_version_id else None)}


def _perform(db: Session, p: m.RemediationProposal, ds: m.Dataset, version: m.DatasetVersion, timeout: int) -> tuple[dict[str, Any], m.DatasetVersion | None]:
    """Execute the action. Returns (result, version_to_verify)."""
    from app.services.monitoring import activate

    a = p.action
    if a == "quarantine_version":
        return _isolate(db, ds, version, "quarantined"), None
    if a == "reject_version":
        return _isolate(db, ds, version, "rejected"), None
    if a == "restore_last_known_good":
        lkg = last_known_good(db, ds, exclude=version.id)
        if lkg is None:
            raise core.RemediationRefused("No known-good version to restore.")
        before = ds.current_version_id
        if version.id == before:
            version.status = "superseded"
        activate(db, ds, lkg)
        return {"restored_version": lkg.version_number,
                "active_version_before": db.get(m.DatasetVersion, before).version_number if before else None}, None
    if a in ("apply_type_conversion", "apply_missing_value_policy"):
        df = dsvc.load_frame(db, version)
        schema = dsvc.schema_of(version)
        col = p.params["column"]
        if a == "apply_type_conversion":
            out, rep = _with_timeout(lambda: core.type_conversion(df, col, p.params["target_type"],
                                                                  float(p.params.get("max_failure_pct", 1.0))), timeout)
            for c in schema:
                if c.name == col:
                    c.semantic_type = SemanticType(p.params["target_type"])
        else:
            sem = next((c.semantic_type.value for c in schema if c.name == col), None)
            out, rep = _with_timeout(lambda: core.missing_value_policy(
                df, col, p.params.get("strategy", "mode"), p.params.get("value"),
                float(p.params.get("max_affected_pct", 20)), sem), timeout)
        derived = _derived_version(db, ds, version, out, schema, {"proposal_id": p.id, "action": a, "report": rep})
        return {**rep, "derived_version": derived.version_number, "derived_version_id": derived.id,
                "source_version": version.version_number}, derived
    if a == "rerun_validation":
        target = db.get(m.DatasetVersion, ds.current_version_id) if ds.current_version_id else version
        return {"revalidated_version": target.version_number}, target
    if a == "rerun_profiling":
        prof = dsvc.profile_version(db, ds, version)
        return {"profile_id": prof.id, "duration_ms": prof.duration_ms}, None
    if a == "retry_ingestion":
        dsvc.retry_ingestion(db, ds, version)
        if version.ingestion_status != "succeeded":
            raise core.RemediationRefused(f"Ingestion failed again: {(version.ingestion_error or {}).get('message')}")
        return {"ingestion_status": "succeeded", "rows": version.row_count}, None
    if a == "notify_operator":
        n = notifications.notify(db, ds.workspace_id, "operator", f"Manual review requested: {ds.name}",
                                 body=p.reason, severity="warning", link=f"/incidents/{p.incident_id}")
        return {"notification_id": n.id if n else None}, None
    raise core.RemediationRefused(f"Unknown action '{a}'.")


def _verify(db: Session, p: m.RemediationProposal, ds: m.Dataset, inc: m.Incident, target: m.DatasetVersion | None) -> dict[str, Any]:
    from app.services.monitoring import evaluate_version

    if p.action in ("notify_operator", "rerun_profiling"):
        return {"applicable": False, "passed": None,
                "note": "This action does not change data quality; the incident stays open until checks pass."}
    if p.action == "retry_ingestion":
        return {"applicable": True, "passed": True, "note": "Version ingested successfully; it will now be monitored."}
    if target is None:
        if not ds.current_version_id:
            return {"applicable": True, "passed": False, "note": "No active version remains to verify."}
        target = db.get(m.DatasetVersion, ds.current_version_id)
    ev = evaluate_version(db, ds, target, "remediation_verification")
    after = {incidents.finding_key(f): f for f in incidents.significant(ev.findings)}
    addressed = [incidents.finding_key(f) for f in p.evidence]
    checked = [{"finding": k, "present_after": k in after,
                "after_message": after[k]["message"] if k in after else None} for k in dict.fromkeys(addressed)]
    before_keys = {incidents.finding_key(f) for f in inc.findings}
    new_critical = [f for k, f in after.items() if f["severity"] == "critical" and k not in before_keys]
    passed = all(not c["present_after"] for c in checked) and not new_critical
    return {"applicable": True, "passed": passed, "verified_version_id": target.id, "verified_version": target.version_number,
            "check_run_id": ev.run.id, "drift_evaluation_id": ev.drift.id if ev.drift else None, "checked": checked,
            "new_critical_findings": new_critical, "all_findings_after": list(after.values()),
            "note": f"Previously failing checks now pass on v{target.version_number}." if passed else
                    f"Checks still failing on v{target.version_number}."}


def execute(db: Session, p: m.RemediationProposal, principal: Any, trigger: str = "manual") -> m.RemediationExecution:
    from app.services.monitoring import activate

    db.execute(select(m.RemediationProposal).where(m.RemediationProposal.id == p.id).with_for_update())
    db.refresh(p)
    if p.status in ("verified", "completed"):
        last = db.scalar(select(m.RemediationExecution).where(m.RemediationExecution.proposal_id == p.id)
                         .order_by(m.RemediationExecution.id.desc()).limit(1))
        if last:
            return last  # idempotent: already done
    if p.status == "executing":
        raise conflict("This remediation is already executing.")
    if p.status == "proposed":
        raise APIError(409, "approval_required", "This action requires approval before it can be executed.")
    if p.status == "recommended_only":
        raise APIError(409, "recommend_only", "The workspace is in recommend-only mode; execution is disabled.")
    if p.status == "rejected":
        raise conflict("A rejected proposal cannot be executed.")
    attempts = db.scalar(select(func.count()).select_from(m.RemediationExecution).where(m.RemediationExecution.proposal_id == p.id)) or 0
    if attempts >= MAX_ATTEMPTS:
        raise APIError(409, "retry_limit", f"Retry limit reached ({MAX_ATTEMPTS} attempts). Review the failures.")
    ds = db.get(m.Dataset, p.dataset_id) if p.dataset_id else None
    version = db.get(m.DatasetVersion, p.version_id) if p.version_id else None
    inc = db.get(m.Incident, p.incident_id)
    exe = m.RemediationExecution(proposal_id=p.id, attempt=attempts + 1, status="running",
                                 executed_by=getattr(principal, "user_id", None))
    db.add(exe)
    checks = preconditions(db, ds, version, p.action, p.params) if ds else []
    p.preconditions = checks
    failed = [c for c in checks if c["blocking"] and not c["passed"]]
    if failed:
        exe.status, exe.finished_at = "failed", datetime.now(UTC)
        exe.error = "Precondition failed: " + "; ".join(f"{c['name']} ({c['detail']})" for c in failed)
        p.status = "failed"
        incidents.add_event(db, inc, "remediation_failed", f"'{core.CATALOG[p.action].title}' not executed. {exe.error}",
                            {"proposal_id": p.id}, principal)
        audit.record(db, p.workspace_id, "remediation.precondition_failed", "remediation_proposal", p.id, {"error": exe.error}, principal)
        db.commit()
        return exe
    p.status = "executing"
    db.commit()  # make the executing state visible; prevents concurrent double execution
    timeout = workspace_policy(db, p.workspace_id)["timeout_seconds"]
    try:
        result, target = _perform(db, p, ds, version, timeout)
        db.flush()
    except (core.RemediationRefused, TimeoutError, FileNotFoundError, APIError) as exc:
        db.rollback()
        msg = getattr(exc, "message", None) or str(exc)
        exe = db.get(m.RemediationExecution, exe.id)
        p = db.get(m.RemediationProposal, p.id)
        exe.status = "timed_out" if isinstance(exc, TimeoutError) else "failed"
        exe.finished_at, exe.error = datetime.now(UTC), msg
        p.status = "failed"
        inc = db.get(m.Incident, p.incident_id)
        incidents.add_event(db, inc, "remediation_failed", f"'{core.CATALOG[p.action].title}' failed: {msg} Original data preserved.",
                            {"proposal_id": p.id, "execution_id": exe.id}, principal)
        audit.record(db, p.workspace_id, "remediation.failed", "remediation_proposal", p.id, {"error": msg}, principal)
        db.commit()
        return exe
    exe.result = numpy_safe(result)
    incidents.add_event(db, inc, "remediation_executed", f"'{core.CATALOG[p.action].title}' executed ({trigger}).",
                        {"proposal_id": p.id, "result": numpy_safe(result)}, principal)
    verification = _verify(db, p, ds, inc, target)
    exe.verification = numpy_safe({k: v for k, v in verification.items() if k != "all_findings_after"})
    exe.status, exe.finished_at = "succeeded", datetime.now(UTC)
    if not verification["applicable"]:
        p.status = "completed"
    elif verification["passed"]:
        p.status = "verified"
    else:
        p.status = "verification_failed"
    derived = target if target is not None and target.origin == "remediation" and target.parent_version_id == p.version_id else None
    if derived is not None:
        if verification["passed"]:
            activate(db, ds, derived)
            derived.is_known_good = True
            if version is not None and version.status != "active":
                version.status = "superseded"
        else:
            derived.status = "rejected"
    incidents.add_event(db, inc, "remediation_verified" if verification.get("passed") else "remediation_verification",
                        verification["note"], {"proposal_id": p.id, "execution_id": exe.id, "checked": verification.get("checked")}, principal)
    if verification.get("applicable") and verification.get("passed") and ds is not None and ds.current_version_id:
        remaining = {incidents.finding_key(f) for f in verification.get("all_findings_after", [])}
        open_keys = {incidents.finding_key(f) for f in inc.findings}
        if not (open_keys & remaining):
            active = db.get(m.DatasetVersion, ds.current_version_id)
            incidents.resolve(db, inc, {"type": "verified", "remediation_proposal_id": p.id, "execution_id": exe.id,
                                        "verified_on_version": active.version_number, "verified_version_id": active.id,
                                        "message": f"Resolved after verification: {core.CATALOG[p.action].title.lower()} executed and "
                                                   f"all {len(open_keys)} originally failing check(s) pass on active version "
                                                   f"v{active.version_number}."
                                                   + (" The quarantined batch still contains the defects and is kept for inspection."
                                                      if p.action in ("quarantine_version", "reject_version", "restore_last_known_good") else "")},
                              principal)
            ds.health = "healthy" if not verification.get("all_findings_after") else "warning"
        elif inc.status == "open":
            inc.status = "investigating"
    elif inc.status == "open" and p.action != "notify_operator":
        inc.status = "investigating"
    audit.record(db, p.workspace_id, f"remediation.{p.status}", "remediation_proposal", p.id,
                 {"action": p.action, "trigger": trigger, "attempt": exe.attempt, "result": numpy_safe(result),
                  "verification_passed": verification.get("passed")}, principal)
    db.commit()
    return exe
