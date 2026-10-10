import io
import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from datasentry_core import synthetic as syn
from tests.conftest import register

API = "/api/v1"


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


def upload_new(client, auth, df, name="tx", **meta):
    files = {"file": (f"{name}.csv", csv_bytes(df), "text/csv")}
    data = {"metadata": json.dumps({"name": name, "primary_key": ["transaction_id"], **meta})}
    r = client.post(f"{API}/datasets/upload", headers=auth, files=files, data=data)
    assert r.status_code == 201, r.text
    return r.json()


def upload_version(client, auth, ds_id, df, name="batch.csv"):
    r = client.post(f"{API}/datasets/{ds_id}/versions", headers=auth, files={"file": (name, csv_bytes(df), "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()


NOW = datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------- health & auth


def test_health_and_ready(client):
    assert client.get("/health").json()["status"] == "ok"
    r = client.get(f"{API}/ready").json()
    assert r["status"] == "ready" and r["migration"] == "0001"
    assert "database_url" not in json.dumps(r)


def test_auth_required_and_login(client):
    assert client.get(f"{API}/datasets").status_code == 401
    headers, reg = register(client)
    r = client.post(f"{API}/auth/login", json={"email": reg["user"]["email"], "password": "correct horse battery"})
    assert r.status_code == 200
    assert client.post(f"{API}/auth/login", json={"email": reg["user"]["email"], "password": "nope"}).status_code == 401
    me = client.get(f"{API}/auth/me", headers=headers).json()
    assert me["role"] == "admin" and "password_hash" not in json.dumps(me)


def test_validation_errors_are_structured(client, auth):
    r = client.post(f"{API}/datasets", headers=auth, json={"name": ""})
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "validation_error" and body["request_id"] and body["details"][0]["field"] == "name"


def test_api_keys_hashed_revocable_and_role_limited(client, auth):
    r = client.post(f"{API}/api-keys", headers=auth, json={"name": "ci", "role": "viewer"})
    assert r.status_code == 201
    secret = r.json()["secret"]
    listed = client.get(f"{API}/api-keys", headers=auth).json()["items"]
    assert secret not in json.dumps(listed)
    k = {"X-API-Key": secret}
    assert client.get(f"{API}/datasets", headers=k).status_code == 200
    assert client.post(f"{API}/datasets", headers=k, json={"name": "x"}).status_code == 403  # viewer cannot write
    client.delete(f"{API}/api-keys/{r.json()['id']}", headers=auth)
    assert client.get(f"{API}/datasets", headers=k).status_code == 401
    assert client.get(f"{API}/datasets", headers={"X-API-Key": "dsk_deadbeef_forged"}).status_code == 401


def test_cross_workspace_access_is_denied(client, auth):
    out = upload_new(client, auth, syn.transactions(300, 1, NOW), name="private")
    other, _ = register(client, "other")
    ds_id = out["dataset"]["id"]
    vid = out["version"]["id"]
    assert client.get(f"{API}/datasets/{ds_id}", headers=other).status_code == 404
    assert client.get(f"{API}/versions/{vid}/preview", headers=other).status_code == 404
    assert client.post(f"{API}/datasets/{ds_id}/rules", headers=other,
                       json={"name": "x", "rule_type": "not_null", "columns": ["amount"]}).status_code == 404
    assert client.get(f"{API}/datasets", headers=other).json()["total"] == 0


# ---------------------------------------------------------------- ingestion & profiling


def test_upload_profile_preview_and_persistence(client, auth):
    df = syn.transactions(500, 3, NOW)
    df.loc[[1, 2, 3], "segment"] = None
    out = upload_new(client, auth, df, name="tx_profile", criticality="high", tags=["a"])
    v = out["version"]
    assert v["row_count"] == 500 and v["column_count"] == 10 and len(v["checksum"]) == 64
    types = {c["name"]: c["semantic_type"] for c in v["columns"]}
    assert types["amount"] == "numeric" and types["event_time"] == "datetime" and types["currency"] == "categorical"
    prof = client.get(f"{API}/versions/{v['id']}/profile", headers=auth).json()
    assert prof["columns"]["segment"]["missing_count"] == 3
    assert prof["columns"]["amount"]["mean"] == round(float(df["amount"].mean()), 10) or abs(
        prof["columns"]["amount"]["mean"] - df["amount"].mean()) < 1e-6
    assert prof["summary"]["duplicate_key_count"] == 0
    pv = client.get(f"{API}/versions/{v['id']}/preview?offset=0&limit=5", headers=auth).json()
    assert len(pv["rows"]) == 5 and pv["total"] == 500 and pv["rows"][1]["segment"] is None
    ds = client.get(f"{API}/datasets/{out['dataset']['id']}", headers=auth).json()
    assert ds["current_version_id"] == v["id"] and ds["health"] == "healthy"


def test_rejects_bad_files(client, auth):
    meta = {"metadata": json.dumps({"name": "bad"})}
    r = client.post(f"{API}/datasets/upload", headers=auth, files={"file": ("x.exe", b"MZ", "application/octet-stream")}, data=meta)
    assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_format"
    r = client.post(f"{API}/datasets/upload", headers=auth, files={"file": ("x.csv", b"", "text/csv")}, data=meta)
    assert r.status_code == 400
    r = client.post(f"{API}/datasets/upload", headers=auth, files={"file": ("x.csv", "a,b\ncafé,1\n".encode("latin-1"), "text/csv")},
                    data={"metadata": json.dumps({"name": "bad_enc"})})
    assert r.status_code == 201
    v = r.json()["version"]
    assert v["ingestion_status"] == "failed" and v["ingestion_error"]["code"] == "bad_encoding"
    assert r.json()["monitoring"]["status"] == "ingestion_failed"


def test_duplicate_upload_rejected(client, auth):
    df = syn.transactions(200, 4, NOW)
    out = upload_new(client, auth, df, name="dup")
    r = client.post(f"{API}/datasets/{out['dataset']['id']}/versions", headers=auth, files={"file": ("a.csv", csv_bytes(df), "text/csv")})
    assert r.status_code == 409


# ---------------------------------------------------------------- rules


def test_rule_crud_and_execution(client, auth):
    out = upload_new(client, auth, syn.transactions(400, 5, NOW), name="tx_rules")
    ds = out["dataset"]["id"]
    bad = client.post(f"{API}/datasets/{ds}/rules", headers=auth, json={"name": "r", "rule_type": "regex", "columns": ["email"],
                                                                      "config": {"pattern": "(a+)+"}})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_rule"
    r = client.post(f"{API}/datasets/{ds}/rules", headers=auth, json={"name": "amount range", "rule_type": "range",
                                                                    "columns": ["amount"], "config": {"min": 0, "max": 50},
                                                                    "severity": "critical"})
    assert r.status_code == 201
    run = client.post(f"{API}/datasets/{ds}/validate", headers=auth, json={}).json()
    res = run["results"][0]
    df = syn.transactions(400, 5, NOW)
    assert res["status"] == "fail" and res["failed_rows"] == int((df["amount"] > 50).sum()) and res["rows_evaluated"] == 400
    inline = client.post(f"{API}/datasets/{ds}/validate", headers=auth,
                         json={"rules": [{"type": "not_null", "column": "transaction_id"}, {"type": "unique", "column": "transaction_id"}],
                               "only_inline": True}).json()
    assert inline["summary"]["total"] == 2 and inline["summary"]["passed"] == 2
    rules = client.get(f"{API}/datasets/{ds}/rules", headers=auth).json()["items"]
    assert len(rules) == 3 and rules[0]["last_result"]["status"] == "fail"
    hist = client.get(f"{API}/rules/{rules[0]['id']}/history", headers=auth).json()
    assert hist["total"] == 1
    client.patch(f"{API}/rules/{rules[0]['id']}", headers=auth, json={"config": {"min": 0, "max": 100000}})
    run2 = client.post(f"{API}/datasets/{ds}/validate", headers=auth, json={}).json()
    assert all(x["status"] == "pass" for x in run2["results"])


def test_referential_integrity_between_datasets(client, auth):
    cust = upload_new(client, auth, syn.customers(100), name="cust")
    tx = upload_new(client, auth, syn.transactions(300, 6, NOW, n_customers=150), name="tx_ri")
    r = client.post(f"{API}/datasets/{tx['dataset']['id']}/rules", headers=auth,
                    json={"name": "fk", "rule_type": "referential_integrity", "columns": ["customer_id"],
                          "config": {"reference_dataset_id": cust["dataset"]["id"], "reference_column": "customer_id"}})
    assert r.status_code == 201
    run = client.post(f"{API}/datasets/{tx['dataset']['id']}/validate", headers=auth, json={}).json()
    res = run["results"][0]
    df = syn.transactions(300, 6, NOW, n_customers=150)
    expected = int((df["customer_id"].str[1:].astype(int) > 100).sum())
    assert res["status"] == "fail" and res["failed_rows"] == expected


# ---------------------------------------------------------------- versions, drift, incidents, remediation


def test_version_comparison_and_rename_confirmation(client, auth):
    sc = syn.scenario("schema_change", n=600, as_of=NOW)
    out = upload_new(client, auth, sc.baseline, name="tx_schema")
    ds = out["dataset"]["id"]
    v2 = upload_version(client, auth, ds, sc.modified)["version"]
    comp = client.post(f"{API}/datasets/{ds}/compare", headers=auth,
                       json={"base_version_id": out["version"]["id"], "target_version_id": v2["id"]}).json()
    kinds = {(c["kind"], c["column"]) for c in comp["result"]["changes"]}
    assert ("column_removed", "channel") in kinds and ("rename_candidate", "amount") in kinds
    cand = comp["result"]["rename_candidates"][0]
    assert cand["to"] == "transaction_amount"
    client.post(f"{API}/datasets/{ds}/rename-decisions", headers=auth,
                json={"from_column": "amount", "to_column": "transaction_amount", "decision": "confirmed"})
    comp2 = client.post(f"{API}/datasets/{ds}/compare", headers=auth,
                        json={"base_version_id": out["version"]["id"], "target_version_id": v2["id"]}).json()
    kinds2 = {(c["kind"], c["column"]) for c in comp2["result"]["changes"]}
    assert ("column_renamed", "amount") in kinds2 and ("column_removed", "amount") not in kinds2


def test_drift_endpoint_and_windows(client, auth):
    sc = syn.scenario("numeric_drift", n=800, as_of=NOW)
    out = upload_new(client, auth, sc.baseline, name="tx_drift")
    ds = out["dataset"]["id"]
    upload_version(client, auth, ds, sc.modified)
    ev = client.post(f"{API}/datasets/{ds}/drift", headers=auth, json={"config": {"psi_warning": 0.2, "psi_critical": 0.5}}).json()
    amt = next(f for f in ev["features"] if f["feature"] == "amount")
    assert amt["status"] == "drift" and amt["statistics"]["psi"] > 0.5 and ev["config"]["psi_warning"] == 0.2
    assert "histogram" in amt["evidence"]
    same = client.post(f"{API}/datasets/{ds}/drift", headers=auth, json={
        "reference_version_id": out["version"]["id"], "current_version_id": out["version"]["id"], "window_column": "event_time",
        "reference_start": (NOW - timedelta(days=7)).isoformat(), "reference_end": (NOW - timedelta(days=4)).isoformat(),
        "current_start": (NOW - timedelta(days=3)).isoformat()})
    assert same.status_code == 201 and same.json()["summary"]["features_drifted"] == 0
    bad = client.post(f"{API}/datasets/{ds}/drift", headers=auth, json={"config": {"alpha": 3}})
    assert bad.status_code == 400


def _setup_incident(client, auth, name="tx_e2e"):
    base = syn.transactions(1500, 21, NOW)
    out = upload_new(client, auth, base, name=name, criticality="critical", freshness_column="event_time")
    ds = out["dataset"]["id"]
    for spec in syn.default_rules():
        r = client.post(f"{API}/datasets/{ds}/rules", headers=auth, json={**spec, "config": spec.get("config", {})})
        assert r.status_code == 201, r.text
    graph = client.get(f"{API}/lineage/graph", headers=auth).json()
    ds_node = next(n for n in graph["nodes"] if n["dataset_id"] == ds)
    t = client.post(f"{API}/lineage/nodes", headers=auth, json={"node_type": "transformation", "name": f"{name}_clean"}).json()
    rep = client.post(f"{API}/lineage/nodes", headers=auth, json={"node_type": "report", "name": f"{name} revenue", "criticality": "critical"}).json()
    client.post(f"{API}/lineage/edges", headers=auth, json={"source_id": ds_node["id"], "target_id": t["id"]})
    client.post(f"{API}/lineage/edges", headers=auth, json={"source_id": t["id"], "target_id": rep["id"]})
    bad = syn.transactions(1500, 22, NOW, id_offset=1500)
    bad["currency"] = np.where(np.arange(len(bad)) % 10 == 0, "XXX", bad["currency"])
    bad["amount"] = bad["amount"] * 1.5 + 10
    mon = upload_version(client, auth, ds, bad)
    return ds, out["version"]["id"], mon, ds_node, t, rep


def test_end_to_end_incident_remediation_and_audit(client, auth):
    ds, v1_id, mon, ds_node, t, rep = _setup_incident(client, auth)
    m = mon["monitoring"]
    kinds = {(f["kind"], f["column"]) for f in m["findings"]}
    assert ("allowed_values", "currency") in kinds and ("drift", "amount") in kinds
    inc = client.get(f"{API}/incidents/{m['incident_id']}", headers=auth).json()
    assert inc["severity"] == "critical" and inc["status"] == "open"
    assert inc["impact"]["counts"]["total"] == 2 and inc["impact"]["counts"]["reports"] == 1
    assert inc["impact"]["consequences"] and inc["priority"]["urgency"] in ("P1", "P2")
    inv = client.get(f"{API}/incidents/{inc['id']}/investigation", headers=auth).json()
    assert inv["source_node_id"] == ds_node["id"] and {n["role"] for n in inv["nodes"]} >= {"source", "affected"}
    actions = {p["action"]: p for p in inc["proposals"]}
    assert {"quarantine_version", "restore_last_known_good", "notify_operator"} <= set(actions)
    q = actions["quarantine_version"]
    assert q["status"] == "proposed" and q["approval_required"]
    # cannot execute without approval
    assert client.post(f"{API}/remediations/{q['id']}/execute", headers=auth).status_code == 409
    assert client.post(f"{API}/remediations/{q['id']}/approve", headers=auth, json={"note": "ok"}).status_code == 200
    res = client.post(f"{API}/remediations/{q['id']}/execute", headers=auth).json()
    assert res["execution"]["status"] == "succeeded"
    assert res["execution"]["verification"]["passed"] is True
    assert res["proposal"]["status"] == "verified"
    assert res["incident"]["status"] == "resolved" and res["incident"]["resolution"]["type"] == "verified"
    dsj = client.get(f"{API}/datasets/{ds}", headers=auth).json()
    assert dsj["current_version_id"] == v1_id and dsj["health"] == "healthy"
    versions = client.get(f"{API}/datasets/{ds}/versions", headers=auth).json()["items"]
    assert versions[0]["status"] == "quarantined"
    # idempotent re-execution returns the same execution
    again = client.post(f"{API}/remediations/{q['id']}/execute", headers=auth).json()
    assert again["execution"]["id"] == res["execution"]["id"]
    timeline = [e["event_type"] for e in client.get(f"{API}/incidents/{inc['id']}", headers=auth).json()["events"]]
    for ev in ("detected", "remediation_proposed", "remediation_approved", "remediation_executed", "remediation_verified", "resolved"):
        assert ev in timeline
    audit = client.get(f"{API}/audit?entity_type=remediation_proposal", headers=auth).json()["items"]
    assert {"remediation.approved", "remediation.verified"} <= {a["action"] for a in audit}


def test_incident_dedup_and_manual_transitions(client, auth):
    ds, _, mon, *_ = _setup_incident(client, auth, name="tx_dedup")
    inc_id = mon["monitoring"]["incident_id"]
    vid = mon["version"]["id"]
    again = client.post(f"{API}/versions/{vid}/monitor", headers=auth).json()
    assert again["incident_id"] == inc_id
    inc = client.get(f"{API}/incidents/{inc_id}", headers=auth).json()
    assert inc["occurrence_count"] == 2
    assert client.post(f"{API}/incidents/{inc_id}/status", headers=auth, json={"status": "resolved"}).status_code == 400
    assert client.post(f"{API}/incidents/{inc_id}/status", headers=auth, json={"status": "acknowledged"}).status_code == 200
    assert client.post(f"{API}/incidents/{inc_id}/status", headers=auth, json={"status": "reopened"}).status_code == 400
    c = client.post(f"{API}/incidents/{inc_id}/comments", headers=auth, json={"body": "Looking at the producer."})
    assert c.status_code == 201
    r = client.post(f"{API}/incidents/{inc_id}/status", headers=auth, json={"status": "resolved", "note": "False positive: test data"})
    assert r.json()["status"] == "resolved" and r.json()["resolution"]["type"] == "manual"


def test_missing_value_policy_refused_above_limit_and_applied_below(client, auth):
    base = syn.transactions(1000, 31, NOW)
    out = upload_new(client, auth, base, name="tx_fill")
    ds = out["dataset"]["id"]
    client.post(f"{API}/datasets/{ds}/rules", headers=auth, json={"name": "seg", "rule_type": "not_null", "columns": ["segment"],
                                                                "severity": "critical"})
    client.put(f"{API}/datasets/{ds}/settings", headers=auth,
               json={"remediation": {"missing_value_policies": {"segment": {"strategy": "mode", "max_affected_pct": 10}}}})
    cur = syn.transactions(1000, 32, NOW, id_offset=1000)
    cur.loc[cur.index[:50], "segment"] = None  # 5%: within the 10% limit
    mon = upload_version(client, auth, ds, cur)["monitoring"]
    inc = client.get(f"{API}/incidents/{mon['incident_id']}", headers=auth).json()
    fill = next(p for p in inc["proposals"] if p["action"] == "apply_missing_value_policy")
    client.post(f"{API}/remediations/{fill['id']}/approve", headers=auth, json={})
    res = client.post(f"{API}/remediations/{fill['id']}/execute", headers=auth).json()
    assert res["execution"]["result"]["rows_affected"] == 50
    assert res["execution"]["verification"]["passed"] is True
    derived = res["execution"]["result"]["derived_version_id"]
    assert client.get(f"{API}/datasets/{ds}", headers=auth).json()["current_version_id"] == derived
    original = client.get(f"{API}/versions/{mon['version_id']}/preview?limit=50", headers=auth).json()
    assert all(r["segment"] is None for r in original["rows"])  # original preserved


def test_remediation_precondition_failure_preserves_data(client, auth):
    base = syn.transactions(1000, 41, NOW)
    out = upload_new(client, auth, base, name="tx_refuse")
    ds = out["dataset"]["id"]
    client.post(f"{API}/datasets/{ds}/rules", headers=auth, json={"name": "seg", "rule_type": "not_null", "columns": ["segment"],
                                                                "severity": "critical"})
    client.put(f"{API}/datasets/{ds}/settings", headers=auth,
               json={"remediation": {"missing_value_policies": {"segment": {"strategy": "mode", "max_affected_pct": 10}}}})
    cur = syn.transactions(1000, 42, NOW, id_offset=1000)
    cur.loc[cur.index[:400], "segment"] = None  # 40% > 10%
    mon = upload_version(client, auth, ds, cur)["monitoring"]
    inc = client.get(f"{API}/incidents/{mon['incident_id']}", headers=auth).json()
    fill = next(p for p in inc["proposals"] if p["action"] == "apply_missing_value_policy")
    assert any(not c["passed"] for c in fill["preconditions"])
    client.post(f"{API}/remediations/{fill['id']}/approve", headers=auth, json={})
    res = client.post(f"{API}/remediations/{fill['id']}/execute", headers=auth).json()
    assert res["execution"]["status"] == "failed" and "Precondition failed" in res["execution"]["error"]
    assert res["incident"]["status"] != "resolved"
    n_versions = client.get(f"{API}/datasets/{ds}/versions", headers=auth).json()["total"]
    assert n_versions == 2


def test_recommend_only_and_auto_modes(client, auth):
    assert client.put(f"{API}/settings/remediation", headers=auth, json={"mode": "auto",
                                                                          "auto_allowlist": ["restore_last_known_good"]}).status_code == 400
    client.put(f"{API}/settings/remediation", headers=auth, json={"mode": "auto", "auto_allowlist": ["quarantine_version"]})
    ds, v1, mon, *_ = _setup_incident(client, auth, name="tx_auto")
    inc = client.get(f"{API}/incidents/{mon['monitoring']['incident_id']}", headers=auth).json()
    q = next(p for p in inc["proposals"] if p["action"] == "quarantine_version")
    assert q["execution_mode"] == "auto" and q["status"] == "verified"
    restore = next(p for p in inc["proposals"] if p["action"] == "restore_last_known_good")
    assert restore["execution_mode"] == "approval"
    assert inc["status"] == "resolved"


def test_lineage_cycle_rejected_and_impact(client, auth):
    a = client.post(f"{API}/lineage/nodes", headers=auth, json={"node_type": "transformation", "name": "a"}).json()
    b = client.post(f"{API}/lineage/nodes", headers=auth, json={"node_type": "feature_table", "name": "b"}).json()
    c = client.post(f"{API}/lineage/nodes", headers=auth, json={"node_type": "report", "name": "c"}).json()
    assert client.post(f"{API}/lineage/edges", headers=auth, json={"source_id": a["id"], "target_id": b["id"]}).status_code == 201
    assert client.post(f"{API}/lineage/edges", headers=auth, json={"source_id": b["id"], "target_id": c["id"]}).status_code == 201
    r = client.post(f"{API}/lineage/edges", headers=auth, json={"source_id": c["id"], "target_id": a["id"]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "cycle_detected"
    imp = client.get(f"{API}/lineage/nodes/{a['id']}/impact", headers=auth).json()
    assert imp["counts"]["total"] == 2 and imp["counts"]["confirmed"] == 0
    r = client.post(f"{API}/lineage/edges", headers=auth, json={"source_id": a["id"], "target_id": c["id"], "provenance": "confirmed"})
    assert r.status_code == 422  # users cannot claim confirmed provenance


# ---------------------------------------------------------------- models


def test_model_registry_predictions_labels_and_evaluation(client, auth):
    train = syn.credit_applications(1500, 1)
    ref = upload_new(client, auth, train.drop(columns=["application_id"]).assign(application_id=train["application_id"]),
                     name="credit_ref", primary_key=[])
    mo = client.post(f"{API}/models", headers=auth, json={"name": "credit", "task": "classification", "positive_label": "1",
                                                        "reference_dataset_id": ref["dataset"]["id"]}).json()
    schema = [{"name": f, "type": "numeric"} for f in ["income", "debt_ratio", "utilization", "late_payments", "age"]] + \
             [{"name": "employment_type", "type": "categorical"}]
    mv = client.post(f"{API}/models/{mo['id']}/versions", headers=auth, json={"version": "1", "input_schema": schema,
                                                                             "baseline_metrics": {"f1": 0.6}}).json()
    assert "income" in mv["reference_features"]
    t0 = datetime(2026, 1, 1, tzinfo=UTC)

    def preds(df, start, labelled=True):
        out = []
        for i, row in enumerate(df.itertuples(index=False)):
            p = 1 if row.debt_ratio + row.utilization > 0.9 else 0
            out.append({"record_id": row.application_id, "timestamp": (start + timedelta(minutes=i)).isoformat(), "prediction": p,
                        "score": float(min(1, row.debt_ratio + row.utilization) / 1.5),
                        "label": int(row.defaulted) if labelled else None,
                        "features": {k: (float(getattr(row, k)) if k != "employment_type" else row.employment_type)
                                     for k in ["income", "debt_ratio", "utilization", "late_payments", "age", "employment_type"]}})
        return out

    ref_batch = syn.credit_applications(400, 2)
    r = client.post(f"{API}/models/{mo['id']}/predictions", headers=auth, json={"model_version": "1", "predictions": preds(ref_batch, t0)})
    assert r.json()["accepted"] == 400
    dup = client.post(f"{API}/models/{mo['id']}/predictions", headers=auth, json={"model_version": "1", "predictions": preds(ref_batch, t0)[:5]})
    assert dup.json() == {"accepted": 0, "duplicates": 5, "schema_violations": 0}
    drifted = syn.credit_applications(400, 3, shift=1.5)
    client.post(f"{API}/models/{mo['id']}/predictions", headers=auth,
                json={"model_version": "1", "predictions": preds(drifted, t0 + timedelta(days=2), labelled=False)})
    ev = client.post(f"{API}/models/{mo['id']}/evaluate", headers=auth, json={
        "model_version": "1", "current_start": (t0 + timedelta(days=2)).isoformat(), "current_end": (t0 + timedelta(days=3)).isoformat(),
        "reference_start": t0.isoformat(), "reference_end": (t0 + timedelta(days=1)).isoformat()}).json()
    assert ev["label_coverage"] == 0 and ev["metrics"]["status"] == "no_labels" and ev["performance"]["status"] == "unknown"
    assert ev["input_drift"]["available"] and ev["input_drift"]["features_drifted"] >= 2
    assert ev["prediction_drift"]["available"]
    labels = [{"record_id": r.application_id, "label": int(r.defaulted)} for r in drifted.head(200).itertuples()]
    lr = client.post(f"{API}/models/{mo['id']}/labels", headers=auth, json={"model_version": "1", "labels": labels}).json()
    assert lr["updated"] == 200
    ev2 = client.post(f"{API}/models/{mo['id']}/evaluate", headers=auth, json={
        "model_version": "1", "current_start": (t0 + timedelta(days=2)).isoformat(), "current_end": (t0 + timedelta(days=3)).isoformat()}).json()
    assert ev2["label_coverage"] == 0.5 and ev2["metrics"]["status"] == "ok" and "f1" in ev2["metrics"]
    inc = client.get(f"{API}/incidents?model_id={mo['id']}", headers=auth).json()
    assert inc["total"] >= 1


# ---------------------------------------------------------------- jobs


def test_jobs_run_now_history_and_cron(client, auth):
    out = upload_new(client, auth, syn.transactions(300, 51, NOW), name="tx_jobs")
    ds = out["dataset"]["id"]
    j = client.post(f"{API}/jobs", headers=auth, json={"name": "profile", "job_type": "profile", "target_id": ds,
                                                      "interval_seconds": 3600}).json()
    assert client.post(f"{API}/jobs", headers=auth, json={"name": "x", "job_type": "profile", "target_id": 999999,
                                                          "interval_seconds": 3600}).status_code == 400
    exe = client.post(f"{API}/jobs/{j['id']}/run", headers=auth).json()
    assert exe["status"] == "succeeded" and exe["result"]["profile_id"]
    job = client.get(f"{API}/jobs", headers=auth).json()["items"][0]
    assert job["last_status"] == "succeeded" and job["last_success_at"]
    assert client.post(f"{API}/jobs/run-due").status_code == 401
    r = client.post(f"{API}/jobs/run-due", headers={"X-Cron-Secret": "test-cron-secret"})
    assert r.status_code == 200


def test_failing_job_retries_then_alerts(client, auth):
    from app.db import models as mm
    from app.db.session import SessionLocal
    from app.services import jobs

    out = upload_new(client, auth, syn.transactions(300, 61, NOW), name="tx_jobfail")
    ds = out["dataset"]["id"]
    j = client.post(f"{API}/jobs", headers=auth, json={"name": "drift-bad", "job_type": "monitor", "target_id": ds,
                                                      "interval_seconds": 3600, "max_retries": 1}).json()
    db = SessionLocal()
    job = db.get(mm.ScheduledJob, j["id"])
    dataset = db.get(mm.Dataset, ds)
    dataset.current_version_id = None  # make the job fail deterministically
    db.commit()
    e1 = jobs.execute_job(db, job, "schedule", 1)
    assert e1.status == "failed" and db.get(mm.ScheduledJob, j["id"]).params["_pending_attempt"] == 2
    e2 = jobs.execute_job(db, db.get(mm.ScheduledJob, j["id"]), "retry", 2)
    assert e2.status == "failed"
    db.close()
    notes = client.get(f"{API}/notifications", headers=auth).json()["items"]
    assert any(n["kind"] == "job_failed" for n in notes)


def test_overview_reflects_records(client, auth):
    empty = client.get(f"{API}/overview", headers=auth).json()
    assert empty["datasets"]["total"] == 0 and empty["incidents"]["open"] == 0
    _setup_incident(client, auth, name="tx_overview")
    ov = client.get(f"{API}/overview", headers=auth).json()
    assert ov["datasets"]["total"] == 1 and ov["incidents"]["open"] == 1 and ov["incidents"]["critical"] == 1
    assert ov["top_incidents"][0]["severity"] == "critical" and ov["recent_drift"]


def test_sdk_records_endpoint(client, auth):
    r = client.post(f"{API}/datasets", headers=auth, json={"name": "sdk_ds"})
    ds = r.json()["id"]
    recs = syn.transactions(100, 71, NOW).to_dict(orient="records")
    up = client.post(f"{API}/datasets/{ds}/versions/records", headers=auth, json={"records": recs})
    assert up.status_code == 201 and up.json()["version"]["row_count"] == 100 and up.json()["version"]["origin"] == "sdk"


def test_viewer_role_cannot_mutate(client, auth):
    r = client.post(f"{API}/users", headers=auth, json={"email": "viewer-x@example.com", "display_name": "V", "password": "longpassword1",
                                                       "role": "viewer"})
    assert r.status_code == 201
    tok = client.post(f"{API}/auth/login", json={"email": "viewer-x@example.com", "password": "longpassword1"}).json()["access_token"]
    vh = {"Authorization": f"Bearer {tok}"}
    assert client.get(f"{API}/datasets", headers=vh).status_code == 200
    assert client.post(f"{API}/datasets", headers=vh, json={"name": "nope"}).status_code == 403
    assert client.get(f"{API}/api-keys", headers=vh).status_code == 403


def test_rate_limit_on_auth(client):
    from app.core.ratelimit import limiter

    limiter.reset()
    import os

    os.environ["RATE_LIMIT_AUTH_PER_MIN"] = "3"
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        codes = [client.post(f"{API}/auth/login", json={"email": "a@b.co", "password": "x"}).status_code for _ in range(5)]
        assert codes[-1] == 429
    finally:
        os.environ["RATE_LIMIT_AUTH_PER_MIN"] = "1000"
        get_settings.cache_clear()
        limiter.reset()


_ = io
