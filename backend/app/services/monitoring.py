"""Monitoring pipeline for a dataset version: profile → rules → schema diff → drift → findings →
incident → remediation proposals → (optional) auto-execution → health update.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.services import analysis, audit, incidents, notifications, quality
from app.services import datasets as dsvc
from datasentry_core.monitor import findings_from

log = logging.getLogger("datasentry.monitoring")


@dataclass
class Evaluation:
    version: m.DatasetVersion
    baseline: m.DatasetVersion | None
    profile: m.Profile
    run: m.CheckRun
    comparison: m.VersionComparison | None = None
    drift: m.DriftEvaluation | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def worst(self) -> str:
        sev = {f["severity"] for f in self.findings}
        return "critical" if "critical" in sev else "warning" if "warning" in sev else "healthy"

    def to_summary(self) -> dict[str, Any]:
        return {
            "version_id": self.version.id,
            "version_number": self.version.version_number,
            "baseline_version_id": self.baseline.id if self.baseline else None,
            "profile_id": self.profile.id,
            "check_run_id": self.run.id,
            "comparison_id": self.comparison.id if self.comparison else None,
            "drift_evaluation_id": self.drift.id if self.drift else None,
            "findings": self.findings,
            "status": self.worst,
        }


def baseline_for(db: Session, ds: m.Dataset, version: m.DatasetVersion) -> m.DatasetVersion | None:
    if ds.reference_version_id and ds.reference_version_id != version.id:
        return db.get(m.DatasetVersion, ds.reference_version_id)
    return db.scalar(select(m.DatasetVersion).where(
        m.DatasetVersion.dataset_id == ds.id, m.DatasetVersion.is_known_good.is_(True), m.DatasetVersion.id != version.id,
        m.DatasetVersion.ingestion_status == "succeeded").order_by(m.DatasetVersion.version_number.desc()).limit(1))


def evaluate_version(db: Session, ds: m.Dataset, version: m.DatasetVersion, trigger: str,
                     as_of: datetime | None = None, with_baseline: bool = True) -> Evaluation:
    profile = dsvc.profile_version(db, ds, version, as_of)
    run = quality.run_rules(db, ds, version, trigger, as_of=as_of)
    baseline = baseline_for(db, ds, version) if with_baseline else None
    ev = Evaluation(version, baseline, profile, run)
    if baseline is not None and baseline.storage_key:
        ev.comparison = analysis.run_comparison(db, ds, baseline, version)
        ev.drift = analysis.run_drift(db, ds, baseline, version, trigger=trigger)
    ev.findings = findings_from(quality.result_dicts(db, run), ev.comparison.result if ev.comparison else None,
                                analysis.drift_dict(ev.drift) if ev.drift else None)
    for f in ev.findings:
        f["version_id"] = version.id
        f["check_run_id"] = run.id
        if ev.drift and f["source"] == "drift":
            f["drift_evaluation_id"] = ev.drift.id
        if ev.comparison and f["source"] == "schema":
            f["comparison_id"] = ev.comparison.id
    return ev


def activate(db: Session, ds: m.Dataset, version: m.DatasetVersion) -> None:
    if ds.current_version_id and ds.current_version_id != version.id:
        prev = db.get(m.DatasetVersion, ds.current_version_id)
        if prev and prev.status == "active":
            prev.status = "superseded"
    version.status = "active"
    ds.current_version_id = version.id


def update_health(ds: m.Dataset, ev: Evaluation) -> None:
    ds.health = {"critical": "failing", "warning": "warning"}.get(ev.worst, "healthy")


def process_version(db: Session, ds: m.Dataset, version: m.DatasetVersion, trigger: str, principal: Any = None,
                    as_of: datetime | None = None) -> dict[str, Any]:
    """Run the full monitoring pipeline on a freshly ingested version."""
    from app.services import remediation as rsvc

    if version.ingestion_status != "succeeded":
        finding = {"id": "F1", "source": "ingestion", "kind": "ingestion_failed", "column": None, "severity": "critical",
                   "message": f"Ingestion of version {version.version_number} failed: {(version.ingestion_error or {}).get('message')}"}
        inc, created = incidents.upsert_dataset_incident(db, ds, version, [finding], {"trigger": trigger})
        if inc is not None:
            rsvc.propose_for_incident(db, inc, ds, version, [finding], ingestion_failed=True)
        db.flush()
        return {"status": "ingestion_failed", "incident_id": inc.id if inc else None, "findings": [finding]}

    ev = evaluate_version(db, ds, version, trigger, as_of)
    gate = (ds.settings or {}).get("gate_mode", "warn")
    critical = ev.worst == "critical"
    if ds.current_version_id is None or not critical or gate == "warn":
        activate(db, ds, version)
    else:
        version.status = "pending"
    version.is_known_good = not critical
    if ds.reference_version_id is None and version.is_known_good:
        ds.reference_version_id = version.id
    if ds.current_version_id == version.id:
        update_health(ds, ev)
    inc, created = incidents.upsert_dataset_incident(db, ds, version, ev.findings,
                                                     {"trigger": trigger, "check_run_id": ev.run.id,
                                                      "drift_evaluation_id": ev.drift.id if ev.drift else None,
                                                      "comparison_id": ev.comparison.id if ev.comparison else None})
    resolved: list[m.Incident] = []
    if ds.current_version_id == version.id:
        resolved = incidents.resolve_if_cleared(db, ds, version, ev.findings,
                                                f"Monitoring of new version {version.version_number} found none of the incident's findings.")
    proposals = []
    if inc is not None and inc.status in incidents.ACTIVE:
        proposals = rsvc.propose_for_incident(db, inc, ds, version, ev.findings)
        rsvc.run_auto_actions(db, proposals)
    if version.status == "pending" and critical:
        notifications.notify(db, ds.workspace_id, "gate", f"{ds.name} v{version.version_number} held back by the validation gate",
                             body="Critical findings; consumers stay on the current version until a human promotes or rejects it.",
                             severity="warning", link=f"/datasets/{ds.id}", dedup_key=f"gate:{version.id}")
    audit.record(db, ds.workspace_id, "monitoring.completed", "dataset_version", version.id,
                 {"dataset_id": ds.id, "status": ev.worst, "findings": len(ev.findings), "trigger": trigger,
                  "incident_id": inc.id if inc else None}, principal)
    db.flush()
    return {**ev.to_summary(), "incident_id": inc.id if inc else None, "incident_created": created,
            "resolved_incident_ids": [r.id for r in resolved], "proposal_ids": [p.id for p in proposals],
            "version_status": version.status, "evaluated_at": datetime.now(UTC).isoformat()}
