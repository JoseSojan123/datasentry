import numpy as np
import pandas as pd
import pytest

from datasentry_core import impact
from datasentry_core.lineage import Edge, Graph, Node, impact_of
from datasentry_core.model_metrics import classification_metrics, compare_performance, regression_metrics
from datasentry_core.remediation import (
    RemediationRefused,
    execution_mode,
    missing_value_policy,
    recommend,
    type_conversion,
    validate_allowlist,
)
from datasentry_core.schema_diff import DiffConfig, compare_versions

# ---------------------------------------------------------------- schema diff


def _schema(*cols):
    return [{"name": n, "position": i, "semantic_type": t} for i, (n, t) in enumerate(cols)]


def _prof(cols, rows=100, dup=0.0):
    return {"dataset": {"row_count": rows, "duplicate_row_pct": dup, "schema_fingerprint": "x"}, "columns": cols}


def test_schema_diff_added_removed_type_change():
    base = _schema(("a", "numeric"), ("b", "categorical"), ("c", "numeric"))
    tgt = _schema(("a", "categorical"), ("b", "categorical"), ("d", "text"))
    res = compare_versions(base, tgt, _prof({}), _prof({}))
    kinds = {(c["kind"], c["column"]) for c in res["changes"]}
    assert ("type_changed", "a") in kinds and ("column_removed", "c") in kinds and ("column_added", "d") in kinds
    assert res["summary"]["overall_severity"] == "critical"


def test_rename_candidate_requires_confirmation():
    base = _schema(("id", "text"), ("amount", "numeric"))
    tgt = _schema(("id", "text"), ("txn_amount", "numeric"))
    p1 = _prof({"amount": {"mean": 50, "std": 10, "missing_pct": 0}})
    p2 = _prof({"txn_amount": {"mean": 51, "std": 10, "missing_pct": 0}})
    res = compare_versions(base, tgt, p1, p2)
    cand = res["rename_candidates"][0]
    assert cand["from"] == "amount" and cand["to"] == "txn_amount" and cand["confidence"] > 0.7
    assert any(c["kind"] == "column_removed" for c in res["changes"])  # not auto-applied
    confirmed = compare_versions(base, tgt, p1, p2, confirmed_renames={"amount": "txn_amount"})
    assert {c["kind"] for c in confirmed["changes"]} == {"column_renamed"}


def test_no_rename_candidate_across_types():
    res = compare_versions(_schema(("a", "numeric")), _schema(("a2", "text")), _prof({}), _prof({}))
    assert res["rename_candidates"] == []


def test_null_category_rowcount_duplicate_changes_and_policy():
    base = _schema(("s", "categorical"))
    p1 = _prof({"s": {"missing_pct": 0, "frequencies": {"a": 50, "b": 50}}}, rows=100, dup=0)
    p2 = _prof({"s": {"missing_pct": 30, "frequencies": {"a": 30, "c": 40}}}, rows=200, dup=5)
    res = compare_versions(base, base, p1, p2, DiffConfig(policy={"category_added": "critical"}))
    kinds = {c["kind"]: c for c in res["changes"]}
    assert kinds["null_pct_increase_large"]["severity"] == "critical"
    assert kinds["category_added"]["values"] == ["c"] and kinds["category_added"]["severity"] == "critical"
    assert kinds["category_removed"]["values"] == ["b"]
    assert "row_count_change" in kinds and "duplicate_increase" in kinds


# ---------------------------------------------------------------- lineage


def _graph():
    nodes = [Node(1, "dataset", "raw"), Node(2, "transformation", "clean"), Node(3, "feature_table", "features"),
             Node(4, "model", "churn", "high"), Node(5, "report", "exec dashboard", "critical"), Node(6, "report", "other")]
    edges = [Edge(1, 1, 2, "confirmed"), Edge(2, 2, 3, "confirmed"), Edge(3, 3, 4, "confirmed"),
             Edge(4, 4, 5, "declared"), Edge(5, 2, 6, "inferred")]
    return Graph(nodes, edges)


def test_downstream_traversal_and_confirmed_paths():
    g = _graph()
    down = g.downstream(1)
    assert set(down) == {2, 3, 4, 5, 6}
    assert down[4]["path"] == [1, 2, 3, 4] and down[4]["confirmed"]
    assert not down[5]["confirmed"] and not down[6]["confirmed"]
    assert set(g.upstream(5)) == {1, 2, 3, 4}


