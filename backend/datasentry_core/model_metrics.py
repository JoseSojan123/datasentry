"""Model performance metrics computed only from what the labels support.

* Metrics are computed on the subset of predictions that have ground truth; label coverage
  (labelled / total) is always reported so partial labels are visible.
* ROC-AUC is reported only for binary problems with scores and both classes present.
* Regression R² is reported only with at least two labelled points and non-constant targets.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
from sklearn import metrics as skm

MIN_LABELS = 1
BOOTSTRAP_RESAMPLES = 300
MIN_FOR_CI = 30


def bootstrap_ci(fn, *arrays: np.ndarray, n: int = BOOTSTRAP_RESAMPLES, seed: int = 0, level: float = 0.95) -> list[float] | None:
    """Percentile bootstrap confidence interval for a metric (deterministic: fixed seed)."""
    size = len(arrays[0])
    if size < MIN_FOR_CI:
        return None
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n):
        idx = rng.integers(0, size, size)
        try:
            vals.append(fn(*[a[idx] for a in arrays]))
        except ValueError:
            continue
    if not vals:
        return None
    lo, hi = np.percentile(vals, [(1 - level) / 2 * 100, (1 + level) / 2 * 100])
    return [float(lo), float(hi)]


def _labelled(y_true: list[Any], *others: list[Any]) -> tuple[list[int], list[Any]]:
    idx = [i for i, v in enumerate(y_true) if v is not None and not (isinstance(v, float) and np.isnan(v))]
    return idx, [y_true[i] for i in idx]


def classification_metrics(
    y_true: list[Any], y_pred: list[Any], y_score: list[float | None] | None = None, positive_label: Any = None
) -> dict[str, Any]:
    total = len(y_pred)
    idx, yt = _labelled(y_true)
    out: dict[str, Any] = {
        "task": "classification",
        "n_predictions": total,
        "n_labelled": len(idx),
        "label_coverage": round(len(idx) / total, 6) if total else 0.0,
    }
    if len(idx) < MIN_LABELS:
        out["status"] = "no_labels"
        out["note"] = "No ground-truth labels yet; performance cannot be computed."
        return out
    yp = [y_pred[i] for i in idx]
    yt_s = [str(v) for v in yt]
    yp_s = [str(v) for v in yp]
    labels = sorted(set(yt_s) | set(yp_s))
    binary = len(labels) <= 2
    pos = str(positive_label) if positive_label is not None else (labels[-1] if labels else None)
    avg: Literal["binary", "macro"] = "binary" if binary and pos in labels else "macro"
    kw = {"pos_label": pos} if avg == "binary" else {}
    out.update(
        status="ok",
        accuracy=float(skm.accuracy_score(yt_s, yp_s)),
        precision=float(skm.precision_score(yt_s, yp_s, average=avg, zero_division=0, **kw)),
        recall=float(skm.recall_score(yt_s, yp_s, average=avg, zero_division=0, **kw)),
        f1=float(skm.f1_score(yt_s, yp_s, average=avg, zero_division=0, **kw)),
        averaging=avg,
        positive_label=pos if avg == "binary" else None,
        labels=labels,
        confusion_matrix=skm.confusion_matrix(yt_s, yp_s, labels=labels).tolist(),
    )
    yt_a, yp_a = np.array(yt_s), np.array(yp_s)
    out["f1_ci95"] = bootstrap_ci(lambda a, b: skm.f1_score(a, b, average=avg, zero_division=0, **kw), yt_a, yp_a)
    roc_note = None
    if y_score is not None and binary and len(set(yt_s)) == 2:
        sc = [y_score[i] for i in idx]
        if all(s is not None for s in sc):
            out["roc_auc"] = float(skm.roc_auc_score([1 if v == pos else 0 for v in yt_s], sc))
        else:
            roc_note = "ROC-AUC skipped: some labelled predictions have no score."
    elif y_score is None:
        roc_note = "ROC-AUC skipped: no prediction scores were logged."
    else:
        roc_note = "ROC-AUC skipped: needs a binary problem with both classes present among labels."
    if roc_note:
        out["roc_auc"] = None
        out["roc_auc_note"] = roc_note
    return out


def regression_metrics(y_true: list[Any], y_pred: list[Any]) -> dict[str, Any]:
    total = len(y_pred)
    idx, yt = _labelled(y_true)
    out: dict[str, Any] = {
        "task": "regression",
        "n_predictions": total,
        "n_labelled": len(idx),
        "label_coverage": round(len(idx) / total, 6) if total else 0.0,
    }
    if not idx:
        out["status"] = "no_labels"
        out["note"] = "No ground-truth labels yet; performance cannot be computed."
        return out
    t = np.asarray(yt, dtype=float)
    p = np.asarray([y_pred[i] for i in idx], dtype=float)
    resid = t - p
    out.update(
        status="ok",
        mae=float(np.mean(np.abs(resid))),
        rmse=float(np.sqrt(np.mean(resid**2))),
        mean_residual=float(resid.mean()),
        residual_quantiles={q: float(np.quantile(resid, q / 100)) for q in (5, 25, 50, 75, 95)},
    )
    out["rmse_ci95"] = bootstrap_ci(lambda a, b: float(np.sqrt(np.mean((a - b) ** 2))), t, p)
    if len(idx) >= 2 and np.ptp(t) > 0:
        out["r2"] = float(skm.r2_score(t, p))
    else:
        out["r2"] = None
        out["r2_note"] = "R² needs at least two labelled points with non-constant targets."
    hist, edges = np.histogram(resid, bins=min(20, max(1, len(resid))))
    out["residual_histogram"] = {"edges": edges.tolist(), "counts": hist.tolist()}
    return out


def compare_performance(baseline: dict[str, Any], current: dict[str, Any], tolerance: float = 0.05) -> dict[str, Any]:
    """Flag degradation of the primary metric relative to the registered baseline.

    Primary metric: F1 for classification, RMSE for regression. ``tolerance`` is relative
    (0.05 = 5% worse triggers a warning, 2x tolerance a critical finding). To avoid alerting on
    sampling noise, a degradation is reported only when the whole 95% bootstrap interval of the
    current metric is beyond the threshold; a worse point estimate whose interval still includes an
    acceptable value is reported as ``inconclusive``.
    """
    if current.get("status") != "ok":
        return {"status": "unknown", "note": "Not enough labelled predictions to assess performance."}
    task = current["task"]
    metric = "f1" if task == "classification" else "rmse"
    base = baseline.get(metric)
    cur = current.get(metric)
    if base is None or cur is None:
        return {"status": "unknown", "metric": metric, "note": f"Baseline {metric} not registered."}
    higher_better = metric != "rmse"
    ci = current.get(f"{metric}_ci95")

    def rel_worse(v: float) -> float:
        if not base:
            return 0.0
        return (base - v) / abs(base) if higher_better else (v - base) / abs(base)

    rel = rel_worse(cur)
    # The most favourable end of the interval decides whether the degradation is established.
    best = (ci[1] if higher_better else ci[0]) if ci else None
    rel_best = rel_worse(best) if best is not None else None
    if rel_best is None:
        sev, status = "none", "inconclusive" if rel >= tolerance else "ok"
    elif rel_best >= 2 * tolerance:
        sev, status = "critical", "degraded"
    elif rel_best >= tolerance:
        sev, status = "warning", "degraded"
    else:
        sev, status = "none", "inconclusive" if rel >= tolerance else "ok"
    expl = (f"{metric.upper()} moved from {base:.4g} (baseline) to {cur:.4g} on {current.get('n_labelled')} labelled predictions "
            f"({rel:+.1%} worse; warning at {tolerance:.0%})")
    if ci:
        expl += f"; 95% bootstrap interval [{ci[0]:.4g}, {ci[1]:.4g}]"
    expl += "." if status != "inconclusive" else "; the interval still includes acceptable values, so this is not yet conclusive."
    return {"status": status, "severity": sev, "metric": metric, "baseline": base, "current": cur, "ci95": ci,
            "relative_degradation": round(rel, 6), "tolerance": tolerance, "n_labelled": current.get("n_labelled"),
            "explanation": expl}
