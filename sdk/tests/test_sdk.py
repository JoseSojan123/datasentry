from datetime import UTC, datetime, timedelta

import pytest
from datasentry import DataSentryError

from datasentry_core import synthetic as syn

NOW = datetime.now(UTC).replace(tzinfo=None)


def test_readme_example(client):
    df = syn.transactions(400, 1, NOW).rename(columns={"customer_id": "cust"}).assign(customer_id=lambda d: d["transaction_id"])
    dataset = client.register_dataset(name="customer_events", data=df, description="Customer activity dataset")
    assert dataset.id and dataset.current_version.row_count == 400 and dataset.monitoring.status == "healthy"
    profile = client.profile(dataset.id)
    assert profile.row_count == 400 and profile.column("amount")["count"] == 400
    result = client.validate(dataset.id, rules=[{"type": "not_null", "column": "customer_id"},
                                                {"type": "unique", "column": "customer_id"}])
    assert result.summary["total"] == 2 and result.passed and result.failures == []


def test_versions_drift_and_comparison(client):
    sc = syn.scenario("numeric_drift", n=600, as_of=NOW)
    ds = client.register_dataset(name="sdk_drift", data=sc.baseline)
    v2, mon = client.create_version(ds.id, sc.modified)
    assert v2.version_number == 2 and any(f["kind"] == "drift" for f in mon.findings)
    drift = client.compare_drift(ds.id, reference_version_id=ds.current_version_id, current_version_id=v2.id)
    assert drift.drifted_features == ["amount"] and drift.feature("amount")["statistics"]["psi"] > 0.25
    comp = client.compare_versions(ds.id, ds.current_version_id, v2.id)
    assert comp["result"]["summary"]["schema_changed"] is False
    assert [v.version_number for v in client.versions(ds.id)] == [2, 1]


def test_failures_and_errors(client):
    ds = client.register_dataset(name="sdk_fail", data=syn.scenario("missing_spike", n=300, as_of=NOW).modified)
    client.add_rule(ds.id, "not_null", ["segment"], severity="critical")
    res = client.validate(ds.id, only_inline=False)
    assert not res.passed and res.failures[0].failed_rows == 90
    with pytest.raises(DataSentryError) as e:
        client.add_rule(ds.id, "regex", ["email"], {"pattern": "(a+)+"})
    assert e.value.status == 400 and e.value.code == "invalid_rule"
    with pytest.raises(DataSentryError) as e:
        client.get_dataset(999999)
    assert e.value.status == 404
    assert client.get_dataset("sdk_fail").id == ds.id


def test_models_lineage_and_incidents(client):
    train = syn.credit_applications(800, 5)
    ref = client.register_dataset(name="sdk_credit", data=train)
    model = client.register_model("sdk_credit_model", "classification", positive_label=1, reference_dataset_id=ref.id)
    schema = [{"name": "income", "type": "numeric"}, {"name": "utilization", "type": "numeric"}]
    client.create_model_version(model.id, "v1", input_schema=schema, baseline_metrics={"f1": 0.5})
    t0 = datetime(2026, 3, 1, tzinfo=UTC)
    batch = syn.credit_applications(200, 6)
    preds = [{"record_id": r.application_id, "timestamp": t0 + timedelta(minutes=i), "prediction": int(r.utilization > 0.5),
              "score": float(r.utilization), "features": {"income": float(r.income), "utilization": float(r.utilization)}}
             for i, r in enumerate(batch.itertuples())]
    out = client.log_predictions(model.id, "v1", preds)
    assert out["accepted"] == 200
    labels = client.log_labels(model.id, "v1", [{"record_id": r.application_id, "label": int(r.defaulted)} for r in batch.itertuples()])
    assert labels["updated"] == 200
    ev = client.evaluate_model(model.id, "v1", current_window=(t0, t0 + timedelta(days=1)))
    assert ev.n_labelled == 200 and ev.label_coverage == 1.0 and "f1" in ev.metrics
    report = client.add_lineage_node("SDK report", "report", criticality="high")
    mnode = client.node_id(model_id=model.id)
    client.register_lineage(mnode, report["id"], "feeds")
    imp = client.impact(client.node_id(dataset_id=ref.id))
    assert {a["name"] for a in imp["affected"]} == {"sdk_credit_model", "SDK report"}
    sc = syn.scenario("unexpected_categories", n=400, as_of=NOW)
    ds = client.register_dataset(name="sdk_inc", data=sc.baseline)
    client.add_rule(ds.id, "allowed_values", ["currency"], {"values": ["USD", "EUR", "GBP"]}, severity="critical")
    _, mon = client.create_version(ds.id, sc.modified)
    incs = client.incidents(status=["open"], dataset_id=ds.id)
    assert len(incs) == 1 and incs[0].id == mon.incident_id and client.get_incident(incs[0].id).severity == "critical"
