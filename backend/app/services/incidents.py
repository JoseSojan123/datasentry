"""Incident creation with deduplication, reopening, timeline and verified resolution."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import bad_request
from app.db import models as m
from app.services import audit, notifications
from app.services import lineage as lsvc
from datasentry_core import impact as imp
from datasentry_core.rules import numpy_safe

ACTIVE = ("open", "acknowledged", "investigating", "reopened")
TRANSITIONS = {
    "open": {"acknowledged", "investigating", "resolved"},
    "acknowledged": {"investigating", "resolved"},
    "investigating": {"resolved", "acknowledged"},
    "reopened": {"acknowledged", "investigating", "resolved"},
    "resolved": {"reopened"},
}
SEV_ORDER = {"info": 0, "warning": 1, "critical": 2}
REOPEN_WINDOW = timedelta(days=7)


def finding_key(f: dict[str, Any]) -> str:
    return f"{f.get('source')}:{f.get('kind')}:{f.get('column') or ''}"


def fingerprint(scope: str, findings: list[dict[str, Any]]) -> str:
    keys = sorted({finding_key(f) for f in findings})
    return hashlib.sha256(json.dumps([scope, keys]).encode()).hexdigest()[:32]


def significant(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in findings if f.get("severity") in ("warning", "critical")]


def add_event(db: Session, inc: m.Incident, event_type: str, message: str, data: dict[str, Any] | None = None,
              principal: Any = None) -> m.IncidentEvent:
    ev = m.IncidentEvent(incident_id=inc.id, event_type=event_type, message=message, data=numpy_safe(data or {}),
                         actor_user_id=getattr(principal, "user_id", None),
                         actor_label=getattr(principal, "label", None) or "system")
    db.add(ev)
    db.flush()
    return ev


def _title(ds_name: str, findings: list[dict[str, Any]]) -> str:
    kinds = sorted({f["kind"].replace("_", " ") for f in findings})
    head = ", ".join(kinds[:3]) + (f" +{len(kinds) - 3} more" if len(kinds) > 3 else "")
    return f"{ds_name}: {head}"


def upsert_dataset_incident(
    db: Session, ds: m.Dataset, version: m.DatasetVersion, findings: list[dict[str, Any]], context: dict[str, Any]
) -> tuple[m.Incident | None, bool]:
    """Create, deduplicate or reopen an incident for a dataset's findings.

    Returns (incident, created). No incident is created for info-only findings.
    """
    sig = significant(findings)
    if not sig:
        return None, False
    fp = fingerprint(f"dataset:{ds.id}", sig)
    severity = max((f["severity"] for f in sig), key=lambda s: SEV_ORDER[s])
    impact = lsvc.dataset_impact(db, ds)
    prio = imp.priority(severity, ds.criticality, impact)
    impact_doc = {**impact, "consequences": imp.consequences(sig, impact),
                  "investigation_steps": imp.investigation_steps(sig, impact)}
    costs = (ds.settings or {}).get("consumer_costs_per_hour")
    if costs:
        impact_doc["cost_estimate"] = imp.cost_estimate(impact, {int(k): float(v) for k, v in costs.items()},
                                                        float((ds.settings or {}).get("assumed_disruption_hours", 4)))
    now = datetime.now(UTC)
    existing = db.scalar(select(m.Incident).where(
        m.Incident.workspace_id == ds.workspace_id, m.Incident.fingerprint == fp, m.Incident.status.in_(ACTIVE)
    ).order_by(m.Incident.id.desc()).limit(1))
    if existing:
        existing.occurrence_count += 1
        existing.last_seen_at = now
        existing.version_id = version.id
        existing.findings = numpy_safe(sig)
        existing.impact = numpy_safe(impact_doc)
        existing.priority, existing.priority_score = prio, prio["score"]
        add_event(db, existing, "recurred", f"Same findings detected again on version {version.version_number} "
                  f"(occurrence {existing.occurrence_count}); alert suppressed by deduplication.", {"version_id": version.id})
        return existing, False
    recent_resolved = db.scalar(select(m.Incident).where(
        m.Incident.workspace_id == ds.workspace_id, m.Incident.fingerprint == fp, m.Incident.status == "resolved",
        m.Incident.resolved_at >= now - REOPEN_WINDOW).order_by(m.Incident.id.desc()).limit(1))
    if recent_resolved:
        inc = recent_resolved
        inc.status = "reopened"
        inc.occurrence_count += 1
        inc.last_seen_at = now
        inc.version_id = version.id
        inc.findings = numpy_safe(sig)
        inc.impact = numpy_safe(impact_doc)
        inc.priority, inc.priority_score = prio, prio["score"]
        add_event(db, inc, "reopened", f"Findings returned on version {version.version_number} after resolution.",
                  {"version_id": version.id})
        created = False
    else:
        inc = m.Incident(workspace_id=ds.workspace_id, dataset_id=ds.id, version_id=version.id, title=_title(ds.name, sig)[:240],
                         severity=severity, status="open", fingerprint=fp, findings=numpy_safe(sig), impact=numpy_safe(impact_doc),
                         priority=prio, priority_score=prio["score"])
        db.add(inc)
        db.flush()
        add_event(db, inc, "detected",
                  f"{len(sig)} finding(s) on version {version.version_number}: " + "; ".join(f["message"][:120] for f in sig[:3]),
                  {"version_id": version.id, **context})
        if impact["affected"]:
            add_event(db, inc, "impact_assessed",
                      f"{impact['counts']['total']} downstream node(s) affected "
                      f"({impact['counts']['confirmed']} confirmed, {impact['counts']['potential']} potential); "
                      f"priority {prio['urgency']} (score {prio['score']}).", {"counts": impact["counts"]})
        created = True
    notifications.notify(db, ds.workspace_id, "incident", f"{severity.upper()}: {inc.title}",
                         body=sig[0]["message"][:500], severity=severity, link=f"/incidents/{inc.id}",
                         dedup_key=f"incident:{inc.id}")
    audit.record(db, ds.workspace_id, "incident.created" if created else "incident.reopened", "incident", inc.id,
                 {"dataset_id": ds.id, "severity": severity, "findings": len(sig)})
    return inc, created


def resolve_if_cleared(db: Session, ds: m.Dataset, version: m.DatasetVersion, current_findings: list[dict[str, Any]],
                       reason: str) -> list[m.Incident]:
    """Resolve unresolved incidents whose findings are all absent from a fresh check of the active version."""
    present = {finding_key(f) for f in significant(current_findings)}
    resolved = []
    for inc in db.scalars(select(m.Incident).where(m.Incident.dataset_id == ds.id, m.Incident.status.in_(ACTIVE))):
        keys = {finding_key(f) for f in inc.findings}
        if keys and not (keys & present):
            resolve(db, inc, {"type": "verified", "reason": reason, "verified_on_version": version.version_number,
                              "verified_version_id": version.id, "checked_findings": sorted(keys)})
            resolved.append(inc)
    return resolved


def resolve(db: Session, inc: m.Incident, resolution: dict[str, Any], principal: Any = None) -> None:
    inc.status = "resolved"
    inc.resolved_at = datetime.now(UTC)
    inc.resolution = numpy_safe(resolution)
    msg = resolution.get("message") or (
        f"Resolved after verification: previously failing checks pass on version {resolution.get('verified_on_version')}."
        if resolution.get("type") == "verified" else f"Resolved manually: {resolution.get('note', '')}")
    add_event(db, inc, "resolved", msg, resolution, principal)
    notifications.notify(db, inc.workspace_id, "incident_resolved", f"Resolved: {inc.title}", body=msg, severity="info",
                         link=f"/incidents/{inc.id}", dedup_key=f"incident-resolved:{inc.id}:{inc.occurrence_count}")


def transition(db: Session, inc: m.Incident, new_status: str, principal: Any, note: str | None = None) -> None:
    if new_status not in TRANSITIONS.get(inc.status, set()):
        raise bad_request(f"Cannot move an incident from '{inc.status}' to '{new_status}'.", code="invalid_transition")
    if new_status == "resolved":
        if not note or len(note.strip()) < 5:
            raise bad_request("Manual resolution requires a note explaining why the incident is resolved.")
        resolve(db, inc, {"type": "manual", "note": note.strip()}, principal)
    else:
        old = inc.status
        inc.status = new_status
        if new_status == "acknowledged" and inc.acknowledged_at is None:
            inc.acknowledged_at = datetime.now(UTC)
        if new_status == "reopened":
            inc.resolved_at = None
        add_event(db, inc, "status_changed", f"Status changed from {old} to {new_status}." + (f" Note: {note}" if note else ""),
                  {"from": old, "to": new_status}, principal)
    audit.record(db, inc.workspace_id, f"incident.{new_status}", "incident", inc.id, {"note": note}, principal)


def resolution_seconds(inc: m.Incident) -> float | None:
    if inc.resolved_at and inc.first_seen_at:
        return (inc.resolved_at - inc.first_seen_at).total_seconds()
    return None
