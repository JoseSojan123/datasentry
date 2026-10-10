"""Persisted drift evaluations and version comparisons."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import bad_request
from app.db import models as m
from app.services import datasets as dsvc
from datasentry_core.drift import DriftConfig, evaluate_drift, slice_window
from datasentry_core.rules import numpy_safe
from datasentry_core.schema_diff import DiffConfig, compare_versions


def drift_config_for(ds: m.Dataset, overrides: dict[str, Any] | None = None) -> DriftConfig:
    base = (ds.settings or {}).get("drift", {})
    try:
        return DriftConfig.from_dict({**base, **(overrides or {})})
    except (TypeError, ValueError) as exc:
        raise bad_request(f"Invalid drift configuration: {exc}") from exc


def diff_config_for(ds: m.Dataset) -> DiffConfig:
    s = (ds.settings or {}).get("schema_changes", {})
    return DiffConfig(
        null_pct_warning_pp=float(s.get("null_pct_warning_pp", 5)),
        null_pct_critical_pp=float(s.get("null_pct_critical_pp", 20)),
        row_count_change_ratio=float(s.get("row_count_change_ratio", 0.3)),
        duplicate_increase_pp=float(s.get("duplicate_increase_pp", 1)),
        policy=dict(s.get("policy", {})),
    )


def confirmed_renames(db: Session, dataset_id: int) -> dict[str, str]:
    rows = db.scalars(select(m.RenameDecision).where(m.RenameDecision.dataset_id == dataset_id,
                                                    m.RenameDecision.decision == "confirmed"))
    return {r.from_column: r.to_column for r in rows}


def rejected_renames(db: Session, dataset_id: int) -> set[tuple[str, str]]:
    rows = db.scalars(select(m.RenameDecision).where(m.RenameDecision.dataset_id == dataset_id,
                                                    m.RenameDecision.decision == "rejected"))
    return {(r.from_column, r.to_column) for r in rows}


def run_drift(
    db: Session,
    ds: m.Dataset,
    reference: m.DatasetVersion,
    current: m.DatasetVersion,
    config: dict[str, Any] | None = None,
    windows: dict[str, Any] | None = None,
    trigger: str = "manual",
) -> m.DriftEvaluation:
    cfg = drift_config_for(ds, config)
    ref_df = dsvc.load_frame(db, reference)
    cur_df = dsvc.load_frame(db, current)
    windows = windows or {}
    try:
        ref_df = slice_window(ref_df, windows.get("column"), windows.get("reference_start"), windows.get("reference_end"))
        cur_df = slice_window(cur_df, windows.get("column"), windows.get("current_start"), windows.get("current_end"))
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    res = evaluate_drift(ref_df, cur_df, {c.name: c.semantic_type for c in reference.columns},
                         {c.name: c.semantic_type for c in current.columns}, cfg)
    ev = m.DriftEvaluation(dataset_id=ds.id, reference_version_id=reference.id, current_version_id=current.id,
                           config=numpy_safe(res["config"]), windows=numpy_safe(windows), summary=numpy_safe(res["summary"]),
                           other_findings=numpy_safe(res["other_findings"]), overall_severity=res["summary"]["overall_severity"],
                           trigger=trigger)
    for f in res["features"]:
        ev.features.append(m.DriftFeatureResult(
            feature=f["feature"], semantic_type=f["semantic_type"], method=f["method"], status=f["status"],
            severity=f["severity"], n_reference=f["n_reference"], n_current=f["n_current"], significant=f["significant"],
            statistics=numpy_safe(f["statistics"]), evidence=numpy_safe(f["evidence"]), explanation=f["explanation"]))
    db.add(ev)
    db.flush()
    return ev


def drift_dict(ev: m.DriftEvaluation) -> dict[str, Any]:
    return {"summary": ev.summary, "other_findings": ev.other_findings,
            "features": [{"feature": f.feature, "status": f.status, "severity": f.severity, "statistics": f.statistics,
                          "explanation": f.explanation} for f in ev.features]}


def ensure_profile(db: Session, ds: m.Dataset, v: m.DatasetVersion) -> m.Profile:
    return dsvc.latest_profile(db, v.id) or dsvc.profile_version(db, ds, v)


def run_comparison(db: Session, ds: m.Dataset, base: m.DatasetVersion, target: m.DatasetVersion) -> m.VersionComparison:
    bp = ensure_profile(db, ds, base)
    tp = ensure_profile(db, ds, target)
    res = compare_versions(
        [c.to_dict() for c in base.columns], [c.to_dict() for c in target.columns],
        {"dataset": bp.summary, "columns": bp.columns}, {"dataset": tp.summary, "columns": tp.columns},
        diff_config_for(ds), confirmed_renames(db, ds.id),
    )
    rejected = rejected_renames(db, ds.id)
    if rejected:
        res["rename_candidates"] = [c for c in res["rename_candidates"] if (c["from"], c["to"]) not in rejected]
        res["changes"] = [c for c in res["changes"]
                          if not (c["kind"] == "rename_candidate" and (c["column"], c.get("to")) in rejected)]
    comp = m.VersionComparison(dataset_id=ds.id, base_version_id=base.id, target_version_id=target.id,
                               result=numpy_safe(res), overall_severity=res["summary"]["overall_severity"])
    db.add(comp)
    db.flush()
    return comp
