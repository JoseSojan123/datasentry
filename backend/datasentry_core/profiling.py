"""Reproducible dataset profiling.

Methodology (also documented in docs/methodology.md):

* Missing values: a cell is missing when it is null/NaN (blank CSV fields become null at ingestion).
* Outliers: Tukey's fences. A value is an outlier when it is below Q1 - k*IQR or above Q3 + k*IQR
  with k = 1.5 by default. Quartiles use linear interpolation (numpy default).
* Duplicate rows: number of rows that are exact repeats of an earlier row across all columns
  (n_rows - n_distinct_rows). Duplicate keys use the same definition over the configured key columns.
* Rare categories: categories whose relative frequency among non-null values is below
  ``rare_threshold`` (default 1%).
* Datetime gaps: the expected interval is the median difference between consecutive distinct
  timestamps; a gap is any consecutive difference larger than ``gap_factor`` (default 1.5) times
  the expected interval.
* Freshness: ``as_of - max(timestamp)`` of the configured freshness column (or the first datetime
  column when none is configured), in seconds.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import numpy as np
import pandas as pd

from .io import ColumnSchema, SemanticType, schema_fingerprint


@dataclass
class ProfileConfig:
    outlier_k: float = 1.5
    rare_threshold: float = 0.01
    top_k: int = 10
    histogram_bins: int = 20
    gap_factor: float = 1.5
    primary_key: list[str] | None = None
    freshness_column: str | None = None


def numeric_values(series: pd.Series) -> np.ndarray:
    """Finite float values of a numeric column, nulls removed."""
    arr = pd.to_numeric(series, errors="coerce").to_numpy(dtype="float64", na_value=np.nan)
    return arr[np.isfinite(arr)]


def _f(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def histogram(values: np.ndarray, bins: int = 20, edges: np.ndarray | None = None) -> dict[str, list[float]]:
    if values.size == 0:
        return {"edges": [], "counts": []}
    if edges is None:
        lo, hi = float(values.min()), float(values.max())
        if lo == hi:
            lo, hi = lo - 0.5, hi + 0.5
        edges = np.linspace(lo, hi, bins + 1)
    counts, edges = np.histogram(np.clip(values, edges[0], edges[-1]), bins=edges)
    return {"edges": [float(e) for e in edges], "counts": [int(c) for c in counts]}


def profile_numeric(series: pd.Series, cfg: ProfileConfig) -> dict[str, Any]:
    values = numeric_values(series)
    out: dict[str, Any] = {}
    if values.size == 0:
        return {"mean": None, "median": None, "std": None, "min": None, "max": None, "q1": None, "q3": None,
                "outlier_count": 0, "outlier_pct": 0.0, "histogram": {"edges": [], "counts": []}}
    q1, med, q3 = np.percentile(values, [25, 50, 75])
    iqr = q3 - q1
    lo_fence, hi_fence = q1 - cfg.outlier_k * iqr, q3 + cfg.outlier_k * iqr
    outliers = int(((values < lo_fence) | (values > hi_fence)).sum())
    out.update(
        mean=_f(values.mean()),
        median=_f(med),
        std=_f(values.std(ddof=1)) if values.size > 1 else 0.0,
        min=_f(values.min()),
        max=_f(values.max()),
        q1=_f(q1),
        q3=_f(q3),
        p05=_f(np.percentile(values, 5)),
        p95=_f(np.percentile(values, 95)),
        iqr=_f(iqr),
        outlier_method=f"tukey_iqr_k{cfg.outlier_k}",
        outlier_fences=[_f(lo_fence), _f(hi_fence)],
        outlier_count=outliers,
        outlier_pct=round(100 * outliers / values.size, 4),
        zero_count=int((values == 0).sum()),
        negative_count=int((values < 0).sum()),
        skewness=_f(pd.Series(values).skew()) if values.size > 2 else None,
        histogram=histogram(values, cfg.histogram_bins),
    )
    return out


def profile_categorical(
    series: pd.Series, cfg: ProfileConfig, reference_categories: set[str] | None = None
) -> dict[str, Any]:
    values = series.dropna().astype(str)
    n = len(values)
    counts = values.value_counts()
    freqs = (counts / n) if n else counts.astype(float)
    rare = [str(k) for k, f in freqs.items() if f < cfg.rare_threshold]
    out: dict[str, Any] = {
        "distinct_count": int(counts.size),
        "top_values": [
            {"value": str(k), "count": int(c), "frequency": round(float(c) / n, 6)}
            for k, c in counts.head(cfg.top_k).items()
        ],
        "frequencies": {str(k): int(c) for k, c in counts.head(200).items()},
        "frequencies_truncated": bool(counts.size > 200),
        "rare_threshold": cfg.rare_threshold,
        "rare_categories": rare[:50],
        "rare_category_count": len(rare),
    }
    if reference_categories is not None:
        unexpected = sorted(set(counts.index.astype(str)) - reference_categories)
        out["unexpected_categories"] = unexpected[:50]
        out["unexpected_category_count"] = len(unexpected)
        out["unexpected_row_count"] = int(values.isin(unexpected).sum())
    return out


def profile_text(series: pd.Series, cfg: ProfileConfig) -> dict[str, Any]:
    values = series.dropna().astype(str)
    lengths = values.str.len()
    return {
        "distinct_count": int(values.nunique()),
        "min_length": int(lengths.min()) if len(values) else None,
        "max_length": int(lengths.max()) if len(values) else None,
        "mean_length": _f(lengths.mean()) if len(values) else None,
        "empty_string_count": int((values.str.strip() == "").sum()),
        "top_values": [
            {"value": str(k)[:120], "count": int(c), "frequency": round(float(c) / len(values), 6)}
            for k, c in values.value_counts().head(5).items()
        ]
        if len(values)
        else [],
    }


def profile_datetime(series: pd.Series, cfg: ProfileConfig, as_of: datetime) -> dict[str, Any]:
    values = pd.to_datetime(series, errors="coerce").dropna()
    if values.empty:
        return {"min": None, "max": None, "coverage_days": 0, "duplicate_timestamps": 0, "gap_count": 0}
    vmin, vmax = values.min(), values.max()
    distinct = values.drop_duplicates().sort_values()
    diffs = distinct.diff().dropna().dt.total_seconds()
    expected = float(diffs.median()) if len(diffs) else None
    gaps = diffs[diffs > cfg.gap_factor * expected] if expected else diffs.iloc[0:0]
    as_of_naive = pd.Timestamp(as_of).tz_localize(None) if pd.Timestamp(as_of).tzinfo else pd.Timestamp(as_of)
    return {
        "min": vmin.isoformat(),
        "max": vmax.isoformat(),
        "coverage_days": round((vmax - vmin).total_seconds() / 86400, 4),
        "distinct_timestamps": int(distinct.size),
        "duplicate_timestamps": int(len(values) - distinct.size),
        "expected_interval_seconds": expected,
        "gap_factor": cfg.gap_factor,
        "gap_count": int(len(gaps)),
        "largest_gap_seconds": _f(gaps.max()) if len(gaps) else None,
        "freshness_seconds": _f((as_of_naive - vmax).total_seconds()),
        "by_day": {str(pd.Timestamp(cast(Any, k)).date()): int(v) for k, v in values.dt.floor("D").value_counts().sort_index().tail(120).items()},
    }


def profile_dataframe(
    df: pd.DataFrame,
    schema: list[ColumnSchema],
    cfg: ProfileConfig | None = None,
    as_of: datetime | None = None,
    reference_categories: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """Compute a full profile. Deterministic for a given (df, schema, cfg, as_of)."""
    cfg = cfg or ProfileConfig()
    as_of = as_of or datetime.now(UTC)
    started = time.perf_counter()
    n_rows, n_cols = df.shape
    columns: dict[str, Any] = {}
    for col in schema:
        s = df[col.name]
        missing = int(s.isna().sum())
        base: dict[str, Any] = {
            "name": col.name,
            "semantic_type": col.semantic_type.value,
            "count": int(n_rows - missing),
            "missing_count": missing,
            "missing_pct": round(100 * missing / n_rows, 4) if n_rows else 0.0,
            "distinct_count": int(s.nunique(dropna=True)),
        }
        if col.semantic_type == SemanticType.NUMERIC:
            base.update(profile_numeric(s, cfg))
        elif col.semantic_type in (SemanticType.CATEGORICAL, SemanticType.BOOLEAN):
            ref = (reference_categories or {}).get(col.name)
            base.update(profile_categorical(s, cfg, ref))
        elif col.semantic_type == SemanticType.DATETIME:
            base.update(profile_datetime(s, cfg, as_of))
        else:
            base.update(profile_text(s, cfg))
        base["is_constant"] = base["distinct_count"] <= 1
        columns[col.name] = base

    duplicate_rows = int(n_rows - len(df.drop_duplicates())) if n_rows else 0
    dataset: dict[str, Any] = {
        "row_count": int(n_rows),
        "column_count": int(n_cols),
        "duplicate_row_count": duplicate_rows,
        "duplicate_row_pct": round(100 * duplicate_rows / n_rows, 4) if n_rows else 0.0,
        "missing_cell_count": int(df.isna().sum().sum()),
        "missing_cell_pct": round(100 * float(df.isna().sum().sum()) / (n_rows * n_cols), 4) if n_rows and n_cols else 0.0,
        "schema_fingerprint": schema_fingerprint(schema),
        "as_of": as_of.isoformat(),
    }
    if cfg.primary_key:
        key = [k for k in cfg.primary_key if k in df.columns]
        if key:
            dup_keys = int(n_rows - len(df[key].drop_duplicates()))
            dataset["primary_key"] = key
            dataset["duplicate_key_count"] = dup_keys
            dataset["null_key_count"] = int(df[key].isna().any(axis=1).sum())
    fresh_col = cfg.freshness_column or next(
        (c.name for c in schema if c.semantic_type == SemanticType.DATETIME), None
    )
    if fresh_col and fresh_col in columns and columns[fresh_col].get("freshness_seconds") is not None:
        dataset["freshness_column"] = fresh_col
        dataset["freshness_seconds"] = columns[fresh_col]["freshness_seconds"]
        dataset["latest_record_at"] = columns[fresh_col]["max"]
    dataset["profiling_duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return {"dataset": dataset, "columns": columns, "config": cfg.__dict__}
