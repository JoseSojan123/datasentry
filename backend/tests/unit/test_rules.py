from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from datasentry_core.rules import RuleContext, run_rule, summarize, validate_rule


@pytest.fixture
def df() -> pd.DataFrame:
    return pd.DataFrame({
        "id": pd.array([1, 2, 3, 4, 4], dtype="Int64"),
        "amount": [10.0, 20.0, np.nan, 500.0, -1.0],
        "cur": pd.array(["USD", "EUR", "USD", "JPY", None], dtype="string"),
        "email": pd.array(["a@x.com", "bad", "c@y.org", None, "d@z.io"], dtype="string"),
        "ts": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"]),
        "discount": [1.0, 25.0, 0.0, 5.0, 0.0],
    })


def test_not_null(df):
    r = run_rule(df, "not_null", ["amount"], {})
    assert r.status == "fail" and r.failed_rows == 1 and r.rows_evaluated == 5 and r.failure_pct == 20.0
    assert r.sample_failures[0]["row"] == 2
    assert run_rule(df, "not_null", ["id"], {}).status == "pass"


def test_not_null_tolerance(df):
    assert run_rule(df, "not_null", ["amount"], {"max_failure_pct": 25}).status == "pass"
    assert run_rule(df, "not_null", ["amount"], {"max_failure_pct": 10}).status == "fail"


def test_unique_counts_all_rows_in_duplicate_groups(df):
    r = run_rule(df, "unique", ["id"], {})
    assert r.status == "fail" and r.failed_rows == 2
    assert r.observed["duplicated_values"] == 1


def test_unique_ignores_null_keys():
    d = pd.DataFrame({"k": [None, None, 1.0]})
    r = run_rule(d, "unique", ["k"], {})
    assert r.status == "pass" and r.rows_evaluated == 1


def test_allowed_values_ignores_nulls(df):
    r = run_rule(df, "allowed_values", ["cur"], {"values": ["USD", "EUR"]})
    assert r.status == "fail" and r.failed_rows == 1 and r.rows_evaluated == 4
    assert r.observed["unexpected_values"] == {"JPY": 1}


def test_allowed_values_case_insensitive():
    d = pd.DataFrame({"c": ["usd", "USD"]})
    assert run_rule(d, "allowed_values", ["c"], {"values": ["USD"], "case_sensitive": False}).status == "pass"


def test_range(df):
    r = run_rule(df, "range", ["amount"], {"min": 0, "max": 100})
    assert r.failed_rows == 2 and r.observed["below"] == 1 and r.observed["above"] == 1
    assert r.rows_evaluated == 4


def test_range_exclusive_bounds():
    d = pd.DataFrame({"x": [0.0, 1.0, 2.0]})
    assert run_rule(d, "range", ["x"], {"min": 0, "max": 2}).status == "pass"
    assert run_rule(d, "range", ["x"], {"min": 0, "max": 2, "inclusive": False}).failed_rows == 2


def test_range_on_non_numeric_column_errors(df):
    r = run_rule(df, "range", ["cur"], {"min": 0}, RuleContext(semantic_types={"cur": "categorical"}))
    assert r.status == "error"


def test_regex(df):
    r = run_rule(df, "regex", ["email"], {"pattern": r"[^@]+@[^@]+\.[a-z]+"})
    assert r.status == "fail" and r.failed_rows == 1 and r.rows_evaluated == 4


@pytest.mark.parametrize("pattern", ["(a+)+", "(\\w*)*$", "(.)\\1", "(a|aa)+", "(x|y){2,}"])
def test_regex_rejects_dangerous_patterns(pattern):
    with pytest.raises(ValueError):
        validate_rule("regex", ["x"], {"pattern": pattern})


@pytest.mark.parametrize("pattern", ["(USD|EUR|GBP)", "[A-Z]{3}", r"[^@\s]+@[^@\s]+\.[a-z]{2,}"])
def test_regex_accepts_ordinary_patterns(pattern):
    validate_rule("regex", ["x"], {"pattern": pattern})