def test_impact_counts():
    res = impact_of(_graph(), [1])
    c = res["counts"]
    assert c["total"] == 5 and c["models"] == 1 and c["reports"] == 2 and c["confirmed"] == 3 and c["potential"] == 2


def test_cycle_detection():
    g = Graph([Node(1, "dataset", "a"), Node(2, "transformation", "b"), Node(3, "dataset", "c")],
              [Edge(1, 1, 2), Edge(2, 2, 3), Edge(3, 3, 1)])
    cycles = g.find_cycles()
    assert len(cycles) == 1 and sorted(cycles[0]) == [1, 2, 3]
    assert not g.validate()["valid"]
    assert _graph().would_create_cycle(4, 1) and not _graph().would_create_cycle(1, 6)


def test_validation_flags_missing_upstream():
    g = Graph([Node(1, "model", "m")], [])
    kinds = {i["kind"] for i in g.validate()["issues"]}
    assert "missing_upstream" in kinds and "isolated" in kinds


def test_priority_increases_with_impact():
    g = _graph()
    none = impact.priority("warning", "medium", {"affected": []})
    some = impact.priority("warning", "medium", impact_of(g, [1]))
    assert some["score"] > none["score"]
    assert impact.priority("critical", "critical", impact_of(g, [1]))["urgency"] == "P1"


def test_consequences_and_steps_mention_models():
    imp = impact_of(_graph(), [1])
    cons = impact.consequences([{"kind": "drift"}], imp)
    assert any("churn" in c and "does not by itself prove" in c for c in cons)
    assert impact.investigation_steps([{"kind": "freshness"}], imp)


def test_cost_estimate_only_when_configured():
    imp = impact_of(_graph(), [1])
    assert impact.cost_estimate(imp, {}, 4) is None
    est = impact.cost_estimate(imp, {5: 100.0}, 4)
    assert est["estimated_cost"] == 400 and "User-configured" in est["label"]


# ---------------------------------------------------------------- model metrics


def test_classification_metrics_with_partial_labels():
    y_true = [1, 0, None, 1, 0, None]
    y_pred = [1, 0, 1, 0, 0, 1]
    score = [0.9, 0.1, 0.8, 0.4, 0.2, 0.7]
    m = classification_metrics(y_true, y_pred, score, positive_label=1)
    assert m["n_labelled"] == 4 and m["label_coverage"] == pytest.approx(4 / 6, rel=1e-4)
    assert m["accuracy"] == 0.75 and m["precision"] == 1.0 and m["recall"] == 0.5
    assert m["roc_auc"] == 1.0 and m["confusion_matrix"] == [[2, 0], [1, 1]]


def test_classification_no_labels_and_no_auc_without_scores():
    assert classification_metrics([None, None], [1, 0])["status"] == "no_labels"
    m = classification_metrics([1, 0], [1, 1])
    assert m["roc_auc"] is None and "no prediction scores" in m["roc_auc_note"]


def test_multiclass_uses_macro():
    m = classification_metrics(["a", "b", "c"], ["a", "b", "b"])
    assert m["averaging"] == "macro" and m["roc_auc"] is None


def test_regression_metrics():
    m = regression_metrics([1.0, 2.0, 3.0, None], [1.5, 2.0, 2.0, 9.0])
    assert m["mae"] == pytest.approx(0.5) and m["rmse"] == pytest.approx(np.sqrt((0.25 + 0 + 1) / 3))
    assert m["r2"] == pytest.approx(1 - 1.25 / 2.0)
    assert regression_metrics([1.0], [1.0])["r2"] is None


def test_degradation_flags_use_confidence_interval():
    base = {"f1": 0.8}
    cls = {"status": "ok", "task": "classification"}
    assert compare_performance(base, {**cls, "f1": 0.7, "f1_ci95": [0.66, 0.71]})["severity"] == "critical"
    assert compare_performance(base, {**cls, "f1": 0.74, "f1_ci95": [0.70, 0.755]})["severity"] == "warning"
    noisy = compare_performance(base, {**cls, "f1": 0.7, "f1_ci95": [0.55, 0.82]})
    assert noisy["status"] == "inconclusive" and noisy["severity"] == "none"
    assert compare_performance(base, {**cls, "f1": 0.7})["status"] == "inconclusive"  # too few labels for a CI
    assert compare_performance(base, {**cls, "f1": 0.79, "f1_ci95": [0.75, 0.83]})["status"] == "ok"
    assert compare_performance(base, {"status": "no_labels"})["status"] == "unknown"
    rmse = compare_performance({"rmse": 1.0}, {"status": "ok", "task": "regression", "rmse": 1.5, "rmse_ci95": [1.3, 1.7]})
    assert rmse["severity"] == "critical"


