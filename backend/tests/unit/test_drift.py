import numpy as np
import pandas as pd
import pytest

from datasentry_core.drift import (
    DriftConfig,
    adjust_pvalues,
    chi_square_homogeneity,
    evaluate_drift,
    js_distance,
    psi_from_counts,
    psi_numeric,
    slice_window,
)


def test_psi_identical_is_zero():
    x = np.random.default_rng(0).normal(size=5000)
    psi, _ = psi_numeric(x, x.copy())
    assert psi == pytest.approx(0.0, abs=1e-12)


def test_psi_known_value():
    # Hand-computed: ref = [0.5, 0.5], cur = [0.25, 0.75]  (no smoothing effect with huge counts)
    ref = np.array([50000.0, 50000.0])
    cur = np.array([25000.0, 75000.0])
    expected = (0.25 - 0.5) * np.log(0.25 / 0.5) + (0.75 - 0.5) * np.log(0.75 / 0.5)
    assert psi_from_counts(ref, cur, smoothing=1e-9) == pytest.approx(expected, rel=1e-6)


def test_psi_smoothing_handles_empty_bins():
    assert np.isfinite(psi_from_counts(np.array([10.0, 0.0]), np.array([0.0, 10.0])))


def test_psi_constant_reference():
    psi, bins = psi_numeric(np.ones(100), np.ones(100))
    assert psi == pytest.approx(0.0) and bins["interior_edges"] == [1.0]


def test_js_distance_bounds():
    assert js_distance(np.array([10.0, 10.0]), np.array([10.0, 10.0])) == pytest.approx(0.0)
    assert 0.9 < js_distance(np.array([1e6, 0.0]), np.array([0.0, 1e6]), smoothing=1e-9) <= 1.0


def test_bh_adjustment_matches_reference():
    # Reference values computed with statsmodels.multipletests(method="fdr_bh")
    p = [0.01, 0.04, 0.03, 0.005]
    adj = adjust_pvalues(p, "benjamini_hochberg")
    assert adj == pytest.approx([0.02, 0.04, 0.04, 0.02])
    assert adjust_pvalues([0.01, None, 0.02], "bonferroni") == pytest.approx([0.02, None, 0.04])


def test_chi_square_pools_rare_categories():
    res = chi_square_homogeneity({"a": 500, "b": 480, "c": 2}, {"a": 300, "b": 690, "c": 1})
    assert res["valid"] and "c" in res["pooled"] and res["p_value"] < 1e-6


def test_chi_square_invalid_when_single_category():
    assert not chi_square_homogeneity({"a": 10}, {"a": 12})["valid"]


def _frames(seed=0, n=2000, shift=0.0):
    rng = np.random.default_rng(seed)
    ref = pd.DataFrame({"x": rng.normal(0, 1, n), "c": rng.choice(["a", "b", "c"], n, p=[0.5, 0.3, 0.2])})
    rng2 = np.random.default_rng(seed + 1)
    cur = pd.DataFrame({"x": rng2.normal(shift, 1, n), "c": rng2.choice(["a", "b", "c"], n, p=[0.5, 0.3, 0.2])})
    return ref, cur


TYPES = {"x": "numeric", "c": "categorical"}


def test_no_drift_on_same_distribution():
    ref, cur = _frames()
    res = evaluate_drift(ref, cur, TYPES)
    assert res["summary"]["features_drifted"] == 0
    assert all(f["status"] == "no_drift" for f in res["features"])


def test_numeric_drift_detected_with_evidence():
    ref, cur = _frames(shift=1.0)
    res = evaluate_drift(ref, cur, TYPES)
    x = next(f for f in res["features"] if f["feature"] == "x")
    assert x["status"] == "drift" and x["severity"] == "critical"
    assert x["statistics"]["psi"] > 0.25 and x["statistics"]["p_value_adjusted"] < 0.05
    assert x["statistics"]["standardized_mean_difference"] == pytest.approx(1.0, abs=0.1)
    assert sum(x["evidence"]["histogram"]["reference"]) == 2000


def test_significant_but_small_effect_is_not_drift():
    rng = np.random.default_rng(3)
    n = 200_000
    ref = pd.DataFrame({"x": rng.normal(0, 1, n)})
    cur = pd.DataFrame({"x": rng.normal(0.03, 1, n)})
    f = evaluate_drift(ref, cur, {"x": "numeric"})["features"][0]
    assert f["significant"] is True and f["status"] == "no_drift" and f["severity"] == "info"


def test_small_samples_are_insufficient():
    ref, cur = _frames(n=10)
    res = evaluate_drift(ref, cur, TYPES)
    assert all(f["status"] == "insufficient_data" for f in res["features"])


def test_large_effect_small_sample_is_inconclusive():
    ref = pd.DataFrame({"c": ["a"] * 20 + ["b"] * 15})
    cur = pd.DataFrame({"c": ["a"] * 14 + ["b"] * 21})
    f = evaluate_drift(ref, cur, {"c": "categorical"}, config=DriftConfig(min_samples=30))["features"][0]
    assert f["status"] in ("inconclusive", "no_drift")
    assert f["status"] != "drift"


def test_categorical_new_categories_reported():
    ref, cur = _frames()
    cur.loc[:399, "c"] = "zz"
    f = next(f for f in evaluate_drift(ref, cur, TYPES)["features"] if f["feature"] == "c")
    assert f["status"] == "drift" and "zz" in f["statistics"]["new_categories"]


def test_missingness_and_schema_findings():
    ref, cur = _frames()
    cur.loc[:799, "x"] = np.nan
    cur["extra"] = 1
    res = evaluate_drift(ref, cur.drop(columns=["c"]), TYPES)
    kinds = {o["kind"] for o in res["other_findings"]}
    assert {"missingness_increase", "column_removed", "column_added"} <= kinds


def test_type_change_skips_comparison():
    ref, cur = _frames()
    res = evaluate_drift(ref, cur, TYPES, {"x": "categorical", "c": "categorical"})
    assert any(o["kind"] == "type_change" for o in res["other_findings"])
    assert all(f["feature"] != "x" for f in res["features"])


def test_empty_and_constant_columns():
    ref = pd.DataFrame({"x": [np.nan] * 50, "k": [1.0] * 50})
    cur = pd.DataFrame({"x": [np.nan] * 50, "k": [1.0] * 50})
    res = evaluate_drift(ref, cur, {"x": "numeric", "k": "numeric"})
    by = {f["feature"]: f for f in res["features"]}
    assert by["x"]["status"] == "insufficient_data"
    assert by["k"]["status"] == "no_drift"


def test_deterministic():
    ref, cur = _frames(shift=0.3)
    assert evaluate_drift(ref, cur, TYPES)["features"] == evaluate_drift(ref, cur, TYPES)["features"]


def test_config_validation():
    with pytest.raises(ValueError):
        DriftConfig.from_dict({"psi_warning": 0.5, "psi_critical": 0.1})
    with pytest.raises(ValueError):
        DriftConfig.from_dict({"alpha": 2})


def test_slice_window():
    df = pd.DataFrame({"t": pd.date_range("2026-01-01", periods=10, freq="D"), "v": range(10)})
    assert len(slice_window(df, "t", "2026-01-03", "2026-01-06")) == 3
