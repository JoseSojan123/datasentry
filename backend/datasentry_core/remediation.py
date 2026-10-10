"""Remediation catalogue, recommendation policy and pure data transformations.

Safety model
------------
* Three execution modes: ``recommend`` (never executes), ``approval`` (executes only after a human
  approves) and ``auto`` (executes immediately, allowed only for actions on the workspace allowlist
  whose risk level is ``low``).
* No action deletes or overwrites stored data. Data-changing actions (type conversion, missing-value
  policy) write a *new derived version*; quarantine/restore only move the dataset's active-version
  pointer; the original files are always preserved.
* Data-changing actions refuse to run when they would alter more than a configured share of rows.
* An incident is resolved only after post-action verification re-runs the originally failing
  checks and they pass.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from .io import SemanticType, coerce_column

Risk = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class ActionSpec:
    action: str
    title: str
    risk: Risk
    changes_data: bool
    reversible: bool
    description: str
    expected_outcome: str
    rollback: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CATALOG: dict[str, ActionSpec] = {
    a.action: a
    for a in [
        ActionSpec("quarantine_version", "Quarantine failing version", "low", False, True,
                   "Mark the failing version as quarantined so consumers keep reading the last known good version.",
                   "Active version reverts to the last known good version; the failing version is kept for inspection.",
                   "Release the version from quarantine (sets it active again)."),
        ActionSpec("reject_version", "Reject schema-breaking update", "low", False, True,
                   "Reject a version whose schema breaks the expected contract.",
                   "Version is marked rejected and never becomes active; data is retained for audit.",
                   "Upload a corrected version, or release the rejected version explicitly."),
        ActionSpec("rerun_validation", "Re-run validation", "low", False, True,
                   "Execute all enabled quality rules again on the active version.",
                   "Fresh rule results; useful after transient errors or rule edits.", "Not applicable (read-only)."),
        ActionSpec("rerun_profiling", "Re-run profiling", "low", False, True,
                   "Recompute the profile of the version.", "Updated profile statistics.", "Not applicable (read-only)."),
        ActionSpec("retry_ingestion", "Retry ingestion", "low", False, True,
                   "Re-parse the retained raw upload of a version whose ingestion failed.",
                   "Version becomes available if the failure was transient.", "Not applicable."),
        ActionSpec("apply_type_conversion", "Apply configured type conversion", "medium", True, True,
                   "Cast a column to the type configured in the dataset's remediation policy, writing a new derived version.",
                   "New version whose column has the expected type; unconvertible values become null and are counted.",
                   "Restore the previous version; the original is untouched."),
        ActionSpec("apply_missing_value_policy", "Apply configured missing-value policy", "medium", True, True,
                   "Fill or drop missing values using the strategy configured for the column, writing a new derived version.",
                   "New version with the configured policy applied; the number of changed rows is recorded.",
                   "Restore the previous version; the original is untouched."),
        ActionSpec("restore_last_known_good", "Restore last known good version", "medium", False, True,
                   "Point the dataset back at the most recent version that passed all critical checks.",
                   "Consumers read the restored version; newer versions are retained.", "Re-activate the newer version."),
        ActionSpec("notify_operator", "Notify an operator", "low", False, True,
                   "Send an in-app (and optionally email) notification asking for manual intervention.",
                   "An operator is alerted; no data changes.", "Not applicable."),
    ]
}
AUTO_ELIGIBLE = {k for k, v in CATALOG.items() if v.risk == "low"}
MODES = ("recommend", "approval", "auto")


def validate_allowlist(actions: list[str]) -> list[str]:
    bad = [a for a in actions if a not in AUTO_ELIGIBLE]
    if bad:
        raise ValueError(f"Only low-risk actions can be auto-executed; not allowed: {', '.join(bad)}")
    return sorted(set(actions))


def execution_mode(action: str, workspace_mode: str, allowlist: list[str]) -> str:
    """Effective mode for one action. ``auto`` applies only to allowlisted low-risk actions."""
    if workspace_mode == "recommend":
        return "recommend"
    if workspace_mode == "auto" and action in allowlist and action in AUTO_ELIGIBLE:
        return "auto"
    return "approval"


def recommend(
    findings: list[dict[str, Any]],
    *,
    version_is_active: bool,
    has_last_known_good: bool,
    remediation_policy: dict[str, Any] | None = None,
    ingestion_failed: bool = False,
) -> list[dict[str, Any]]:
    """Map findings to candidate actions. Each item carries the reason and the findings it addresses."""
    policy = remediation_policy or {}
    conversions: dict[str, str] = policy.get("type_conversions", {})
    missing: dict[str, dict[str, Any]] = policy.get("missing_value_policies", {})
    kinds = {f.get("kind") for f in findings}
    recs: list[dict[str, Any]] = []

    def add(action: str, reason: str, addresses: list[dict[str, Any]], params: dict[str, Any] | None = None) -> None:
        if any(r["action"] == action and r["params"] == (params or {}) for r in recs):
            return
        recs.append({"action": action, "reason": reason, "params": params or {},
                     "addresses": [f.get("id") or f.get("kind") for f in addresses]})

    if ingestion_failed:
        add("retry_ingestion", "Ingestion failed; retrying is safe because the raw upload is retained.", findings)
        return recs
    breaking = [f for f in findings if f.get("kind") in ("column_removed", "type_changed", "schema") and f.get("severity") == "critical"]
    for f in [f for f in findings if f.get("kind") == "type_changed" and f.get("column") in conversions]:
        add("apply_type_conversion", f"A type conversion for '{f['column']}' is configured in the dataset policy.", [f],
            {"column": f["column"], "target_type": conversions[f["column"]]})
    for f in findings:
        col = f.get("column")
        if f.get("kind") in ("not_null", "missingness_increase", "null_pct_increase", "null_pct_increase_large") and col in missing:
            add("apply_missing_value_policy", f"A missing-value policy for '{col}' is configured in the dataset policy.", [f],
                {"column": col, **missing[col]})
    if breaking:
        add("reject_version", "The version breaks the schema contract (removed or retyped columns).", breaking)
    critical = [f for f in findings if f.get("severity") == "critical"]
    if critical and not breaking:
        add("quarantine_version", "Critical findings: keep consumers on the last known good version while investigating.", critical)
    if version_is_active and has_last_known_good and (critical or breaking):
        add("restore_last_known_good", "The failing version is active and an earlier version passed all critical checks.", critical)
    if "error" in kinds:
        add("rerun_validation", "Some rules errored during evaluation; a re-run distinguishes transient errors.", findings)
    add("notify_operator", "A human should review the evidence and confirm the remediation.", findings)
    return recs


# ---------------------------------------------------------------------------
# Data-changing transformations (pure; operate on copies)
# ---------------------------------------------------------------------------


class RemediationRefused(ValueError):
    """Raised when a precondition fails; the message is shown to users and logged in the audit trail."""


def type_conversion(df: pd.DataFrame, column: str, target_type: str, max_failure_pct: float = 1.0) -> tuple[pd.DataFrame, dict[str, Any]]:
    if column not in df.columns:
        raise RemediationRefused(f"Column '{column}' is not present in the version.")
    try:
        target = SemanticType(target_type)
    except ValueError as exc:
        raise RemediationRefused(f"Unknown target type '{target_type}'.") from exc
    out = df.copy()
    before_nonnull = int(out[column].notna().sum())
    converted = coerce_column(out[column], target)
    failures = int(before_nonnull - converted.notna().sum())
    pct = round(100 * failures / before_nonnull, 4) if before_nonnull else 0.0
    if pct > max_failure_pct:
        raise RemediationRefused(
            f"Conversion of '{column}' to {target.value} would null {failures} values ({pct}%), above the "
            f"{max_failure_pct}% limit. No data was changed."
        )
    out[column] = converted
    return out, {"column": column, "target_type": target.value, "values_converted": before_nonnull - failures,
                 "coercion_failures": failures, "coercion_failure_pct": pct}


def missing_value_policy(
    df: pd.DataFrame, column: str, strategy: str, value: Any = None, max_affected_pct: float = 20.0,
    semantic_type: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if column not in df.columns:
        raise RemediationRefused(f"Column '{column}' is not present in the version.")
    out = df.copy()
    nulls = out[column].isna()
    n_null = int(nulls.sum())
    pct = round(100 * n_null / len(out), 4) if len(out) else 0.0
    if pct > max_affected_pct:
        raise RemediationRefused(
            f"{n_null} rows ({pct}%) are missing '{column}', above the {max_affected_pct}% limit for automatic "
            "filling. Filling this many values would hide a real data problem; no data was changed."
        )
    numeric = semantic_type == SemanticType.NUMERIC.value or pd.api.types.is_numeric_dtype(out[column])
    if strategy in ("mean", "median") and not numeric:
        raise RemediationRefused(f"Strategy '{strategy}' needs a numeric column.")
    fill: Any
    if strategy == "drop_rows":
        out = out[~nulls].reset_index(drop=True)
        fill = None
    elif strategy == "mean":
        fill = float(pd.to_numeric(out[column], errors="coerce").mean())
    elif strategy == "median":
        fill = float(pd.to_numeric(out[column], errors="coerce").median())
    elif strategy == "mode":
        mode = out[column].mode(dropna=True)
        if mode.empty:
            raise RemediationRefused(f"'{column}' has no non-null values to take a mode from.")
        fill = mode.iloc[0]
    elif strategy == "constant":
        if value is None:
            raise RemediationRefused("Strategy 'constant' needs a value.")
        fill = value
    else:
        raise RemediationRefused(f"Unknown missing-value strategy '{strategy}'.")
    if strategy != "drop_rows":
        if pd.api.types.is_integer_dtype(out[column]) and isinstance(fill, float) and not float(fill).is_integer():
            out[column] = out[column].astype("float64")
        out[column] = out[column].fillna(fill)
    return out, {"column": column, "strategy": strategy, "rows_affected": n_null, "affected_pct": pct,
                 "fill_value": None if fill is None else (fill.item() if isinstance(fill, np.generic) else fill),
                 "rows_after": int(len(out))}
