"""Combine rules, schema comparison and drift into a single list of findings for one batch.

Used by the API's monitoring pipeline and by the offline benchmark so both exercise identical logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from .drift import DriftConfig, evaluate_drift
from .io import ColumnSchema
from .profiling import ProfileConfig, profile_dataframe
from .rules import RuleContext, run_rule
from .schema_diff import DiffConfig, compare_versions


@dataclass
class MonitorInput:
    df: pd.DataFrame
    schema: list[ColumnSchema]
    profile: dict[str, Any] | None = None


@dataclass
class MonitorResult:
    profile: dict[str, Any]
    rule_results: list[tuple[dict[str, Any], dict[str, Any]]] = field(default_factory=list)
    diff: dict[str, Any] | None = None
    drift: dict[str, Any] | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)


def findings_from(
    rule_results: list[tuple[dict[str, Any], dict[str, Any]]],
    diff: dict[str, Any] | None,
    drift: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rule, res in rule_results:
        if res["status"] in ("fail", "error"):
            out.append({
                "source": "rule", "kind": rule["rule_type"] if res["status"] == "fail" else "error",
                "column": (rule.get("columns") or [None])[0], "columns": rule.get("columns") or [],
                "severity": rule.get("severity", "warning"), "rule_id": rule.get("id"), "rule_name": rule.get("name"),
                "message": res["explanation"], "observed": res.get("observed"),
            })
    if diff:
        for ch in diff["changes"]:
            out.append({"source": "schema", "kind": ch["kind"], "column": ch.get("column"), "severity": ch["severity"],
                        "message": ch["message"]})
    if drift:
        for f in drift["features"]:
            if f["status"] == "drift":
                out.append({"source": "drift", "kind": "drift", "column": f["feature"], "severity": f["severity"],
                            "message": f["explanation"], "statistics": {k: f["statistics"].get(k) for k in
                            ("psi", "ks_statistic", "js_distance", "p_value_adjusted")}})
        for o in drift["other_findings"]:
            if o["kind"] in ("missingness_increase", "cardinality_change"):
                if diff and o["kind"] == "missingness_increase" and any(
                    f["source"] == "schema" and f["column"] == o["feature"] and f["kind"].startswith("null_pct") for f in out
                ):
                    continue
                out.append({"source": "drift", "kind": o["kind"], "column": o["feature"], "severity": o["severity"],
                            "message": o["explanation"]})
    for i, f in enumerate(out):
        f["id"] = f"F{i + 1}"
    return out


def run_monitoring(
    current: MonitorInput,
    reference: MonitorInput | None,
    rules: list[dict[str, Any]],
    *,
    as_of: datetime,
    profile_config: ProfileConfig | None = None,
    drift_config: DriftConfig | None = None,
    diff_config: DiffConfig | None = None,
    reference_values: dict[int, dict[str, set[Any]]] | None = None,
    confirmed_renames: dict[str, str] | None = None,
) -> MonitorResult:
    ref_cats = None
    if reference is not None and reference.profile:
        ref_cats = {
            name: set(col.get("frequencies", {}).keys())
            for name, col in reference.profile["columns"].items()
            if "frequencies" in col and not col.get("frequencies_truncated")
        }
    profile = current.profile or profile_dataframe(current.df, current.schema, profile_config, as_of, ref_cats)
    ctx = RuleContext(as_of=as_of, reference_values=reference_values or {},
                      semantic_types={c.name: c.semantic_type.value for c in current.schema})
    rule_results = []
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        res = run_rule(current.df, rule["rule_type"], rule.get("columns") or [], rule.get("config") or {}, ctx)
        rule_results.append((rule, res.to_dict()))
    diff = drift = None
    if reference is not None:
        ref_profile = reference.profile or profile_dataframe(reference.df, reference.schema, profile_config, as_of)
        diff = compare_versions(
            [c.to_dict() for c in reference.schema], [c.to_dict() for c in current.schema],
            ref_profile, profile, diff_config, confirmed_renames,
        )
        drift = evaluate_drift(
            reference.df, current.df,
            {c.name: c.semantic_type.value for c in reference.schema},
            {c.name: c.semantic_type.value for c in current.schema},
            drift_config,
        )
    return MonitorResult(profile, rule_results, diff, drift, findings_from(rule_results, diff, drift))