def test_bootstrap_ci_contains_point_estimate():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 500)
    p = np.where(rng.random(500) < 0.8, y, 1 - y)
    m = classification_metrics(y.tolist(), p.tolist())
    lo, hi = m["f1_ci95"]
    assert lo <= m["f1"] <= hi and hi - lo < 0.15


# ---------------------------------------------------------------- remediation


def test_allowlist_rejects_risky_actions():
    assert validate_allowlist(["quarantine_version"]) == ["quarantine_version"]
    with pytest.raises(ValueError):
        validate_allowlist(["apply_missing_value_policy"])


def test_execution_mode():
    assert execution_mode("quarantine_version", "auto", ["quarantine_version"]) == "auto"
    assert execution_mode("restore_last_known_good", "auto", ["restore_last_known_good"]) == "approval"
    assert execution_mode("quarantine_version", "recommend", ["quarantine_version"]) == "recommend"
    assert execution_mode("quarantine_version", "approval", ["quarantine_version"]) == "approval"


def test_recommendations():
    findings = [{"id": "F1", "kind": "column_removed", "column": "a", "severity": "critical"},
                {"id": "F2", "kind": "not_null", "column": "s", "severity": "warning"}]
    recs = recommend(findings, version_is_active=True, has_last_known_good=True,
                     remediation_policy={"missing_value_policies": {"s": {"strategy": "mode"}}})
    actions = [r["action"] for r in recs]
    assert "reject_version" in actions and "restore_last_known_good" in actions
    assert "apply_missing_value_policy" in actions and actions[-1] == "notify_operator"
    assert recommend([], version_is_active=False, has_last_known_good=False, ingestion_failed=True)[0]["action"] == "retry_ingestion"


def test_type_conversion_preconditions():
    df = pd.DataFrame({"x": pd.array(["1", "2", "x"], dtype="string")})
    with pytest.raises(RemediationRefused):
        type_conversion(df, "x", "numeric", max_failure_pct=1)
    out, rep = type_conversion(df, "x", "numeric", max_failure_pct=50)
    assert rep["coercion_failures"] == 1 and out["x"].isna().sum() == 1
    assert df["x"].tolist() == ["1", "2", "x"]  # original untouched


def test_missing_value_policy_limits_and_strategies():
    df = pd.DataFrame({"v": [1.0, None, 3.0, 4.0, 5.0], "c": ["a", "a", None, "b", "a"]})
    out, rep = missing_value_policy(df, "v", "median", max_affected_pct=25)
    assert out["v"].tolist() == [1.0, 3.5, 3.0, 4.0, 5.0] and rep["rows_affected"] == 1
    out, _ = missing_value_policy(df, "c", "mode", max_affected_pct=25)
    assert out["c"].tolist() == ["a", "a", "a", "b", "a"]
    with pytest.raises(RemediationRefused):
        missing_value_policy(df, "v", "median", max_affected_pct=10)
    with pytest.raises(RemediationRefused):
        missing_value_policy(df, "c", "mean", max_affected_pct=50)
    out, rep = missing_value_policy(df, "v", "drop_rows", max_affected_pct=25)
    assert len(out) == 4 and rep["rows_after"] == 4


def test_client_ip_ignores_forwarded_for_unless_proxies_are_trusted(monkeypatch):
    from types import SimpleNamespace

    from app.core import config
    from app.core.ratelimit import client_ip

    req = SimpleNamespace(headers={"x-forwarded-for": "6.6.6.6, 203.0.113.9"}, client=SimpleNamespace(host="10.0.0.2"))
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")
    config.get_settings.cache_clear()
    assert client_ip(req) == "10.0.0.2"
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    config.get_settings.cache_clear()
    assert client_ip(req) == "203.0.113.9"
    config.get_settings.cache_clear()
