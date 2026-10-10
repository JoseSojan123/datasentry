"""Statistical drift detection between a reference and a current sample.

Design principles (see docs/methodology.md for the full discussion):

* **Practical importance comes from effect sizes** (PSI for numeric features, Jensen–Shannon
  distance for categorical features). **Statistical significance comes from hypothesis tests**
  (two-sample Kolmogorov–Smirnov, chi-square test of homogeneity) after multiple-testing
  correction across all features in one evaluation (Benjamini–Hochberg by default).
* A feature is reported as ``drift`` only when the effect size crosses the configured warning
  threshold **and** the corrected test is significant. A large effect that is not significant is
  ``inconclusive`` (typically small samples); a significant but tiny effect is ``no_drift`` with
  an informational note, because with large samples trivial differences become significant.
* PSI uses quantile bins from the reference sample with additive (Laplace-style) smoothing so that
  empty bins never produce infinite values.
* Default thresholds (PSI 0.1/0.25, JS distance 0.1/0.2) are conventional rules of thumb, not
  universal truths. They are configurable per evaluation and are recorded with every result.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy import stats
from scipy.spatial.distance import jensenshannon

from .io import SemanticType
from .profiling import numeric_values

Severity = Literal["none", "info", "warning", "critical"]
SEVERITY_ORDER = {"none": 0, "info": 1, "warning": 2, "critical": 3}


@dataclass
class DriftConfig:
    psi_bins: int = 10
    psi_warning: float = 0.1
    psi_critical: float = 0.25
    js_warning: float = 0.1
    js_critical: float = 0.2
    alpha: float = 0.05
    correction: Literal["benjamini_hochberg", "bonferroni", "none"] = "benjamini_hochberg"
    min_samples: int = 30
    smoothing: float = 0.5
    missing_warning_pp: float = 5.0
    missing_critical_pp: float = 20.0
    cardinality_change_ratio: float = 0.5
    features: list[str] | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> DriftConfig:
        d = d or {}
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        cfg = cls(**known)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if not (2 <= self.psi_bins <= 50):
            raise ValueError("psi_bins must be between 2 and 50")
        if not (0 < self.psi_warning <= self.psi_critical):
            raise ValueError("require 0 < psi_warning <= psi_critical")
        if not (0 < self.js_warning <= self.js_critical <= 1):
            raise ValueError("require 0 < js_warning <= js_critical <= 1")
        if not (0 < self.alpha < 1):
            raise ValueError("alpha must be in (0, 1)")
        if self.min_samples < 5:
            raise ValueError("min_samples must be >= 5")
        if self.smoothing <= 0:
            raise ValueError("smoothing must be > 0")


@dataclass
class FeatureDrift:
    feature: str
    semantic_type: str
    method: str
    n_reference: int
    n_current: int
    status: Literal["no_drift", "drift", "inconclusive", "insufficient_data", "skipped"]
    severity: Severity
    statistics: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    explanation: str = ""
    significant: bool | None = None
    practically_important: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Effect sizes
# ---------------------------------------------------------------------------


def quantile_edges(reference: np.ndarray, bins: int) -> np.ndarray:
    """Interior bin edges from reference quantiles, de-duplicated (handles ties/constant data)."""
    qs = np.linspace(0, 1, bins + 1)[1:-1]
    edges = np.unique(np.quantile(reference, qs))
    return edges


def psi_from_counts(ref_counts: np.ndarray, cur_counts: np.ndarray, smoothing: float = 0.5) -> float:
    ref = (ref_counts + smoothing) / (ref_counts.sum() + smoothing * len(ref_counts))
    cur = (cur_counts + smoothing) / (cur_counts.sum() + smoothing * len(cur_counts))
    return float(np.sum((cur - ref) * np.log(cur / ref)))


def psi_numeric(reference: np.ndarray, current: np.ndarray, bins: int = 10, smoothing: float = 0.5) -> tuple[float, dict[str, Any]]:
    interior = quantile_edges(reference, bins)
    ref_idx = np.searchsorted(interior, reference, side="right")
    cur_idx = np.searchsorted(interior, current, side="right")
    k = len(interior) + 1
    ref_counts = np.bincount(ref_idx, minlength=k).astype(float)
    cur_counts = np.bincount(cur_idx, minlength=k).astype(float)
    psi = psi_from_counts(ref_counts, cur_counts, smoothing)
    return psi, {
        "interior_edges": [float(e) for e in interior],
        "reference_counts": ref_counts.astype(int).tolist(),
        "current_counts": cur_counts.astype(int).tolist(),
    }


def js_distance(p_counts: np.ndarray, q_counts: np.ndarray, smoothing: float = 0.5) -> float:
    p = (p_counts + smoothing) / (p_counts.sum() + smoothing * len(p_counts))
    q = (q_counts + smoothing) / (q_counts.sum() + smoothing * len(q_counts))
    return float(jensenshannon(p, q, base=2))


def classify(value: float, warning: float, critical: float) -> Severity:
    if value >= critical:
        return "critical"
    if value >= warning:
        return "warning"
    return "none"


# ---------------------------------------------------------------------------
# Tests and correction
# ---------------------------------------------------------------------------


def adjust_pvalues(pvalues: list[float | None], method: str) -> list[float | None]:
    idx = [i for i, p in enumerate(pvalues) if p is not None]
    m = len(idx)
    out: list[float | None] = [None] * len(pvalues)
    if m == 0:
        return out
    ps = np.array([pvalues[i] for i in idx], dtype=float)
    if method == "none":
        adj = ps
    elif method == "bonferroni":
        adj = np.minimum(ps * m, 1.0)
    else:  # Benjamini–Hochberg step-up
        order = np.argsort(ps)
        ranked = ps[order] * m / np.arange(1, m + 1)
        ranked = np.minimum.accumulate(ranked[::-1])[::-1]
        adj = np.empty(m)
        adj[order] = np.minimum(ranked, 1.0)
    for j, i in enumerate(idx):
        out[i] = float(adj[j])
    return out


def chi_square_homogeneity(ref_counts: Mapping[Any, int], cur_counts: Mapping[Any, int]) -> dict[str, Any]:
    """Chi-square test of homogeneity with Cochran's rule.

    Categories whose expected count is below 5 in either sample are pooled into ``__other__``; if
    that pooled bucket is itself too small its rows are excluded from the test. The test is reported only if, after pooling, there are >= 2 categories, every expected count
    is >= 1 and at least 80% are >= 5.
    """
    cats = sorted(set(ref_counts) | set(cur_counts))
    table = np.array([[ref_counts.get(c, 0) for c in cats], [cur_counts.get(c, 0) for c in cats]], dtype=float)
    pooled_cats: list[str] = []
    if table.sum() == 0 or table.shape[1] < 2:
        return {"valid": False, "reason": "fewer than two categories"}
    row = table.sum(axis=1, keepdims=True)
    col = table.sum(axis=0, keepdims=True)
    expected = row * col / table.sum()
    small = (expected < 5).any(axis=0)
    if small.any():
        pooled_cats = [c for c, s in zip(cats, small, strict=True) if s]
        keep = table[:, ~small]
        other = table[:, small].sum(axis=1, keepdims=True)
        if keep.shape[1] >= 1 and other.sum() > 0:
            pooled_expected = other.sum() * row / table.sum()
            # Keep the pooled bucket only if it is itself large enough; otherwise exclude those rows.
            table = np.hstack([keep, other]) if np.all(pooled_expected >= 5) else keep
        else:
            table = keep
    if table.shape[1] < 2:
        return {"valid": False, "reason": "fewer than two categories after pooling rare ones", "pooled": pooled_cats}
    row = table.sum(axis=1, keepdims=True)
    col = table.sum(axis=0, keepdims=True)
    expected = row * col / table.sum()
    if (expected < 1).any() or (expected >= 5).mean() < 0.8:
        return {"valid": False, "reason": "expected counts too small (Cochran's rule)", "pooled": pooled_cats}
    chi2, p, dof, _ = stats.chi2_contingency(table, correction=False)
    return {"valid": True, "chi2": float(chi2), "p_value": float(p), "dof": int(dof), "pooled": pooled_cats}


def two_proportion_z(x1: int, n1: int, x2: int, n2: int) -> float | None:
    if n1 == 0 or n2 == 0:
        return None
    p = (x1 + x2) / (n1 + n2)
    if p in (0, 1):
        return 1.0
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    z = (x2 / n2 - x1 / n1) / se
    return float(2 * stats.norm.sf(abs(z)))


# ---------------------------------------------------------------------------
# Feature evaluation
# ---------------------------------------------------------------------------


def _numeric_feature(name: str, ref_s: pd.Series, cur_s: pd.Series, cfg: DriftConfig) -> tuple[FeatureDrift, float | None]:
    ref = numeric_values(ref_s)
    cur = numeric_values(cur_s)
    fd = FeatureDrift(name, SemanticType.NUMERIC.value, "psi+ks", ref.size, cur.size, "skipped", "none")
    if ref.size < cfg.min_samples or cur.size < cfg.min_samples:
        fd.status = "insufficient_data"
        fd.explanation = (
            f"Not evaluated: {ref.size} reference and {cur.size} current non-null values; "
            f"at least {cfg.min_samples} are required on each side."
        )
        return fd, None
    psi, bins = psi_numeric(ref, cur, cfg.psi_bins, cfg.smoothing)
    if np.ptp(ref) == 0 and np.ptp(cur) == 0:
        ks_stat, ks_p = (0.0, 1.0) if ref[0] == cur[0] else (1.0, 0.0)
    else:
        ks = stats.ks_2samp(ref, cur, method="auto")
        ks_stat, ks_p = float(ks.statistic), float(ks.pvalue)
    ref_std = float(ref.std(ddof=1)) if ref.size > 1 else 0.0
    smd = (float(cur.mean()) - float(ref.mean())) / ref_std if ref_std > 0 else None
    lo = float(min(ref.min(), cur.min()))
    hi = float(max(ref.max(), cur.max()))
    if lo == hi:
        lo, hi = lo - 0.5, hi + 0.5
    edges = np.linspace(lo, hi, 21)
    fd.statistics = {
        "psi": round(psi, 6),
        "ks_statistic": round(ks_stat, 6),
        "ks_p_value": ks_p,
        "mean_reference": float(ref.mean()),
        "mean_current": float(cur.mean()),
        "std_reference": ref_std,
        "std_current": float(cur.std(ddof=1)) if cur.size > 1 else 0.0,
        "standardized_mean_difference": None if smd is None else round(smd, 6),
        "median_reference": float(np.median(ref)),
        "median_current": float(np.median(cur)),
    }
    fd.evidence = {
        "psi_bins": bins,
        "histogram": {
            "edges": [float(e) for e in edges],
            "reference": np.histogram(ref, edges)[0].tolist(),
            "current": np.histogram(cur, edges)[0].tolist(),
        },
    }
    fd.severity = classify(psi, cfg.psi_warning, cfg.psi_critical)
    fd.practically_important = fd.severity != "none"
    return fd, ks_p


def _categorical_feature(
    name: str, semantic: str, ref_s: pd.Series, cur_s: pd.Series, cfg: DriftConfig
) -> tuple[FeatureDrift, float | None]:
    ref = ref_s.dropna().astype(str)
    cur = cur_s.dropna().astype(str)
    fd = FeatureDrift(name, semantic, "js+chi2", len(ref), len(cur), "skipped", "none")
    if len(ref) < cfg.min_samples or len(cur) < cfg.min_samples:
        fd.status = "insufficient_data"
        fd.explanation = (
            f"Not evaluated: {len(ref)} reference and {len(cur)} current non-null values; "
            f"at least {cfg.min_samples} are required on each side."
        )
        return fd, None
    rc: dict[Any, int] = ref.value_counts().to_dict()
    cc: dict[Any, int] = cur.value_counts().to_dict()
    cats = sorted(set(rc) | set(cc), key=lambda c: -(rc.get(c, 0) + cc.get(c, 0)))
    rv = np.array([rc.get(c, 0) for c in cats], dtype=float)
    cv = np.array([cc.get(c, 0) for c in cats], dtype=float)
    js = js_distance(rv, cv, cfg.smoothing)
    psi = psi_from_counts(rv, cv, cfg.smoothing)
    chi = chi_square_homogeneity(rc, cc)
    new_cats = sorted(set(cc) - set(rc), key=str)
    gone = sorted(set(rc) - set(cc), key=str)
    fd.statistics = {
        "js_distance": round(js, 6),
        "psi": round(psi, 6),
        "chi2": chi.get("chi2"),
        "chi2_p_value": chi.get("p_value"),
        "chi2_dof": chi.get("dof"),
        "chi2_valid": chi["valid"],
        "chi2_note": chi.get("reason"),
        "categories_reference": len(rc),
        "categories_current": len(cc),
        "new_categories": new_cats[:50],
        "missing_categories": gone[:50],
        "new_category_share": round(float(cur.isin(new_cats).mean()), 6) if new_cats else 0.0,
    }
    top = cats[:25]
    fd.evidence = {
        "categories": [
            {
                "value": c,
                "reference": int(rc.get(c, 0)),
                "current": int(cc.get(c, 0)),
                "reference_pct": round(100 * rc.get(c, 0) / len(ref), 4),
                "current_pct": round(100 * cc.get(c, 0) / len(cur), 4),
            }
            for c in top
        ],
        "truncated": len(cats) > 25,
    }
    fd.severity = classify(js, cfg.js_warning, cfg.js_critical)
    fd.practically_important = fd.severity != "none"
    return fd, chi.get("p_value") if chi["valid"] else None


def _finalize(fd: FeatureDrift, p_adj: float | None, cfg: DriftConfig) -> None:
    effect_name = "PSI" if fd.method == "psi+ks" else "JS distance"
    effect = fd.statistics.get("psi") if fd.method == "psi+ks" else fd.statistics.get("js_distance")
    warn = cfg.psi_warning if fd.method == "psi+ks" else cfg.js_warning
    fd.statistics["p_value_adjusted"] = p_adj
    fd.statistics["correction"] = cfg.correction
    test = "KS" if fd.method == "psi+ks" else "chi-square"
    sizes = f"(n_ref={fd.n_reference:,}, n_cur={fd.n_current:,})"
    if p_adj is None:
        fd.significant = None
        if fd.practically_important:
            fd.status = "drift" if fd.severity == "critical" else "inconclusive"
            fd.explanation = (
                f"{effect_name} = {effect:.3f} (≥ {warn}) {sizes}; the {test} test was not applicable "
                f"({fd.statistics.get('chi2_note', 'n/a')}), so the result rests on effect size alone."
            )
        else:
            fd.status = "no_drift"
            fd.explanation = f"{effect_name} = {effect:.3f} is below the warning threshold {warn} {sizes}."
    else:
        fd.significant = p_adj < cfg.alpha
        if fd.practically_important and fd.significant:
            fd.status = "drift"
            fd.explanation = (
                f"Distribution shifted: {effect_name} = {effect:.3f} (warning ≥ {warn}) and the {test} test is "
                f"significant after {cfg.correction.replace('_', '-')} correction (p_adj = {p_adj:.2g} < {cfg.alpha}) {sizes}."
            )
        elif fd.practically_important:
            fd.status = "inconclusive"
            fd.severity = "info"
            fd.explanation = (
                f"{effect_name} = {effect:.3f} exceeds {warn}, but the {test} test is not significant "
                f"(p_adj = {p_adj:.2g}); likely sampling noise from small samples {sizes}."
            )
        else:
            fd.status = "no_drift"
            fd.severity = "info" if fd.significant else "none"
            fd.explanation = (
                f"{effect_name} = {effect:.3f} is below the warning threshold {warn} {sizes}"
                + (f"; the {test} test is significant (p_adj = {p_adj:.2g}) but the difference is practically small."
                   if fd.significant else ".")
            )
    if fd.method == "psi+ks" and fd.status == "drift":
        smd = fd.statistics.get("standardized_mean_difference")
        if smd is not None:
            fd.explanation += (
                f" Mean moved from {fd.statistics['mean_reference']:.4g} to {fd.statistics['mean_current']:.4g} "
                f"({smd:+.2f} reference standard deviations)."
            )
    if fd.method == "js+chi2" and fd.statistics.get("new_categories"):
        fd.explanation += (
            f" New categories in current data: {', '.join(fd.statistics['new_categories'][:5])} "
            f"({100 * fd.statistics['new_category_share']:.1f}% of rows)."
        )


def missingness_change(name: str, ref_s: pd.Series, cur_s: pd.Series, cfg: DriftConfig) -> dict[str, Any] | None:
    n1, n2 = len(ref_s), len(cur_s)
    if not n1 or not n2:
        return None
    m1, m2 = int(ref_s.isna().sum()), int(cur_s.isna().sum())
    r1, r2 = 100 * m1 / n1, 100 * m2 / n2
    delta = r2 - r1
    sev: Severity = "none"
    if delta >= cfg.missing_critical_pp:
        sev = "critical"
    elif delta >= cfg.missing_warning_pp:
        sev = "warning"
    if sev == "none":
        return None
    p = two_proportion_z(m1, n1, m2, n2)
    return {
        "feature": name,
        "kind": "missingness_increase",
        "severity": sev,
        "reference_missing_pct": round(r1, 4),
        "current_missing_pct": round(r2, 4),
        "delta_pp": round(delta, 4),
        "p_value": p,
        "explanation": f"Missing values in '{name}' rose from {r1:.1f}% to {r2:.1f}% (+{delta:.1f} pp; "
        f"warning at +{cfg.missing_warning_pp} pp, critical at +{cfg.missing_critical_pp} pp; two-proportion z-test p = {p:.2g}).",
    }


def cardinality_change(name: str, ref_s: pd.Series, cur_s: pd.Series, cfg: DriftConfig) -> dict[str, Any] | None:
    a, b = ref_s.nunique(), cur_s.nunique()
    if a == 0:
        return None
    ratio = (b - a) / a
    if abs(ratio) < cfg.cardinality_change_ratio:
        return None
    return {
        "feature": name,
        "kind": "cardinality_change",
        "severity": "warning",
        "reference_distinct": int(a),
        "current_distinct": int(b),
        "relative_change": round(ratio, 4),
        "explanation": f"Distinct values in '{name}' changed from {a} to {b} ({ratio:+.0%}); threshold ±{cfg.cardinality_change_ratio:.0%}.",
    }


def slice_window(df: pd.DataFrame, column: str | None, start: Any = None, end: Any = None) -> pd.DataFrame:
    """Restrict a frame to a time window [start, end) on ``column``."""
    if not column or (start is None and end is None):
        return df
    if column not in df.columns:
        raise ValueError(f"window column '{column}' not found")
    ts = pd.to_datetime(df[column], errors="coerce")

    def naive(v: Any) -> pd.Timestamp:
        t = pd.Timestamp(v)
        return t.tz_convert("UTC").tz_localize(None) if t.tzinfo else t

    mask = pd.Series(True, index=df.index)
    if start is not None:
        mask &= ts >= naive(start)
    if end is not None:
        mask &= ts < naive(end)
    return df[mask]


def evaluate_drift(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    reference_types: dict[str, str],
    current_types: dict[str, str] | None = None,
    config: DriftConfig | None = None,
) -> dict[str, Any]:
    """Compare two samples feature by feature. Deterministic for fixed inputs."""
    cfg = config or DriftConfig()
    cfg.validate()
    current_types = current_types or reference_types
    started = time.perf_counter()
    shared = [c for c in reference.columns if c in current.columns]
    if cfg.features:
        shared = [c for c in shared if c in cfg.features]
    features: list[FeatureDrift] = []
    pvals: list[float | None] = []
    skipped_types: list[dict[str, str]] = []
    for col in shared:
        rt, ct = reference_types.get(col), current_types.get(col)
        if rt != ct:
            skipped_types.append({"feature": col, "reference_type": str(rt), "current_type": str(ct)})
            continue
        if rt == SemanticType.NUMERIC.value:
            fd, p = _numeric_feature(col, reference[col], current[col], cfg)
        elif rt in (SemanticType.CATEGORICAL.value, SemanticType.BOOLEAN.value):
            fd, p = _categorical_feature(col, rt, reference[col], current[col], cfg)
        else:
            continue  # text and datetime columns are covered by schema/freshness checks
        features.append(fd)
        pvals.append(p if fd.status != "insufficient_data" else None)
    adjusted = adjust_pvalues(pvals, cfg.correction)
    for fd, p_adj in zip(features, adjusted, strict=True):
        if fd.status != "insufficient_data":
            _finalize(fd, p_adj, cfg)
    other: list[dict[str, Any]] = []
    for col in shared:
        m = missingness_change(col, reference[col], current[col], cfg)
        if m:
            other.append(m)
        if reference_types.get(col) == current_types.get(col) == SemanticType.CATEGORICAL.value:
            c = cardinality_change(col, reference[col], current[col], cfg)
            if c:
                other.append(c)
    for t in skipped_types:
        other.append({**t, "kind": "type_change", "severity": "critical",
                      "explanation": f"'{t['feature']}' changed type from {t['reference_type']} to {t['current_type']}; "
                                     "distribution comparison is not meaningful."})
    added = [c for c in current.columns if c not in reference.columns]
    removed = [c for c in reference.columns if c not in current.columns]
    for col in removed:
        other.append({"feature": col, "kind": "column_removed", "severity": "critical",
                      "explanation": f"Column '{col}' exists in the reference but not in the current data."})
    for col in added:
        other.append({"feature": col, "kind": "column_added", "severity": "info",
                      "explanation": f"Column '{col}' is new in the current data."})
    drifted = [f for f in features if f.status == "drift"]
    severities = [f.severity for f in drifted] + [o["severity"] for o in other]
    overall: Severity = max(severities, key=lambda s: SEVERITY_ORDER[s], default="none")  # type: ignore[arg-type]
    evaluated = [f for f in features if f.status not in ("insufficient_data", "skipped")]
    return {
        "summary": {
            "features_compared": len(features),
            "features_evaluated": len(evaluated),
            "features_drifted": len(drifted),
            "drift_share": round(len(drifted) / len(evaluated), 4) if evaluated else 0.0,
            "features_inconclusive": sum(f.status == "inconclusive" for f in features),
            "features_insufficient": sum(f.status == "insufficient_data" for f in features),
            "other_findings": len(other),
            "overall_severity": overall,
            "n_reference": len(reference),
            "n_current": len(current),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        },
        "config": asdict(cfg),
        "features": [f.to_dict() for f in features],
        "other_findings": other,
    }
