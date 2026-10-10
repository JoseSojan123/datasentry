"""File validation, parsing and deterministic column type inference.

CSV files are parsed with DuckDB as all-VARCHAR so that type inference is fully
controlled (and reproducible) here rather than depending on reader heuristics.
Malformed rows are skipped by DuckDB and counted through its reject table.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

SUPPORTED_FORMATS = {"csv", "parquet"}
MAX_COLUMN_NAME_LENGTH = 128
_BOOL_TRUE = {"true", "t", "yes", "y"}
_BOOL_FALSE = {"false", "f", "no", "n"}
_DATE_HINT = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}|^\d{1,2}/\d{1,2}/\d{2,4}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class SemanticType(StrEnum):
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    TEXT = "text"


class IngestionError(ValueError):
    """Raised for files that cannot be accepted. The message is safe to show users."""

    def __init__(self, message: str, code: str = "invalid_file", details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass
class ColumnSchema:
    name: str
    position: int
    semantic_type: SemanticType
    physical_type: str
    nullable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "position": self.position,
            "semantic_type": self.semantic_type.value,
            "physical_type": self.physical_type,
            "nullable": self.nullable,
        }


@dataclass
class ParseReport:
    rows: int
    columns: int
    malformed_rows: int = 0
    encoding: str = "utf-8"
    warnings: list[str] = field(default_factory=list)


def detect_format(filename: str) -> str:
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix in {"csv", "txt"}:
        return "csv"
    if suffix in {"parquet", "pq"}:
        return "parquet"
    raise IngestionError(
        f"Unsupported file type '.{suffix}'. Upload a .csv or .parquet file.",
        code="unsupported_format",
    )


def safe_filename(filename: str) -> str:
    """Strip any directory components and unsafe characters from a client-supplied filename."""
    base = Path(filename.replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".")
    return base[:120] or "upload"


def file_checksum(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_utf8(path: Path, encoding: str = "utf-8") -> Path:
    """Validate the encoding of a CSV file, transcoding latin-1 input to UTF-8 when declared."""
    encoding = encoding.lower().replace("_", "-")
    if encoding not in {"utf-8", "latin-1", "iso-8859-1"}:
        raise IngestionError(f"Unsupported encoding '{encoding}'. Use utf-8 or latin-1.", code="bad_encoding")
    if encoding == "utf-8":
        decoder_ok = True
        with path.open("rb") as fh:
            import codecs

            dec = codecs.getincrementaldecoder("utf-8")()
            line = 1
            try:
                while chunk := fh.read(1 << 20):
                    text = dec.decode(chunk)
                    line += text.count("\n")
                dec.decode(b"", final=True)
            except UnicodeDecodeError:
                decoder_ok = False
        if not decoder_ok:
            raise IngestionError(
                f"File is not valid UTF-8 (first invalid byte near line {line}). "
                "Re-export as UTF-8 or upload with encoding=latin-1.",
                code="bad_encoding",
            )
        return path
    out = path.with_suffix(".utf8.csv")
    with path.open("r", encoding="latin-1") as src, out.open("w", encoding="utf-8") as dst:
        while text := src.read(1 << 20):
            dst.write(text)
    return out


def validate_column_names(names: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for i, raw in enumerate(names):
        name = str(raw).strip().lstrip("﻿")
        if not name or name.lower().startswith("unnamed:") or name == f"column{i}":
            raise IngestionError(f"Column {i + 1} has an empty header.", code="bad_header")
        if len(name) > MAX_COLUMN_NAME_LENGTH:
            raise IngestionError(
                f"Column name '{name[:40]}…' exceeds {MAX_COLUMN_NAME_LENGTH} characters.", code="bad_header"
            )
        if _CONTROL.search(name):
            raise IngestionError(f"Column {i + 1} name contains control characters.", code="bad_header")
        key = name.lower()
        if key in seen:
            raise IngestionError(f"Duplicate column name '{name}' (names are case-insensitive).", code="bad_header")
        seen.add(key)
        cleaned.append(name)
    return cleaned


# Files are read from server-side storage paths only; never let DuckDB fetch or load extensions.
_DUCKDB_CONFIG: dict[str, Any] = {"autoinstall_known_extensions": False, "autoload_known_extensions": False}


def read_csv(path: Path, encoding: str = "utf-8", max_rows: int | None = None) -> tuple[pd.DataFrame, ParseReport]:
    src = ensure_utf8(path, encoding)
    con = duckdb.connect(":memory:", config=_DUCKDB_CONFIG)
    try:
        try:
            rel = con.execute(
                "SELECT * FROM read_csv(?, all_varchar=true, header=true, ignore_errors=true, "
                "store_rejects=true, null_padding=false, sample_size=-1)",
                [str(src)],
            )
            cols = [d[0] for d in rel.description]
            rows = rel.fetchall() if max_rows is None else rel.fetchmany(max_rows + 1)
        except duckdb.Error as exc:  # pragma: no cover - message depends on duckdb version
            raise IngestionError("Could not parse the CSV file. Check delimiters and quoting.", code="parse_error") from exc
        if max_rows is not None and len(rows) > max_rows:
            raise IngestionError(
                f"File has more than {max_rows:,} rows, the configured limit for this deployment.",
                code="too_many_rows",
            )
        try:
            malformed = int(con.execute("SELECT count(*) FROM reject_errors").fetchone()[0])  # type: ignore[index]
        except duckdb.Error:
            malformed = 0
    finally:
        con.close()
        if src != path:
            src.unlink(missing_ok=True)
    names = validate_column_names(cols)
    df = pd.DataFrame.from_records(rows, columns=names)
    if df.empty and not names:
        raise IngestionError("The file contains no columns.", code="empty_file")
    report = ParseReport(rows=len(df), columns=len(names), malformed_rows=malformed, encoding=encoding)
    if malformed:
        report.warnings.append(f"{malformed} malformed row(s) were skipped (wrong number of fields or bad quoting).")
    return df, report


def read_parquet(path: Path, max_rows: int | None = None) -> tuple[pd.DataFrame, ParseReport]:
    try:
        con = duckdb.connect(":memory:", config=_DUCKDB_CONFIG)
        n = con.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()[0]  # type: ignore[index]
        if max_rows is not None and n > max_rows:
            raise IngestionError(
                f"File has more than {max_rows:,} rows, the configured limit for this deployment.",
                code="too_many_rows",
            )
        df = con.execute("SELECT * FROM read_parquet(?)", [str(path)]).df()
        con.close()
    except duckdb.Error as exc:
        raise IngestionError("Could not read the Parquet file; it may be corrupt.", code="parse_error") from exc
    df.columns = validate_column_names([str(c) for c in df.columns])
    return df, ParseReport(rows=len(df), columns=df.shape[1], encoding="binary")


def read_file(path: Path, fmt: str, encoding: str = "utf-8", max_rows: int | None = None) -> tuple[pd.DataFrame, ParseReport]:
    if fmt == "csv":
        return read_csv(path, encoding=encoding, max_rows=max_rows)
    if fmt == "parquet":
        return read_parquet(path, max_rows=max_rows)
    raise IngestionError(f"Unsupported format '{fmt}'.", code="unsupported_format")


# ---------------------------------------------------------------------------
# Type inference
# ---------------------------------------------------------------------------


def _string_values(series: pd.Series) -> pd.Series:
    s = series.dropna().astype(str).str.strip()
    return s[s != ""]


def infer_semantic_type(series: pd.Series) -> SemanticType:
    """Deterministically infer a semantic type.

    Rules (applied in order, on non-empty values):
      * native bool dtype or every value in {true,false,yes,no,t,f,y,n} -> boolean
      * native numeric dtype or every value parses as a number          -> numeric
      * native datetime dtype or every value is ISO/US-style date-like   -> datetime
      * <= 50 distinct values, or distinct ratio <= 0.2 with short values -> categorical
      * otherwise                                                        -> text
    """
    if pd.api.types.is_bool_dtype(series):
        return SemanticType.BOOLEAN
    if pd.api.types.is_numeric_dtype(series):
        return SemanticType.NUMERIC
    if pd.api.types.is_datetime64_any_dtype(series):
        return SemanticType.DATETIME
    values = _string_values(series)
    if values.empty:
        return SemanticType.TEXT
    lowered = values.str.lower()
    if lowered.isin(_BOOL_TRUE | _BOOL_FALSE).all():
        return SemanticType.BOOLEAN
    if pd.to_numeric(values, errors="coerce").notna().all():
        return SemanticType.NUMERIC
    if values.str.match(_DATE_HINT).all():
        parsed = pd.to_datetime(values, errors="coerce", format="mixed")
        if parsed.notna().all():
            return SemanticType.DATETIME
    nunique = values.nunique()
    ratio = nunique / len(values)
    if nunique <= 50 or (ratio <= 0.2 and values.str.len().mean() <= 40):
        return SemanticType.CATEGORICAL
    return SemanticType.TEXT


def coerce_column(series: pd.Series, semantic: SemanticType) -> pd.Series:
    """Convert a column to the canonical dtype for its semantic type.

    Values that cannot be converted become null; callers that apply user-requested
    conversions should count those coercion failures before relying on the result.
    """
    if semantic == SemanticType.NUMERIC:
        if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
            num = series.astype("float64")
        else:
            cleaned = series.where(series.isna(), series.astype(str).str.strip())
            cleaned = cleaned.replace("", np.nan)
            num = pd.to_numeric(cleaned, errors="coerce").astype("float64")
        finite = num.dropna()
        if len(finite) and np.all(np.mod(finite, 1) == 0) and finite.abs().max() < 2**53:
            return num.astype("Int64")
        return num
    if semantic == SemanticType.BOOLEAN:
        if pd.api.types.is_bool_dtype(series):
            return series.astype("boolean")
        lowered = series.where(series.isna(), series.astype(str).str.strip().str.lower())
        mapped = lowered.map(lambda v: True if v in _BOOL_TRUE else (False if v in _BOOL_FALSE else None))
        return mapped.astype("boolean")
    if semantic == SemanticType.DATETIME:
        if pd.api.types.is_datetime64_any_dtype(series):
            out = series
        else:
            cleaned = series.where(series.isna(), series.astype(str).str.strip()).replace("", np.nan)
            out = pd.to_datetime(cleaned, errors="coerce", format="mixed", utc=True)
        if getattr(out.dt, "tz", None) is not None:
            out = out.dt.tz_convert("UTC").dt.tz_localize(None)
        return out.astype("datetime64[ns]")
    out = series.where(series.isna(), series.astype(str))
    out = out.replace("", np.nan) if out.dtype == object else out
    return out.astype("string")


def infer_schema(df: pd.DataFrame, overrides: dict[str, str] | None = None) -> list[ColumnSchema]:
    overrides = overrides or {}
    schema = []
    for i, col in enumerate(df.columns):
        semantic = SemanticType(overrides[col]) if col in overrides else infer_semantic_type(df[col])
        schema.append(
            ColumnSchema(
                name=col,
                position=i,
                semantic_type=semantic,
                physical_type=str(df[col].dtype),
                nullable=bool(df[col].isna().any() or (_string_values(df[col]).size < df[col].notna().sum())),
            )
        )
    return schema


def normalize_frame(df: pd.DataFrame, schema: list[ColumnSchema]) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for col in schema:
        out[col.name] = coerce_column(df[col.name], col.semantic_type)
        col.physical_type = str(out[col.name].dtype)
    return out.reset_index(drop=True)


def schema_fingerprint(schema: list[ColumnSchema] | list[dict[str, Any]]) -> str:
    items = [c.to_dict() if isinstance(c, ColumnSchema) else c for c in schema]
    canonical = [[c["name"], c["semantic_type"]] for c in sorted(items, key=lambda c: c["position"])]
    return hashlib.sha256(json.dumps(canonical, separators=(",", ":")).encode()).hexdigest()[:16]


def load_and_normalize(
    path: Path,
    fmt: str,
    encoding: str = "utf-8",
    max_rows: int | None = None,
    overrides: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, list[ColumnSchema], ParseReport]:
    raw, report = read_file(path, fmt, encoding=encoding, max_rows=max_rows)
    if raw.shape[1] == 0:
        raise IngestionError("The file contains no columns.", code="empty_file")
    schema = infer_schema(raw, overrides)
    df = normalize_frame(raw, schema)
    return df, schema, report


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def schema_from_dicts(items: list[dict[str, Any]]) -> list[ColumnSchema]:
    return [
        ColumnSchema(
            name=i["name"],
            position=i["position"],
            semantic_type=SemanticType(i["semantic_type"]),
            physical_type=i.get("physical_type", ""),
            nullable=i.get("nullable", True),
        )
        for i in items
    ]
