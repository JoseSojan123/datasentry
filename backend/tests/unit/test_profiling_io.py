from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from datasentry_core.io import (
    IngestionError,
    SemanticType,
    detect_format,
    infer_schema,
    infer_semantic_type,
    load_and_normalize,
    safe_filename,
    schema_fingerprint,
    validate_column_names,
)
from datasentry_core.profiling import ProfileConfig, profile_dataframe


def write(tmp_path: Path, text: str, name="f.csv", encoding="utf-8") -> Path:
    p = tmp_path / name
    p.write_bytes(text.encode(encoding))
    return p


def test_type_inference():
    assert infer_semantic_type(pd.Series(["1", "2.5", None])) == SemanticType.NUMERIC
    assert infer_semantic_type(pd.Series(["true", "No", "yes"])) == SemanticType.BOOLEAN
    assert infer_semantic_type(pd.Series(["2024-01-01", "2024-02-01 10:00"])) == SemanticType.DATETIME
    assert infer_semantic_type(pd.Series(["a", "b", "a"])) == SemanticType.CATEGORICAL
    assert infer_semantic_type(pd.Series([f"free text {i}" for i in range(500)])) == SemanticType.TEXT
    assert infer_semantic_type(pd.Series(["1", "x"])) == SemanticType.CATEGORICAL


def test_load_csv_counts_malformed_rows(tmp_path):
    p = write(tmp_path, "a,b\n1,x\n2,y,extra\n3,z\n")
    df, schema, report = load_and_normalize(p, "csv")
    assert len(df) == 2 and report.malformed_rows == 1
    assert [c.semantic_type for c in schema] == [SemanticType.NUMERIC, SemanticType.CATEGORICAL]


def test_rejects_non_utf8_but_accepts_declared_latin1(tmp_path):
    p = write(tmp_path, "name\ncafé\n", encoding="latin-1")
    with pytest.raises(IngestionError) as e:
        load_and_normalize(p, "csv")
    assert e.value.code == "bad_encoding"
    df, _, _ = load_and_normalize(p, "csv", encoding="latin-1")
    assert df["name"][0] == "café"


def test_column_name_validation():
    with pytest.raises(IngestionError):
        validate_column_names(["a", "A"])
    with pytest.raises(IngestionError):
        validate_column_names(["a", ""])
    assert validate_column_names([" a ", "﻿b"]) == ["a", "b"]


def test_row_limit(tmp_path):
    p = write(tmp_path, "a\n" + "\n".join(str(i) for i in range(20)) + "\n")
    with pytest.raises(IngestionError) as e:
        load_and_normalize(p, "csv", max_rows=10)
    assert e.value.code == "too_many_rows"


def test_detect_format_and_safe_filename():
    assert detect_format("X.CSV") == "csv" and detect_format("a.parquet") == "parquet"
    with pytest.raises(IngestionError):
        detect_format("evil.exe")
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("..\\..\\a b.csv") == "a_b.csv"


def test_parquet_roundtrip(tmp_path):
    df = pd.DataFrame({"x": [1.5, 2.5], "flag": [True, False], "t": pd.to_datetime(["2026-01-01", "2026-01-02"])})
    p = tmp_path / "f.parquet"
    df.to_parquet(p)
    out, schema, _ = load_and_normalize(p, "parquet")
    assert [c.semantic_type.value for c in schema] == ["numeric", "boolean", "datetime"]


def test_fingerprint_depends_on_names_and_types():
    a = infer_schema(pd.DataFrame({"x": [1], "y": ["a"]}))
    b = infer_schema(pd.DataFrame({"x": [1], "y": [2]}))
    assert schema_fingerprint(a) != schema_fingerprint(b)
    assert schema_fingerprint(a) == schema_fingerprint(infer_schema(pd.DataFrame({"x": [3], "y": ["b"]})))


@pytest.fixture
def frame():
    raw = pd.DataFrame({
        "id": ["1", "2", "3", "3", "5", "6"],
        "v": ["1", "2", "3", "3", None, "100"],
        "c": ["a", "a", "b", "b", "a", "z"],
        "t": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-03", "2026-01-09", "2026-01-10"],
    })
    df, schema, _ = (None, None, None)
    from datasentry_core.io import normalize_frame

    schema = infer_schema(raw)
    return normalize_frame(raw, schema), schema


def test_profile_numeric_and_outliers(frame):
    df, schema = frame
    prof = profile_dataframe(df, schema, ProfileConfig(), datetime(2026, 1, 11))
    v = prof["columns"]["v"]
    assert v["missing_count"] == 1 and v["missing_pct"] == pytest.approx(100 / 6, rel=1e-3)
    assert v["median"] == 3 and v["mean"] == pytest.approx(21.8)
    # Q1=2, Q3=3 -> IQR=1 -> fences [0.5, 4.5] -> 100 is the only outlier
    assert v["outlier_count"] == 1 and v["outlier_fences"] == [0.5, 4.5]


def test_profile_categorical_rare(frame):
    df, schema = frame
    prof = profile_dataframe(df, schema, ProfileConfig(rare_threshold=0.2), datetime(2026, 1, 11), {"c": {"a", "b"}})
    c = prof["columns"]["c"]
    assert c["top_values"][0] == {"value": "a", "count": 3, "frequency": 0.5}
    assert c["rare_categories"] == ["z"] and c["unexpected_categories"] == ["z"]


def test_profile_datetime_gaps_and_freshness(frame):
    df, schema = frame
    prof = profile_dataframe(df, schema, ProfileConfig(), datetime(2026, 1, 11))
    t = prof["columns"]["t"]
    assert t["duplicate_timestamps"] == 1
    assert t["expected_interval_seconds"] == 86400 and t["gap_count"] == 1
    assert t["largest_gap_seconds"] == 6 * 86400
    assert t["freshness_seconds"] == 86400
    assert prof["dataset"]["freshness_seconds"] == 86400


def test_profile_dataset_level(frame):
    df, schema = frame
    prof = profile_dataframe(df, schema, ProfileConfig(primary_key=["id"]), datetime(2026, 1, 11))
    d = prof["dataset"]
    assert d["row_count"] == 6 and d["duplicate_row_count"] == 1 and d["duplicate_key_count"] == 1
    assert d["missing_cell_count"] == 1


def test_profile_reproducible(frame):
    df, schema = frame
    a = profile_dataframe(df, schema, as_of=datetime(2026, 1, 11))
    b = profile_dataframe(df, schema, as_of=datetime(2026, 1, 11))
    a["dataset"].pop("profiling_duration_ms")
    b["dataset"].pop("profiling_duration_ms")
    assert a == b


def test_profile_handles_all_null_column():
    df = pd.DataFrame({"x": pd.Series([np.nan, np.nan], dtype="float64")})
    schema = infer_schema(df)
    prof = profile_dataframe(df, schema)
    assert prof["columns"]["x"]["missing_pct"] == 100.0
