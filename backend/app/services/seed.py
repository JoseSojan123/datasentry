"""Seed a workspace with clearly labelled synthetic demo data.

Everything here goes through the same services as real usage (ingestion, monitoring, model
logging, evaluation); nothing writes precomputed results. Data are deterministic (fixed seeds), but
timestamps are anchored to "now" so freshness checks behave realistically.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.services import datasets as dsvc
from app.services import lineage as lsvc
from app.services import models as msvc
from app.services import monitoring
from datasentry_core import synthetic as syn
from datasentry_core.rules import validate_rule

log = logging.getLogger("datasentry.seed")
SYN_DESC = "SYNTHETIC demo data generated with a fixed seed (datasentry_core.synthetic). Not real customers."


def _rule(db: Session, ds: m.Dataset, spec: dict[str, Any]) -> m.QualityRule:
    cfg = validate_rule(spec["rule_type"], spec.get("columns", []), spec.get("config", {}))
    r = m.QualityRule(workspace_id=ds.workspace_id, dataset_id=ds.id, name=spec["name"], rule_type=spec["rule_type"],
                      columns=spec.get("columns", []), config=cfg, severity=spec.get("severity", "warning"))
    db.add(r)
    db.flush()
    return r


def _node(db: Session, ws: int, node_type: str, name: str, criticality: str = "medium", **meta: Any) -> m.LineageNode:
    n = m.LineageNode(workspace_id=ws, node_type=node_type, name=name, criticality=criticality,
                      description=meta.pop("description", None), owner=meta.pop("owner", None), meta={"synthetic_demo": True, **meta})
    db.add(n)
    db.flush()
    return n


def seed_transactions(db: Session, ws: int, principal: Any, now: datetime) -> dict[str, Any]:
    cust = dsvc.create_dataset(db, ws, principal, name="customers", description=SYN_DESC + " Customer master data.",
                               owner="crm-team", tags=["synthetic", "master-data"], domain="customer", criticality="high",
                               source_type="synthetic", primary_key=["customer_id"])
    v = dsvc.ingest_frame(db, cust, syn.customers(), principal, "synthetic", "customers.csv", {"generator": "customers", "seed": 7})
    monitoring.process_version(db, cust, v, "seed", principal)

    tx = dsvc.create_dataset(db, ws, principal, name="card_transactions",
                             description=SYN_DESC + " Card transactions landed hourly from the payments platform.",
                             owner="payments-data", tags=["synthetic", "payments", "pii-free"], domain="payments",
                             criticality="critical", source_type="synthetic", primary_key=["transaction_id"],
                             freshness_column="event_time",
                             settings={"remediation": {"missing_value_policies": {"segment": {"strategy": "mode", "max_affected_pct": 20}}}})
    for spec in syn.default_rules():
        _rule(db, tx, spec)
    _rule(db, tx, {"name": "customer exists", "rule_type": "referential_integrity", "columns": ["customer_id"],
                   "severity": "warning", "config": {"reference_dataset_id": cust.id, "reference_column": "customer_id"}})
    base = syn.transactions(2000, 42, now.replace(tzinfo=None))
    v1 = dsvc.ingest_frame(db, tx, base, principal, "synthetic", "card_transactions_batch1.csv",
                           {"generator": "transactions", "seed": 42, "scenario": "healthy baseline"})
    monitoring.process_version(db, tx, v1, "seed", principal)

    # Lineage: raw → cleaning → feature table → model / reports
    tx_node = lsvc.node_for_dataset(db, tx.id)
    cust_node = lsvc.node_for_dataset(db, cust.id)
    clean = _node(db, ws, "transformation", "clean_transactions", "high", description="dbt model: dedupe, FX-normalise amounts",
                  owner="analytics-eng")
    feats = _node(db, ws, "feature_table", "customer_spend_features", "high", description="Rolling 7/30-day spend per customer",
                  owner="ml-platform")
    report = _node(db, ws, "report", "Daily revenue dashboard", "critical", description="Executive revenue report (BI)",
                   owner="finance-bi")
    recon = _node(db, ws, "consumer", "Finance reconciliation export", "high", description="Nightly export to the ledger team",
                  owner="finance-ops")
    churn = _node(db, ws, "model", "churn_propensity (external)", "medium", description="Churn model served by another team",
                  owner="growth-ds")
    for s, t, prov, dep in [(tx_node, clean, "confirmed", "reads"), (cust_node, clean, "declared", "joins"),
                            (clean, feats, "confirmed", "writes"), (clean, report, "declared", "feeds"),
                            (feats, churn, "inferred", "features"), (clean, recon, "declared", "exports")]:
        lsvc.add_edge(db, ws, s.id, t.id, dep, prov, {"synthetic_demo": True}, None)

    # Second batch with injected problems → real detection → incident with impact + proposals.
    bad = syn.transactions(2000, 1042, now.replace(tzinfo=None), id_offset=2000)
    rng = np.random.default_rng(99)
    idx = rng.choice(len(bad), 640, replace=False)
    bad.loc[idx, "segment"] = None
    idx2 = rng.choice(len(bad), 160, replace=False)
    bad.loc[idx2, "currency"] = rng.choice(["JPY", "XXX"], len(idx2))
    bad["amount"] = np.round(bad["amount"] * 1.45 + 10, 2)
    v2 = dsvc.ingest_frame(db, tx, bad, principal, "synthetic", "card_transactions_batch2.csv",
                           {"generator": "transactions", "seed": 1042,
                            "scenario": "injected: 32% null segment, 8% unknown currency, amount ×1.45+10"})
    res = monitoring.process_version(db, tx, v2, "seed", principal)
    return {"customers_id": cust.id, "transactions_id": tx.id, "incident_id": res.get("incident_id")}


def seed_model(db: Session, ws: int, principal: Any, now: datetime) -> dict[str, Any]:
    train = syn.credit_applications(4000, 11)
    ds = dsvc.create_dataset(db, ws, principal, name="credit_applications_train",
                             description=SYN_DESC + " Training sample for the credit-default classifier (labels from a known "
                                         "logistic data-generating process).",
                             owner="risk-ml", tags=["synthetic", "training"], domain="credit-risk", criticality="high",
                             source_type="synthetic", primary_key=["application_id"])
    v = dsvc.ingest_frame(db, ds, train, principal, "synthetic", "credit_train.csv", {"generator": "credit_applications", "seed": 11})
    monitoring.process_version(db, ds, v, "seed", principal)

    num = ["income", "debt_ratio", "utilization", "late_payments", "age"]

    def X(df):  # noqa: N802
        out = df[num].astype(float).copy()
        out["income"] = np.log(out["income"])
        out["unemployed"] = (df["employment_type"] == "unemployed").astype(float)
        return out.to_numpy()

    hold = syn.credit_applications(1500, 12)
    clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=500)).fit(X(train), train["defaulted"])
    hp = clf.predict_proba(X(hold))[:, 1]
    baseline = {"f1": float(f1_score(hold["defaulted"], hp >= 0.35)), "roc_auc": float(roc_auc_score(hold["defaulted"], hp)),
                "threshold": 0.35, "evaluated_on": "synthetic holdout (seed 12, n=1500)", "degradation_tolerance": 0.05}
    model = msvc.register_model(db, ws, principal, name="credit_default_lr", task="classification",
                                description="Logistic regression predicting 90-day default. Trained on synthetic applications.",
                                target="defaulted within 90 days (1 = default)", positive_label="1",
                                reference_dataset_id=ds.id, criticality="critical", owner="risk-ml")
    schema = [{"name": f, "type": "numeric"} for f in num] + [{"name": "employment_type", "type": "categorical"}]
    mv = msvc.create_version(db, model, principal, version="1.0.0", input_schema=schema, baseline_metrics=baseline,
                             artifact={"framework": "scikit-learn", "estimator": "StandardScaler+LogisticRegression",
                                       "trained_rows": len(train)}, feature_logging="aggregate", retention_days=90)
    consumer = _node(db, ws, "consumer", "Credit decision API", "critical", description="Online loan decisioning service",
                     owner="lending-platform")
    lsvc.add_edge(db, ws, lsvc.node_for_model(db, model.id).id, consumer.id, "serves", "declared", {"synthetic_demo": True}, None)

    start = (now - timedelta(days=14)).replace(minute=0, second=0, microsecond=0)
    for day in range(14):
        if day < 6:
            batch, coverage = syn.credit_applications(300, 100 + day), 1.0
        elif day < 10:
            batch, coverage = syn.credit_applications(300, 100 + day, shift=1.0), 1.0
        elif day < 13:
            batch, coverage = syn.credit_applications(300, 100 + day, concept_change=True), 0.5
        else:
            batch, coverage = syn.credit_applications(300, 100 + day, concept_change=True), 0.0
        proba = clf.predict_proba(X(batch))[:, 1]
        rng = np.random.default_rng(500 + day)
        labelled = rng.random(len(batch)) < coverage
        recs = []
        for i, row in enumerate(batch.itertuples(index=False)):
            ts = start + timedelta(days=day, seconds=int(i * 86400 / len(batch)))
            recs.append({"record_id": row.application_id, "timestamp": ts, "prediction": int(proba[i] >= 0.35),
                         "score": float(proba[i]), "label": int(row.defaulted) if labelled[i] else None,
                         "features": {"income": float(row.income), "debt_ratio": float(row.debt_ratio),
                                      "utilization": float(row.utilization), "late_payments": int(row.late_payments),
                                      "age": float(row.age), "employment_type": row.employment_type}})
        msvc.log_predictions(db, mv, recs, principal)
    ref_s, ref_e = start, start + timedelta(days=3)
    for day in range(3, 14):
        ws_ = start + timedelta(days=day)
        msvc.evaluate(db, model, mv, ws_, ws_ + timedelta(days=1), ref_s, ref_e, trigger="seed", raise_incident=day == 13 or day == 9)
    return {"model_id": model.id, "model_version_id": mv.id, "dataset_id": ds.id}


def seed_jobs(db: Session, ws: int, ids: dict[str, Any], now: datetime) -> None:
    db.add_all([
        m.ScheduledJob(workspace_id=ws, name="Monitor card_transactions", job_type="monitor", target_id=ids["transactions_id"],
                       interval_seconds=6 * 3600, next_run_at=now + timedelta(hours=6)),
        m.ScheduledJob(workspace_id=ws, name="Profile customers", job_type="profile", target_id=ids["customers_id"],
                       interval_seconds=24 * 3600, next_run_at=now + timedelta(hours=24)),
        m.ScheduledJob(workspace_id=ws, name="Evaluate credit_default_lr", job_type="model_eval", target_id=ids["model_version_id"],
                       interval_seconds=24 * 3600, params={"window_hours": 24}, next_run_at=now + timedelta(hours=24)),
    ])
    db.flush()


def seed_workspace(db: Session, ws_id: int, principal: Any = None) -> dict[str, Any]:
    if db.scalar(select(m.Dataset.id).where(m.Dataset.workspace_id == ws_id, m.Dataset.name == "card_transactions")):
        return {"skipped": "sample data already loaded"}
    now = datetime.now(UTC)
    ids = seed_transactions(db, ws_id, principal, now)
    ids.update(seed_model(db, ws_id, principal, now))
    seed_jobs(db, ws_id, ids, now)
    ws = db.get(m.Workspace, ws_id)
    ws.settings = {**(ws.settings or {}), "sample_data_loaded": True}
    db.commit()
    return ids


def load_scenario(db: Session, ws_id: int, name: str, principal: Any) -> dict[str, Any]:
    """Create ``scenario_<name>`` with the healthy baseline and the modified batch, then monitor both."""
    if name not in syn.SCENARIOS:
        from app.core.errors import bad_request

        raise bad_request(f"Unknown scenario. Available: {', '.join(syn.SCENARIOS)}")
    sc = syn.scenario(name, as_of=datetime.now(UTC).replace(tzinfo=None))
    ds_name = f"scenario_{name}"
    existing = db.scalar(select(m.Dataset).where(m.Dataset.workspace_id == ws_id, m.Dataset.name == ds_name))
    if existing:
        from app.core.errors import conflict

        raise conflict(f"Scenario dataset '{ds_name}' already exists.", {"dataset_id": existing.id})
    ds = dsvc.create_dataset(db, ws_id, principal, name=ds_name, description=f"SYNTHETIC scenario: {sc.title}. {sc.description}",
                             owner="demo", tags=["synthetic", "scenario"], domain="demo", criticality="medium",
                             source_type="synthetic", primary_key=["transaction_id"], freshness_column="event_time")
    for spec in sc.expected_rules:
        _rule(db, ds, spec)
    v1 = dsvc.ingest_frame(db, ds, sc.baseline, principal, "synthetic", "baseline.csv", {"scenario": name, "role": "baseline"})
    monitoring.process_version(db, ds, v1, "scenario", principal)
    v2 = dsvc.ingest_frame(db, ds, sc.modified, principal, "synthetic", "modified.csv",
                           {"scenario": name, "role": "modified", "injected": sc.injected})
    res = monitoring.process_version(db, ds, v2, "scenario", principal)
    db.commit()
    return {"dataset_id": ds.id, "injected": sc.injected, "findings": res.get("findings", []), "incident_id": res.get("incident_id")}
