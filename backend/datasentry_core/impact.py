"""Business-impact scoring and investigation guidance for incidents.

Priority score (0–100) is a transparent weighted sum; every component is returned so the UI can
show how the number was derived:

    severity        info 10 | warning 25 | critical 40
    source          dataset criticality: low 0 | medium 5 | high 10 | critical 15
    downstream      sum over affected nodes of criticality weight × provenance factor / depth,
                    capped at 30 (confirmed impact factor 1.0, potential 0.5)
    models_reports  +5 per affected model or report, capped at 15

Urgency: P1 ≥ 70, P2 ≥ 45, P3 ≥ 25, otherwise P4.

No monetary figures are produced unless the user configured ``estimated_cost_per_hour`` on a
consumer; any such estimate is labelled as a user-configured assumption.
"""

from __future__ import annotations

from typing import Any

SEVERITY_POINTS = {"info": 10, "warning": 25, "critical": 40}
CRITICALITY_POINTS = {"low": 0, "medium": 5, "high": 10, "critical": 15}
CRITICALITY_WEIGHT = {"low": 0.5, "medium": 1.0, "high": 2.0, "critical": 3.0}


def priority(severity: str, source_criticality: str, impact: dict[str, Any] | None) -> dict[str, Any]:
    sev = SEVERITY_POINTS.get(severity, 10)
    src = CRITICALITY_POINTS.get(source_criticality, 5)
    downstream = 0.0
    mr = 0
    for n in (impact or {}).get("affected", []):
        factor = 1.0 if n["impact"] == "confirmed" else 0.5
        downstream += CRITICALITY_WEIGHT.get(n.get("criticality", "medium"), 1.0) * factor * 3 / max(n["depth"], 1)
        if n["type"] in ("model", "report", "consumer"):
            mr += 5
    downstream = min(downstream, 30.0)
    mr = min(mr, 15)
    score = round(min(100.0, sev + src + downstream + mr), 1)
    urgency = "P1" if score >= 70 else "P2" if score >= 45 else "P3" if score >= 25 else "P4"
    return {
        "score": score,
        "urgency": urgency,
        "components": {"severity": sev, "source_criticality": src, "downstream": round(downstream, 2), "models_reports": mr},
        "method": "weighted-sum v1 (see docs/methodology.md#incident-priority)",
    }


def consequences(findings: list[dict[str, Any]], impact: dict[str, Any] | None) -> list[str]:
    """Plain-language potential consequences derived from finding kinds and affected node types."""
    kinds = {f.get("kind") for f in findings}
    affected = (impact or {}).get("affected", [])
    models = [n["name"] for n in affected if n["type"] == "model"]
    reports = [n["name"] for n in affected if n["type"] in ("report", "consumer")]
    transforms = [n["name"] for n in affected if n["type"] in ("transformation", "feature_table")]
    out: list[str] = []
    if kinds & {"column_removed", "type_changed", "schema"}:
        if transforms:
            out.append(f"Transformations that read the changed columns may fail: {', '.join(transforms[:4])}.")
        if reports:
            out.append(f"Reports depending on this data may break or show blanks: {', '.join(reports[:4])}.")
    if kinds & {"not_null", "missingness_increase", "null_pct_increase", "null_pct_increase_large"}:
        if models:
            out.append(f"Models receiving more missing inputs may produce degraded or failed predictions: {', '.join(models[:4])}.")
        if reports:
            out.append(f"Aggregates in {', '.join(reports[:3])} may be under-counted where values are missing.")
    if kinds & {"freshness"}:
        out.append("Consumers may be operating on stale data; time-sensitive outputs (forecasts, daily reports) may be invalid.")
    if kinds & {"drift", "distribution_change"} and models:
        out.append(
            f"Input drift affects {', '.join(models[:4])}. Drift does not by itself prove accuracy has dropped; "
            "check performance once labels arrive."
        )
    if kinds & {"unique", "duplicate_rows", "duplicate_increase"}:
        out.append("Duplicate records can double-count metrics and break joins that assume unique keys.")
    if kinds & {"allowed_values", "category_added"}:
        out.append("Unexpected categories may fall through mapping logic or be grouped as 'unknown' downstream.")
    if kinds & {"referential_integrity"}:
        out.append("Orphaned keys will drop out of inner joins, silently reducing downstream row counts.")
    if not out and affected:
        out.append(f"{len(affected)} downstream node(s) consume this data and may be affected.")
    if not affected:
        out.append("No downstream dependencies are registered; impact beyond this dataset is unknown.")
    return out


def investigation_steps(findings: list[dict[str, Any]], impact: dict[str, Any] | None) -> list[str]:
    kinds = {f.get("kind") for f in findings}
    steps = ["Open the evidence for each finding and confirm the observed values against the source system."]
    if kinds & {"column_removed", "type_changed", "rename_candidate", "schema"}:
        steps.append("Compare the schema with the previous version and check with the producer whether the change was intentional.")
        steps.append("If a column was renamed, confirm the rename candidate so future comparisons map it correctly.")
    if kinds & {"not_null", "missingness_increase", "null_pct_increase", "null_pct_increase_large"}:
        steps.append("Check whether the missing values come from a specific source, partition or time range.")
    if kinds & {"drift"}:
        steps.append("Review the per-feature histograms; distinguish a genuine population change from a pipeline bug (units, encoding).")
    if kinds & {"freshness"}:
        steps.append("Check the upstream ingestion job's last successful run and scheduler status.")
    if kinds & {"unique", "duplicate_rows", "duplicate_increase"}:
        steps.append("Check for replayed batches or a join fan-out upstream.")
    if (impact or {}).get("affected"):
        steps.append("Notify owners of the confirmed downstream consumers before they consume this version.")
    steps.append("Choose a remediation (quarantine, restore last known good, or a configured fix) and re-validate afterwards.")
    return steps


def cost_estimate(impact: dict[str, Any] | None, node_costs: dict[int, float], hours: float) -> dict[str, Any] | None:
    """Optional, user-configured cost estimate. Returns None when no costs are configured."""
    relevant = {n["node_id"]: node_costs[n["node_id"]] for n in (impact or {}).get("affected", []) if n["node_id"] in node_costs}
    if not relevant:
        return None
    total = sum(relevant.values()) * hours
    return {
        "label": "User-configured estimate (not measured)",
        "assumptions": f"Sum of configured cost-per-hour for {len(relevant)} affected consumer(s) × {hours} h assumed disruption.",
        "estimated_cost": round(total, 2),
        "per_node": relevant,
    }