def test_referential_integrity(df):
    ctx = RuleContext(reference_values={9: {"code": {"USD", "EUR"}}})
    r = run_rule(df, "referential_integrity", ["cur"], {"reference_dataset_id": 9, "reference_column": "code"}, ctx)
    assert r.status == "fail" and r.failed_rows == 1
    r2 = run_rule(df, "referential_integrity", ["cur"], {"reference_dataset_id": 10, "reference_column": "code"}, ctx)
    assert r2.status == "error"


def test_freshness(df):
    ctx = RuleContext(as_of=datetime(2026, 1, 6))
    assert run_rule(df, "freshness", ["ts"], {"max_age_seconds": 2 * 86400}, ctx).status == "pass"
    r = run_rule(df, "freshness", ["ts"], {"max_age_seconds": 3600}, ctx)
    assert r.status == "fail" and r.observed["age_seconds"] == 86400 and r.scope == "dataset"


def test_row_count(df):
    assert run_rule(df, "row_count", [], {"min_rows": 5}).status == "pass"
    assert run_rule(df, "row_count", [], {"min_rows": 6}).status == "fail"


def test_duplicate_rows_excludes_first_occurrence():
    d = pd.DataFrame({"a": [1, 1, 1, 2], "b": ["x", "x", "x", "y"]})
    r = run_rule(d, "duplicate_rows", [], {})
    assert r.failed_rows == 2


def test_schema_rule(df):
    ctx = RuleContext(semantic_types={"id": "numeric", "cur": "categorical"})
    ok = run_rule(df, "schema", [], {"expected_columns": [{"name": "id", "semantic_type": "numeric"}]}, ctx)
    assert ok.status == "pass"
    bad = run_rule(df, "schema", [], {"expected_columns": [{"name": "id", "semantic_type": "text"}, {"name": "missing"}],
                                      "allow_extra_columns": False}, ctx)
    assert bad.status == "fail"
    assert bad.observed["missing"] == ["missing"] and bad.observed["type_mismatches"][0]["column"] == "id"


def test_expectation_column_vs_column(df):
    r = run_rule(df, "expectation", [], {"expect": {"column": "discount", "op": "le", "other_column": "amount"}})
    # row 1 (25 > 20) and row 4 (0 > -1) violate; row 2 has null amount -> comparison invalid -> counts as violation
    assert r.status == "fail" and r.failed_rows == 3


def test_expectation_with_when(df):
    cfg = {"when": {"column": "cur", "op": "eq", "value": "USD"}, "expect": {"column": "amount", "op": "not_null"}}
    r = run_rule(df, "expectation", [], cfg)
    assert r.rows_evaluated == 2 and r.failed_rows == 1


def test_expectation_rejects_unknown_keys():
    with pytest.raises(ValueError):
        validate_rule("expectation", [], {"expect": {"column": "a", "op": "eval", "value": "__import__('os')"}})


def test_missing_column_fails_not_errors(df):
    r = run_rule(df, "not_null", ["nope"], {})
    assert r.status == "fail" and r.observed["missing_columns"] == ["nope"]


def test_validate_rule_requires_columns():
    with pytest.raises(ValueError):
        validate_rule("not_null", [], {})
    with pytest.raises(ValueError):
        validate_rule("range", ["a"], {})
    with pytest.raises(ValueError):
        validate_rule("bogus", ["a"], {})


def test_summary(df):
    rules = [{"rule_type": "not_null", "columns": ["amount"], "severity": "critical"},
             {"rule_type": "not_null", "columns": ["id"], "severity": "warning"}]
    pairs = [(r, run_rule(df, r["rule_type"], r["columns"], {})) for r in rules]
    s = summarize(pairs)
    assert s["total"] == 2 and s["failed"] == 1 and s["failed_by_severity"] == {"critical": 1}
    assert s["by_column"]["amount"]["fail"] == 1
