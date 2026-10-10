"""Model registry, prediction logging (privacy-aware), delayed labels and evaluation.

Feature logging levels per model version:
  * ``none``      – no feature data retained; only predictions/labels (no input-drift monitoring).
  * ``aggregate`` – (default) raw features are discarded after updating per-batch histograms on the
                    reference bins, which is enough for PSI/JS/chi-square input-drift monitoring.
  * ``full``      – raw features stored on each prediction record (subject to retention).

Input drift, prediction drift and performance are reported separately: drift never implies that
accuracy has dropped; only labelled predictions can show that.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.errors import bad_request, conflict
from app.db import models as m
from app.services import audit, incidents, notifications
from app.services import datasets as dsvc
from app.services import lineage as lsvc
from datasentry_core import impact as imp
from datasentry_core.drift import (
    DriftConfig,
    adjust_pvalues,
    chi_square_homogeneity,
    classify,
    evaluate_drift,
    js_distance,
    psi_from_counts,
    quantile_edges,
)
from datasentry_core.model_metrics import classification_metrics, compare_performance, regression_metrics
from datasentry_core.rules import numpy_safe

MAX_CATEGORIES = 100


def register_model(db: Session, workspace_id: int, principal: Any, **fields: Any) -> m.MLModel:
    if db.scalar(select(m.MLModel.id).where(m.MLModel.workspace_id == workspace_id, m.MLModel.name == fields["name"])):
        raise conflict(f"A model named '{fields['name']}' already exists.")
    ref_id = fields.get("reference_dataset_id")
    if ref_id is not None:
        ds = db.get(m.Dataset, ref_id)
        if ds is None or ds.workspace_id != workspace_id:
            raise bad_request("reference_dataset_id does not refer to a dataset in this workspace.")
    model = m.MLModel(workspace_id=workspace_id, **fields)
    db.add(model)
    db.flush()
    node = m.LineageNode(workspace_id=workspace_id, node_type="model", name=model.name, model_id=model.id,
                         criticality=model.criticality, owner=model.owner, meta={"auto_created": True, "task": model.task})
    db.add(node)
    db.flush()
    if ref_id is not None:
        dnode = lsvc.node_for_dataset(db, ref_id)
        if dnode:
            lsvc.ensure_edge(db, workspace_id, dnode.id, node.id, "trains", "confirmed",
                             {"observed": "model registered with this reference dataset"})
    audit.record(db, workspace_id, "model.registered", "model", model.id, {"name": model.name, "task": model.task}, principal)
    return model


def reference_profile(db: Session, model: m.MLModel, input_schema: list[dict[str, Any]], bins: int = 10) -> dict[str, Any]:
    if not model.reference_dataset_id:
        return {}
    ds = db.get(m.Dataset, model.reference_dataset_id)
    if not ds or not ds.current_version_id:
        return {}
    ver = db.get(m.DatasetVersion, ds.current_version_id)
    df = dsvc.load_frame(db, ver)
    prof: dict[str, Any] = {"source": {"dataset_id": ds.id, "version_id": ver.id, "version": ver.version_number}, "features": {}}
    for feat in input_schema:
        name, kind = feat["name"], feat.get("type", "numeric")
        if name not in df.columns:
            continue
        s = df[name]
        entry: dict[str, Any] = {"type": kind, "n": int(len(s)), "missing": int(s.isna().sum())}
        if kind == "numeric":
            vals = pd.to_numeric(s, errors="coerce").dropna().to_numpy(dtype=float)
            edges = quantile_edges(vals, bins) if vals.size else np.array([])
            entry["edges"] = [float(e) for e in edges]
            entry["counts"] = np.bincount(np.searchsorted(edges, vals, side="right"), minlength=len(edges) + 1).tolist()
            entry["mean"] = float(vals.mean()) if vals.size else None
        else:
            vc = s.dropna().astype(str).value_counts().head(MAX_CATEGORIES)
            entry["counts"] = {str(k): int(v) for k, v in vc.items()}
        prof["features"][name] = entry
    return prof


def create_version(db: Session, model: m.MLModel, principal: Any, **fields: Any) -> m.ModelVersion:
    if db.scalar(select(m.ModelVersion.id).where(m.ModelVersion.model_id == model.id, m.ModelVersion.version == fields["version"])):
        raise conflict(f"Version '{fields['version']}' already exists for this model.")
    mv = m.ModelVersion(model_id=model.id, **fields)
    mv.reference_profile = numpy_safe(reference_profile(db, model, mv.input_schema or []))
    db.add(mv)
    db.flush()
    audit.record(db, model.workspace_id, "model.version_created", "model_version", mv.id,
                 {"model_id": model.id, "version": mv.version, "feature_logging": mv.feature_logging}, principal)
    return mv


def _violations(features: dict[str, Any] | None, schema: list[dict[str, Any]]) -> list[str]:
    out = []
    features = features or {}
    for f in schema:
        name = f["name"]
        if name not in features:
            out.append(f"missing:{name}")
            continue
        v = features[name]
        if v is None:
            if not f.get("nullable", True):
                out.append(f"null:{name}")
            continue
        if f.get("type", "numeric") == "numeric" and not isinstance(v, int | float):
            out.append(f"type:{name}")
    known = {f["name"] for f in schema}
    out.extend(f"unexpected:{k}" for k in features if known and k not in known)
    return out


def log_predictions(db: Session, mv: m.ModelVersion, records: list[dict[str, Any]], principal: Any) -> dict[str, Any]:
    schema = mv.input_schema or []
    rows = []
    for r in records:
        pred = r["prediction"]
        try:
            pval = float(pred) if not isinstance(pred, bool) else float(pred)
        except (TypeError, ValueError):
            pval = None
        viol = _violations(r.get("features"), schema) if schema else []
        rows.append({
            "model_version_id": mv.id, "record_id": str(r["record_id"])[:128],
            "predicted_at": r.get("timestamp") or datetime.now(UTC),
            "features": r.get("features") if mv.feature_logging == "full" else None,
            "prediction": str(pred)[:64], "prediction_value": pval, "score": r.get("score"),
            "label": None if r.get("label") is None else str(r["label"])[:64],
            "labeled_at": datetime.now(UTC) if r.get("label") is not None else None,
            "schema_violations": viol or None,
        })
    if not rows:
        return {"accepted": 0, "duplicates": 0}
    stmt = pg_insert(m.PredictionRecord).values(rows).on_conflict_do_nothing(
        index_elements=["model_version_id", "record_id"]).returning(m.PredictionRecord.record_id)
    inserted = {r[0] for r in db.execute(stmt)}
    accepted = [r for r, row in zip(records, rows, strict=True) if row["record_id"] in inserted]
    if accepted and mv.feature_logging != "none" and mv.reference_profile.get("features"):
        _aggregate(db, mv, accepted)
    violations = sum(1 for row in rows if row["schema_violations"] and row["record_id"] in inserted)
    db.flush()
    return {"accepted": len(inserted), "duplicates": len(rows) - len(inserted), "schema_violations": violations}


def _aggregate(db: Session, mv: m.ModelVersion, records: list[dict[str, Any]]) -> None:
    stats: dict[str, Any] = {}
    for name, ref in mv.reference_profile["features"].items():
        vals = [(r.get("features") or {}).get(name) for r in records]
        missing = sum(v is None for v in vals)
        present = [v for v in vals if v is not None]
        if ref["type"] == "numeric":
            nums = np.array([v for v in present if isinstance(v, int | float)], dtype=float)
            edges = np.array(ref["edges"], dtype=float)
            counts = np.bincount(np.searchsorted(edges, nums, side="right"), minlength=len(edges) + 1).tolist() if nums.size else [0] * (len(edges) + 1)
            stats[name] = {"counts": counts, "missing": missing, "n": len(vals), "sum": float(nums.sum()) if nums.size else 0.0}
        else:
            vc = pd.Series([str(v) for v in present]).value_counts().head(MAX_CATEGORIES)
            stats[name] = {"counts": {str(k): int(v) for k, v in vc.items()}, "missing": missing, "n": len(vals)}
    ts = [pd.Timestamp(r.get("timestamp") or datetime.now(UTC)) for r in records]
    ts = [t.tz_localize("UTC") if t.tzinfo is None else t for t in ts]
    db.add(m.PredictionBatch(model_version_id=mv.id, window_start=min(ts).to_pydatetime(), window_end=max(ts).to_pydatetime(),
                             n_predictions=len(records), feature_stats=stats))


def log_labels(db: Session, mv: m.ModelVersion, labels: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [str(x["record_id"]) for x in labels]
    found = {r.record_id: r for r in db.scalars(select(m.PredictionRecord).where(
        m.PredictionRecord.model_version_id == mv.id, m.PredictionRecord.record_id.in_(ids)))}
    now = datetime.now(UTC)
    updated = 0
    for x in labels:
        rec = found.get(str(x["record_id"]))
        if rec is not None:
            rec.label = None if x.get("label") is None else str(x["label"])[:64]
            rec.labeled_at = x.get("labeled_at") or now
            updated += 1
    db.flush()
    return {"updated": updated, "unknown_record_ids": [i for i in ids if i not in found][:50]}


def _bin_labels(edges: list[float]) -> list[str]:
    if not edges:
        return ["all"]
    e = [f"{x:.4g}" for x in edges]
    return [f"< {e[0]}"] + [f"{a} – {b}" for a, b in zip(e[:-1], e[1:], strict=True)] + [f"≥ {e[-1]}"]


def _input_drift(db: Session, mv: m.ModelVersion, start: datetime, end: datetime, cfg: DriftConfig) -> dict[str, Any]:
    ref = (mv.reference_profile or {}).get("features")
    if not ref:
        return {"available": False, "note": "No reference profile (register the model with a reference dataset)."}
    if mv.feature_logging == "none":
        return {"available": False, "note": "Feature logging is disabled for this version."}
    batches = list(db.scalars(select(m.PredictionBatch).where(
        m.PredictionBatch.model_version_id == mv.id, m.PredictionBatch.window_end >= start, m.PredictionBatch.window_start < end)))
    if not batches:
        return {"available": False, "note": "No aggregated feature batches in this window."}
    feats = []
    pvals: list[float | None] = []
    for name, r in ref.items():
        agg_missing = sum(b.feature_stats.get(name, {}).get("missing", 0) for b in batches)
        agg_n = sum(b.feature_stats.get(name, {}).get("n", 0) for b in batches)
        if r["type"] == "numeric":
            cur = np.zeros(len(r["counts"]))
            for b in batches:
                c = b.feature_stats.get(name, {}).get("counts")
                if c and len(c) == len(cur):
                    cur += np.array(c)
            refc = np.array(r["counts"], dtype=float)
            keys = [str(i) for i in range(len(refc))]
        else:
            allk = set(r["counts"])
            for b in batches:
                allk |= set(b.feature_stats.get(name, {}).get("counts", {}))
            keys = sorted(allk)
            refc = np.array([r["counts"].get(k, 0) for k in keys], dtype=float)
            cur = np.zeros(len(keys))
            for b in batches:
                c = b.feature_stats.get(name, {}).get("counts", {})
                cur += np.array([c.get(k, 0) for k in keys])
        n_cur = int(cur.sum())
        entry: dict[str, Any] = {"feature": name, "type": r["type"], "n_reference": int(refc.sum()), "n_current": n_cur,
                                 "reference_missing_pct": round(100 * r["missing"] / r["n"], 3) if r["n"] else 0.0,
                                 "current_missing_pct": round(100 * agg_missing / agg_n, 3) if agg_n else 0.0}
        if n_cur < cfg.min_samples or refc.sum() < cfg.min_samples:
            entry.update(status="insufficient_data", severity="none")
            pvals.append(None)
        else:
            psi = psi_from_counts(refc, cur, cfg.smoothing)
            js = js_distance(refc, cur, cfg.smoothing)
            chi = chi_square_homogeneity(dict(zip(keys, refc.tolist(), strict=True)), dict(zip(keys, cur.tolist(), strict=True)))
            effect = psi if r["type"] == "numeric" else js
            sev = classify(effect, cfg.psi_warning, cfg.psi_critical) if r["type"] == "numeric" else classify(js, cfg.js_warning, cfg.js_critical)
            entry.update(psi=round(psi, 6), js_distance=round(js, 6), chi2_p_value=chi.get("p_value"), severity=sev,
                         reference_distribution=refc.astype(int).tolist(), current_distribution=cur.astype(int).tolist(),
                         bins=keys if r["type"] != "numeric" else _bin_labels(r["edges"]))
            pvals.append(chi.get("p_value") if chi["valid"] else None)
        feats.append(entry)
    adj = adjust_pvalues(pvals, cfg.correction)
    for e, p in zip(feats, adj, strict=True):
        if e.get("status") == "insufficient_data":
            continue
        e["p_value_adjusted"] = p
        significant = p is not None and p < cfg.alpha
        if e["severity"] != "none" and (significant or (p is None and e["severity"] == "critical")):
            e["status"] = "drift"
        else:
            e["status"] = "no_drift"
            e["severity"] = "none"
        metric = f"PSI {e['psi']:.3f}" if e["type"] == "numeric" else f"JS distance {e['js_distance']:.3f}"
        e["explanation"] = (f"{metric}; chi-square p_adj = {p:.2g}" if p is not None else f"{metric}; chi-square not applicable") + \
            f" (n_ref={e['n_reference']:,}, n_cur={e['n_current']:,})."
    drifted = [e for e in feats if e.get("status") == "drift"]
    return {"available": True, "method": "aggregated histograms on reference bins: PSI / JS distance + chi-square, BH-corrected",
            "features": feats, "features_drifted": len(drifted),
            "overall_severity": max((e["severity"] for e in drifted), key=lambda s: {"warning": 1, "critical": 2}.get(s, 0), default="none")}


def default_windows(db: Session, mv: m.ModelVersion) -> tuple[datetime, datetime, datetime | None, datetime | None]:
    lo, hi = db.execute(select(func.min(m.PredictionRecord.predicted_at), func.max(m.PredictionRecord.predicted_at))
                        .where(m.PredictionRecord.model_version_id == mv.id)).one()
    if hi is None:
        now = datetime.now(UTC)
        return now - timedelta(days=1), now, None, None
    cur_end = hi + timedelta(seconds=1)
    cur_start = cur_end - timedelta(days=1)
    return cur_start, cur_end, lo, cur_start


def evaluate(db: Session, model: m.MLModel, mv: m.ModelVersion, current_start: datetime | None = None,
             current_end: datetime | None = None, reference_start: datetime | None = None,
             reference_end: datetime | None = None, trigger: str = "manual", raise_incident: bool = True) -> m.ModelEvaluation:
    ds, de, rs, re_ = default_windows(db, mv)
    current_start, current_end = current_start or ds, current_end or de
    reference_start, reference_end = reference_start or rs, reference_end or re_ or current_start
    rows = db.execute(select(m.PredictionRecord.prediction, m.PredictionRecord.prediction_value, m.PredictionRecord.score,
                             m.PredictionRecord.label, m.PredictionRecord.schema_violations).where(
        m.PredictionRecord.model_version_id == mv.id, m.PredictionRecord.predicted_at >= current_start,
        m.PredictionRecord.predicted_at < current_end)).all()
    preds = [r[0] for r in rows]
    if model.task == "classification":
        metrics = classification_metrics([r[3] for r in rows], preds, [r[2] for r in rows] if any(r[2] is not None for r in rows) else None,
                                         positive_label=model.positive_label)
    else:
        metrics = regression_metrics([None if r[3] is None else float(r[3]) for r in rows], [r[1] for r in rows])
    performance = compare_performance(mv.baseline_metrics or {}, metrics,
                                      float((mv.baseline_metrics or {}).get("degradation_tolerance", 0.05)))
    cfg = DriftConfig()
    pred_drift: dict[str, Any] = {"available": False}
    if reference_start is not None:
        ref_preds = db.execute(select(m.PredictionRecord.prediction, m.PredictionRecord.prediction_value).where(
            m.PredictionRecord.model_version_id == mv.id, m.PredictionRecord.predicted_at >= reference_start,
            m.PredictionRecord.predicted_at < reference_end)).all()
        if ref_preds and rows:
            col = "prediction"
            if model.task == "classification":
                rdf, cdf, t = pd.DataFrame({col: [p[0] for p in ref_preds]}), pd.DataFrame({col: preds}), "categorical"
            else:
                rdf, cdf, t = pd.DataFrame({col: [p[1] for p in ref_preds]}), pd.DataFrame({col: [r[1] for r in rows]}), "numeric"
            res = evaluate_drift(rdf, cdf, {col: t}, config=cfg)
            pred_drift = {"available": True, "reference_window": [reference_start.isoformat(), reference_end.isoformat()],
                          **res["features"][0]} if res["features"] else {"available": False}
    input_drift = _input_drift(db, mv, current_start, current_end, cfg)
    violations = sum(1 for r in rows if r[4])
    sev = {"none": 0, "info": 0, "warning": 1, "critical": 2}
    level = max(sev.get(performance.get("severity", "none"), 0), sev.get(input_drift.get("overall_severity", "none"), 0),
                sev.get(pred_drift.get("severity", "none") if pred_drift.get("status") == "drift" else "none", 0),
                1 if rows and violations / len(rows) > 0.05 else 0)
    status = {0: "ok", 1: "warning", 2: "critical"}[level]
    ev = m.ModelEvaluation(model_version_id=mv.id, window_start=current_start, window_end=current_end,
                           n_predictions=len(rows), n_labelled=metrics.get("n_labelled", 0),
                           label_coverage=metrics.get("label_coverage", 0.0), metrics=numpy_safe(metrics),
                           input_drift=numpy_safe(input_drift), prediction_drift=numpy_safe(pred_drift),
                           performance=numpy_safe(performance), schema_violation_count=violations, status=status, trigger=trigger)
    db.add(ev)
    db.flush()
    if raise_incident and status != "ok":
        _model_incident(db, model, mv, ev)
    return ev


def _model_incident(db: Session, model: m.MLModel, mv: m.ModelVersion, ev: m.ModelEvaluation) -> None:
    findings = []
    for f in ev.input_drift.get("features", []):
        if f.get("status") == "drift":
            findings.append({"source": "model", "kind": "input_drift", "column": f["feature"], "severity": f["severity"],
                             "message": f"Input feature '{f['feature']}' drifted: {f['explanation']}"})
    if ev.prediction_drift.get("status") == "drift":
        findings.append({"source": "model", "kind": "prediction_drift", "column": "prediction",
                         "severity": ev.prediction_drift["severity"], "message": ev.prediction_drift["explanation"]})
    if ev.performance.get("status") == "degraded":
        findings.append({"source": "model", "kind": "performance_degradation", "column": ev.performance["metric"],
                         "severity": ev.performance["severity"], "message": ev.performance["explanation"]})
    if ev.n_predictions and ev.schema_violation_count / ev.n_predictions > 0.05:
        findings.append({"source": "model", "kind": "schema_violation", "column": None, "severity": "warning",
                         "message": f"{ev.schema_violation_count} of {ev.n_predictions} predictions had input schema violations."})
    sig = incidents.significant(findings)
    if not sig:
        return
    for i, f in enumerate(sig):
        f["id"] = f"F{i + 1}"
        f["model_evaluation_id"] = ev.id
    fp = incidents.fingerprint(f"model:{model.id}", sig)
    severity = "critical" if any(f["severity"] == "critical" for f in sig) else "warning"
    node = lsvc.node_for_model(db, model.id)
    from datasentry_core.lineage import impact_of

    impact = impact_of(lsvc.load_graph(db, model.workspace_id), [node.id]) if node else {"affected": [], "counts": {}}
    prio = imp.priority(severity, model.criticality, impact)
    note = ("Input or prediction drift alone does not show the model is less accurate; "
            f"label coverage in this window is {ev.label_coverage:.0%}.")
    existing = db.scalar(select(m.Incident).where(m.Incident.workspace_id == model.workspace_id, m.Incident.fingerprint == fp,
                                                  m.Incident.status.in_(incidents.ACTIVE)))
    if existing:
        existing.occurrence_count += 1
        existing.last_seen_at = datetime.now(UTC)
        existing.findings = numpy_safe(sig)
        incidents.add_event(db, existing, "recurred", f"Same model findings in evaluation #{ev.id}; alert suppressed.", {"evaluation_id": ev.id})
        return
    inc = m.Incident(workspace_id=model.workspace_id, model_id=model.id, title=f"{model.name} {mv.version}: " +
                     ", ".join(sorted({f['kind'].replace('_', ' ') for f in sig})), severity=severity, status="open",
                     fingerprint=fp, findings=numpy_safe(sig),
                     impact=numpy_safe({**impact, "consequences": imp.consequences(
                         [{"kind": "drift" if "drift" in f["kind"] else f["kind"]} for f in sig], impact) + [note],
                         "investigation_steps": ["Compare input feature histograms with the training reference.",
                                                 "Wait for or backfill labels before concluding accuracy has changed.",
                                                 "Check upstream datasets feeding the model for quality incidents."]}),
                     priority=prio, priority_score=prio["score"])
    db.add(inc)
    db.flush()
    incidents.add_event(db, inc, "detected", f"Model evaluation #{ev.id}: " + "; ".join(f["message"][:140] for f in sig[:3]),
                        {"evaluation_id": ev.id})
    notifications.notify(db, model.workspace_id, "incident", f"{severity.upper()}: {inc.title}", body=sig[0]["message"][:500],
                         severity=severity, link=f"/incidents/{inc.id}", dedup_key=f"incident:{inc.id}")
    audit.record(db, model.workspace_id, "incident.created", "incident", inc.id, {"model_id": model.id, "severity": severity})


def daily_series(db: Session, mv: m.ModelVersion, days: int = 60) -> list[dict[str, Any]]:
    day = func.date_trunc("day", m.PredictionRecord.predicted_at)
    rows = db.execute(select(day, func.count(), func.count(m.PredictionRecord.label), func.avg(m.PredictionRecord.score),
                             func.avg(m.PredictionRecord.prediction_value))
                      .where(m.PredictionRecord.model_version_id == mv.id).group_by(day).order_by(day.desc()).limit(days)).all()
    return [{"day": r[0].date().isoformat(), "predictions": r[1], "labelled": r[2],
             "label_coverage": round(r[2] / r[1], 4) if r[1] else 0, "mean_score": r[3], "mean_prediction": r[4]}
            for r in reversed(rows)]


def purge_old_predictions(db: Session) -> int:
    total = 0
    for mv in db.scalars(select(m.ModelVersion)):
        cutoff = datetime.now(UTC) - timedelta(days=mv.retention_days)
        res = db.execute(m.PredictionRecord.__table__.delete().where(
            m.PredictionRecord.model_version_id == mv.id, m.PredictionRecord.predicted_at < cutoff))
        total += res.rowcount or 0
    return total
