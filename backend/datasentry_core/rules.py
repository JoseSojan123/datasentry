"""Configurable data-quality rule engine.

Every rule type has a strict Pydantic configuration model. Rules never execute user
code: custom expectations use a small structured condition language that is
interpreted with vectorised pandas operations (see ``Condition``).

A rule fails only when its defined condition is violated beyond its configured
tolerance (``max_failure_pct``, default 0). Null values are ignored by value rules
(allowed_values, range, regex); use a not_null rule to require presence.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .io import SemanticType

RuleType = Literal[
    "not_null",
    "unique",
    "allowed_values",
    "range",
    "regex",
    "referential_integrity",
    "freshness",
    "row_count",
    "duplicate_rows",
    "schema",
    "expectation",
]
RULE_TYPES: tuple[str, ...] = RuleType.__args__  # type: ignore[attr-defined]
DATASET_LEVEL = {"freshness", "row_count", "schema"}
SAMPLE_LIMIT = 5
MAX_REGEX_LENGTH = 300
_NESTED_QUANTIFIER = re.compile(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)\s*[+*{]")
# A repeated group with alternatives, e.g. (a|aa)+, can also backtrack exponentially when branches overlap.
_QUANTIFIED_ALTERNATION = re.compile(r"\((?:[^()\\]|\\.)*\|(?:[^()\\]|\\.)*\)\s*[+*{]")


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_failure_pct: float = Field(0.0, ge=0, le=100, description="Tolerated % of failing rows.")


class NotNullConfig(_Base):
    pass


class UniqueConfig(_Base):
    pass


class AllowedValuesConfig(_Base):
    values: list[str | int | float | bool] = Field(min_length=1, max_length=1000)
    case_sensitive: bool = True


class RangeConfig(_Base):
    min: float | None = None
    max: float | None = None
    inclusive: bool = True

    @model_validator(mode="after")
    def _bounds(self) -> RangeConfig:
        if self.min is None and self.max is None:
            raise ValueError("range rule needs at least one of min or max")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must be <= max")
        return self


class RegexConfig(_Base):
    pattern: str = Field(min_length=1, max_length=MAX_REGEX_LENGTH)
    full_match: bool = True

    @field_validator("pattern")
    @classmethod
    def _safe_pattern(cls, v: str) -> str:
        if _NESTED_QUANTIFIER.search(v):
            raise ValueError("nested quantifiers such as (a+)+ are not allowed (catastrophic backtracking risk)")
        if _QUANTIFIED_ALTERNATION.search(v):
            raise ValueError("repeated alternations such as (a|aa)+ are not allowed (catastrophic backtracking risk)")
        if re.search(r"\\\d", v):
            raise ValueError("backreferences are not allowed")
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"invalid regular expression: {exc}") from exc
        return v


class ReferentialIntegrityConfig(_Base):
    reference_dataset_id: int
    reference_column: str


class FreshnessConfig(_Base):
    max_age_seconds: int = Field(gt=0)


class RowCountConfig(_Base):
    min_rows: int | None = Field(None, ge=0)
    max_rows: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _bounds(self) -> RowCountConfig:
        if self.min_rows is None and self.max_rows is None:
            raise ValueError("row_count rule needs min_rows or max_rows")
        return self


class DuplicateRowsConfig(_Base):
    pass


class ExpectedColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    semantic_type: SemanticType | None = None
    required: bool = True


class SchemaConfig(_Base):
    expected_columns: list[ExpectedColumn] = Field(min_length=1)
    allow_extra_columns: bool = True


Op = Literal["eq", "ne", "lt", "le", "gt", "ge", "in", "not_in", "is_null", "not_null", "matches"]


class Comparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    op: Op
    value: str | int | float | bool | list[str | int | float | bool] | None = None
    other_column: str | None = None

    @model_validator(mode="after")
    def _operand(self) -> Comparison:
        if self.op in ("is_null", "not_null"):
            return self
        if (self.value is None) == (self.other_column is None):
            raise ValueError(f"'{self.op}' needs exactly one of value or other_column")
        if self.op in ("in", "not_in") and not isinstance(self.value, list):
            raise ValueError(f"'{self.op}' needs a list value")
        if self.op == "matches":
            RegexConfig(pattern=str(self.value))
        return self


class AllOf(BaseModel):
    model_config = ConfigDict(extra="forbid")
    all: list[Condition] = Field(min_length=1, max_length=20)


class AnyOf(BaseModel):
    model_config = ConfigDict(extra="forbid")
    any: list[Condition] = Field(min_length=1, max_length=20)


class Not(BaseModel):
    model_config = ConfigDict(extra="forbid")
    not_: Condition = Field(alias="not")


Condition = Annotated[Comparison | AllOf | AnyOf | Not, Field(union_mode="left_to_right")]
AllOf.model_rebuild()
AnyOf.model_rebuild()
Not.model_rebuild()


class ExpectationConfig(_Base):
    """Row-level expectation: rows where ``when`` holds must satisfy ``expect``."""

    expect: Condition
    when: Condition | None = None
    description: str | None = Field(None, max_length=300)


CONFIG_MODELS: dict[str, type[_Base]] = {
    "not_null": NotNullConfig,
    "unique": UniqueConfig,
    "allowed_values": AllowedValuesConfig,
    "range": RangeConfig,
    "regex": RegexConfig,
    "referential_integrity": ReferentialIntegrityConfig,
    "freshness": FreshnessConfig,
    "row_count": RowCountConfig,
    "duplicate_rows": DuplicateRowsConfig,
    "schema": SchemaConfig,
    "expectation": ExpectationConfig,
}
REQUIRES_COLUMNS = {"not_null", "unique", "allowed_values", "range", "regex", "referential_integrity"}


def validate_rule(rule_type: str, columns: list[str], config: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise a rule definition. Raises ValueError with a readable message."""
    if rule_type not in CONFIG_MODELS:
        raise ValueError(f"Unknown rule type '{rule_type}'. Supported: {', '.join(RULE_TYPES)}")
    if rule_type in REQUIRES_COLUMNS and not columns:
        raise ValueError(f"Rule type '{rule_type}' requires at least one column")
    if rule_type in {"allowed_values", "range", "regex", "referential_integrity"} and len(columns) != 1:
        raise ValueError(f"Rule type '{rule_type}' applies to exactly one column")
    model = CONFIG_MODELS[rule_type].model_validate(config or {})
    return model.model_dump(by_alias=True, exclude_none=True)


@dataclass
class RuleContext:
    as_of: datetime = field(default_factory=lambda: datetime.now(UTC))
    reference_values: dict[int, dict[str, set[Any]]] = field(default_factory=dict)
    semantic_types: dict[str, str] = field(default_factory=dict)
    store_samples: bool = True


@dataclass
class RuleResult:
    status: Literal["pass", "fail", "error"]
    rows_evaluated: int
    failed_rows: int | None
    failure_pct: float | None
    observed: dict[str, Any]
    expected: dict[str, Any]
    explanation: str
    duration_ms: float = 0.0
    sample_failures: list[dict[str, Any]] = field(default_factory=list)
    scope: Literal["row", "dataset"] = "row"

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _missing_columns(df: pd.DataFrame, columns: list[str]) -> list[str]:
    return [c for c in columns if c not in df.columns]


def _row_result(
    mask_failed: pd.Series,
    evaluated: int,
    tolerance: float,
    df: pd.DataFrame,
    columns: list[str],
    ctx: RuleContext,
    describe: Callable[[int, float], str],
    observed: dict[str, Any] | None = None,
    expected: dict[str, Any] | None = None,
) -> RuleResult:
    failed = int(mask_failed.sum())
    pct = round(100 * failed / evaluated, 4) if evaluated else 0.0
    status: Literal["pass", "fail"] = "fail" if failed and pct > tolerance else "pass"
    samples: list[dict[str, Any]] = []
    if failed and ctx.store_samples:
        idx = mask_failed[mask_failed].index[:SAMPLE_LIMIT]
        for i in idx:
            row: dict[str, Any] = {"row": int(i)}
            for c in columns:
                if c in df.columns:
                    v = df.at[i, c]
                    row[c] = None if pd.isna(v) else (str(v)[:80] if not isinstance(v, int | float | bool) else v)
            samples.append(row)
    obs = {"failed_rows": failed, "failure_pct": pct, **(observed or {})}
    exp = {"max_failure_pct": tolerance, **(expected or {})}
    return RuleResult(status, evaluated, failed, pct, obs, exp, describe(failed, pct), sample_failures=samples)


def _compare(series: pd.Series, op: str, other: Any) -> pd.Series:
    if op == "eq":
        return series == other
    if op == "ne":
        return series != other
    if op == "lt":
        return series < other
    if op == "le":
        return series <= other
    if op == "gt":
        return series > other
    if op == "ge":
        return series >= other
    raise ValueError(op)


def evaluate_condition(df: pd.DataFrame, cond: Any) -> pd.Series:
    """Evaluate a structured condition into a boolean mask. Null comparisons evaluate to False."""
    if isinstance(cond, dict):
        if "all" in cond:
            cond = AllOf.model_validate(cond)
        elif "any" in cond:
            cond = AnyOf.model_validate(cond)
        elif "not" in cond:
            cond = Not.model_validate(cond)
        else:
            cond = Comparison.model_validate(cond)
    if isinstance(cond, AllOf):
        mask = pd.Series(True, index=df.index)
        for c in cond.all:
            mask &= evaluate_condition(df, c)
        return mask
    if isinstance(cond, AnyOf):
        mask = pd.Series(False, index=df.index)
        for c in cond.any:
            mask |= evaluate_condition(df, c)
        return mask
    if isinstance(cond, Not):
        return ~evaluate_condition(df, cond.not_)
    assert isinstance(cond, Comparison)
    if cond.column not in df.columns:
        raise KeyError(cond.column)
    s = df[cond.column]
    if cond.op == "is_null":
        return s.isna()
    if cond.op == "not_null":
        return s.notna()
    if cond.op in ("in", "not_in"):
        vals = [str(v) for v in cond.value]  # type: ignore[union-attr]
        m = s.astype("string").isin(vals).fillna(False).astype(bool)
        return (m if cond.op == "in" else ~m) & s.notna()
    if cond.op == "matches":
        pat = re.compile(str(cond.value))
        return s.astype("string").map(lambda v: bool(pat.fullmatch(v)) if isinstance(v, str) else False).astype(bool)
    if cond.other_column is not None:
        if cond.other_column not in df.columns:
            raise KeyError(cond.other_column)
        other = df[cond.other_column]
        res = _compare(s, cond.op, other)
        valid = s.notna() & other.notna()
    else:
        value: Any = cond.value
        other = value
        if isinstance(other, int | float) and not isinstance(other, bool):
            s = pd.to_numeric(s, errors="coerce")
        res = _compare(s, cond.op, other)
        valid = s.notna()
    return res.fillna(False).astype(bool) & valid


def run_rule(
    df: pd.DataFrame, rule_type: str, columns: list[str], config: dict[str, Any], ctx: RuleContext | None = None
) -> RuleResult:
    ctx = ctx or RuleContext()
    started = time.perf_counter()
    try:
        cfg = CONFIG_MODELS[rule_type].model_validate(config or {})
        missing = _missing_columns(df, columns)
        if missing:
            res = RuleResult(
                "fail",
                len(df),
                len(df),
                100.0 if len(df) else 0.0,
                {"missing_columns": missing},
                {"columns": columns},
                f"Column(s) {', '.join(missing)} are not present in this version, so the rule cannot be satisfied.",
            )
        else:
            res = _DISPATCH[rule_type](df, columns, cfg, ctx)
    except (KeyError, ValueError, TypeError, re.error) as exc:
        res = RuleResult("error", len(df), None, None, {"error": str(exc)[:300]}, {}, f"Rule could not be evaluated: {exc}")
    res.duration_ms = round((time.perf_counter() - started) * 1000, 3)
    if rule_type in DATASET_LEVEL:
        res.scope = "dataset"
    return res


def _not_null(df: pd.DataFrame, columns: list[str], cfg: NotNullConfig, ctx: RuleContext) -> RuleResult:
    mask = df[columns].isna().any(axis=1)
    per_col = {c: int(df[c].isna().sum()) for c in columns}
    return _row_result(
        mask, len(df), cfg.max_failure_pct, df, columns, ctx,
        lambda f, p: f"{f:,} of {len(df):,} rows ({p}%) have a null in {', '.join(columns)}"
        + (f"; tolerance is {cfg.max_failure_pct}%." if cfg.max_failure_pct else "; no nulls are allowed."),
        observed={"nulls_per_column": per_col},
    )


def _unique(df: pd.DataFrame, columns: list[str], cfg: UniqueConfig, ctx: RuleContext) -> RuleResult:
    sub = df[columns]
    present = sub.notna().all(axis=1)
    mask = sub[present].duplicated(keep=False).reindex(df.index, fill_value=False)
    n_groups = int(sub[present][mask[present]].drop_duplicates().shape[0])
    return _row_result(
        mask, int(present.sum()), cfg.max_failure_pct, df, columns, ctx,
        lambda f, p: f"{f:,} rows share a value of ({', '.join(columns)}) with another row "
        f"across {n_groups:,} duplicated value(s). Rows with nulls in the key are not counted.",
        observed={"duplicated_values": n_groups},
    )


def _allowed(df: pd.DataFrame, columns: list[str], cfg: AllowedValuesConfig, ctx: RuleContext) -> RuleResult:
    col = columns[0]
    s = df[col]
    present = s.notna()
    vals = s[present].astype(str)
    allowed = [str(v) for v in cfg.values]
    if not cfg.case_sensitive:
        vals = vals.str.lower()
        allowed = [a.lower() for a in allowed]
    bad = ~vals.isin(allowed)
    mask = bad.reindex(df.index, fill_value=False)
    unexpected = vals[bad].value_counts().head(10)
    return _row_result(
        mask, int(present.sum()), cfg.max_failure_pct, df, columns, ctx,
        lambda f, p: f"{f:,} non-null values in '{col}' ({p}%) are outside the allowed set"
        + (f"; most common unexpected: {', '.join(map(str, unexpected.index[:3]))}." if f else "."),
        observed={"unexpected_values": {str(k): int(v) for k, v in unexpected.items()}},
        expected={"allowed_values": cfg.values},
    )


def _range(df: pd.DataFrame, columns: list[str], cfg: RangeConfig, ctx: RuleContext) -> RuleResult:
    col = columns[0]
    if ctx.semantic_types.get(col) not in (None, SemanticType.NUMERIC.value):
        raise TypeError(f"range rule needs a numeric column; '{col}' is {ctx.semantic_types[col]}")
    s = pd.to_numeric(df[col], errors="coerce").astype("float64")
    present = s.notna()
    below = pd.Series(False, index=df.index)
    above = pd.Series(False, index=df.index)
    if cfg.min is not None:
        below = (s < cfg.min) if cfg.inclusive else (s <= cfg.min)
    if cfg.max is not None:
        above = (s > cfg.max) if cfg.inclusive else (s >= cfg.max)
    mask = (below | above).fillna(False) & present
    bounds = f"[{cfg.min}, {cfg.max}]" if cfg.inclusive else f"({cfg.min}, {cfg.max})"
    return _row_result(
        mask, int(present.sum()), cfg.max_failure_pct, df, columns, ctx,
        lambda f, p: f"{f:,} values in '{col}' ({p}%) fall outside {bounds} "
        f"({int(below.sum())} below, {int(above.sum())} above). Observed min {s.min()}, max {s.max()}.",
        observed={"min": None if s.dropna().empty else float(s.min()), "max": None if s.dropna().empty else float(s.max()),
                  "below": int(below.sum()), "above": int(above.sum())},
        expected={"min": cfg.min, "max": cfg.max, "inclusive": cfg.inclusive},
    )


def _regex(df: pd.DataFrame, columns: list[str], cfg: RegexConfig, ctx: RuleContext) -> RuleResult:
    col = columns[0]
    pat = re.compile(cfg.pattern)
    s = df[col]
    present = s.notna()
    vals = s[present].astype(str).str.slice(0, 1000)
    matcher = pat.fullmatch if cfg.full_match else pat.search
    ok = vals.map(lambda v: matcher(v) is not None).astype(bool)
    mask = (~ok).reindex(df.index, fill_value=False)
    return _row_result(
        mask, int(present.sum()), cfg.max_failure_pct, df, columns, ctx,
        lambda f, p: f"{f:,} non-null values in '{col}' ({p}%) do not "
        f"{'fully match' if cfg.full_match else 'contain a match for'} /{cfg.pattern}/.",
        expected={"pattern": cfg.pattern, "full_match": cfg.full_match},
    )


def _referential(
    df: pd.DataFrame, columns: list[str], cfg: ReferentialIntegrityConfig, ctx: RuleContext
) -> RuleResult:
    col = columns[0]
    ref = ctx.reference_values.get(cfg.reference_dataset_id, {}).get(cfg.reference_column)
    if ref is None:
        raise ValueError(
            f"reference dataset {cfg.reference_dataset_id} column '{cfg.reference_column}' is unavailable"
        )
    ref_str = {str(v) for v in ref}
    s = df[col]
    present = s.notna()
    bad = ~s[present].astype(str).isin(ref_str)
    mask = bad.reindex(df.index, fill_value=False)
    orphans = s[present][bad].astype(str).value_counts().head(10)
    return _row_result(
        mask, int(present.sum()), cfg.max_failure_pct, df, columns, ctx,
        lambda f, p: f"{f:,} values in '{col}' ({p}%) have no matching '{cfg.reference_column}' "
        f"in reference dataset #{cfg.reference_dataset_id} ({len(ref_str):,} reference keys).",
        observed={"orphan_values": {str(k): int(v) for k, v in orphans.items()}, "reference_key_count": len(ref_str)},
        expected={"reference_dataset_id": cfg.reference_dataset_id, "reference_column": cfg.reference_column},
    )


def _freshness(df: pd.DataFrame, columns: list[str], cfg: FreshnessConfig, ctx: RuleContext) -> RuleResult:
    col = columns[0] if columns else next(
        (c for c, t in ctx.semantic_types.items() if t == SemanticType.DATETIME.value), None
    )
    if col is None or col not in df.columns:
        raise ValueError("freshness rule needs a datetime column")
    ts = pd.to_datetime(df[col], errors="coerce").dropna()
    as_of = pd.Timestamp(ctx.as_of)
    as_of = as_of.tz_convert("UTC").tz_localize(None) if as_of.tzinfo else as_of
    if ts.empty:
        return RuleResult("fail", len(df), None, None, {"latest": None}, {"max_age_seconds": cfg.max_age_seconds},
                          f"'{col}' has no valid timestamps, so freshness cannot be established.")
    latest = ts.max()
    age = (as_of - latest).total_seconds()
    status: Literal["pass", "fail"] = "fail" if age > cfg.max_age_seconds else "pass"
    return RuleResult(
        status, len(df), None, None,
        {"latest": latest.isoformat(), "age_seconds": round(age, 1), "column": col},
        {"max_age_seconds": cfg.max_age_seconds},
        f"Latest '{col}' is {latest.isoformat()}, {age / 3600:.1f} h before evaluation time; "
        f"the limit is {cfg.max_age_seconds / 3600:.1f} h.",
    )


def _row_count(df: pd.DataFrame, columns: list[str], cfg: RowCountConfig, ctx: RuleContext) -> RuleResult:
    n = len(df)
    ok = (cfg.min_rows is None or n >= cfg.min_rows) and (cfg.max_rows is None or n <= cfg.max_rows)
    return RuleResult(
        "pass" if ok else "fail", n, None, None, {"row_count": n},
        {"min_rows": cfg.min_rows, "max_rows": cfg.max_rows},
        f"Dataset has {n:,} rows; expected between {cfg.min_rows if cfg.min_rows is not None else '-'} "
        f"and {cfg.max_rows if cfg.max_rows is not None else '-'}.",
    )


def _dup_rows(df: pd.DataFrame, columns: list[str], cfg: DuplicateRowsConfig, ctx: RuleContext) -> RuleResult:
    cols = columns or list(df.columns)
    mask = df.duplicated(subset=cols, keep="first")
    return _row_result(
        mask, len(df), cfg.max_failure_pct, df, cols[:5], ctx,
        lambda f, p: f"{f:,} rows ({p}%) are exact repeats of an earlier row over "
        f"{'all columns' if not columns else ', '.join(columns)} (first occurrences are not counted).",
    )


def _schema(df: pd.DataFrame, columns: list[str], cfg: SchemaConfig, ctx: RuleContext) -> RuleResult:
    problems: list[str] = []
    present = set(df.columns)
    missing = [c.name for c in cfg.expected_columns if c.required and c.name not in present]
    type_mismatch = [
        {"column": c.name, "expected": c.semantic_type.value, "observed": ctx.semantic_types.get(c.name)}
        for c in cfg.expected_columns
        if c.semantic_type and c.name in present and ctx.semantic_types.get(c.name) not in (None, c.semantic_type.value)
    ]
    extra = sorted(present - {c.name for c in cfg.expected_columns})
    if missing:
        problems.append(f"missing required column(s): {', '.join(missing)}")
    if type_mismatch:
        problems.append("type mismatch: " + ", ".join(f"{t['column']} ({t['expected']}→{t['observed']})" for t in type_mismatch))
    if extra and not cfg.allow_extra_columns:
        problems.append(f"unexpected column(s): {', '.join(extra)}")
    return RuleResult(
        "fail" if problems else "pass", len(df), None, None,
        {"missing": missing, "type_mismatches": type_mismatch, "extra": extra},
        {"expected_columns": [c.model_dump(exclude_none=True) for c in cfg.expected_columns],
         "allow_extra_columns": cfg.allow_extra_columns},
        ("Schema incompatible: " + "; ".join(problems) + ".") if problems else "Schema is compatible with the expected definition.",
    )


def _expectation(df: pd.DataFrame, columns: list[str], cfg: ExpectationConfig, ctx: RuleContext) -> RuleResult:
    applicable = evaluate_condition(df, cfg.when) if cfg.when is not None else pd.Series(True, index=df.index)
    satisfied = evaluate_condition(df, cfg.expect)
    mask = applicable & ~satisfied
    involved = _condition_columns(cfg.expect) + (_condition_columns(cfg.when) if cfg.when else [])
    label = cfg.description or "custom expectation"
    return _row_result(
        mask, int(applicable.sum()), cfg.max_failure_pct, df, list(dict.fromkeys(involved)), ctx,
        lambda f, p: f"{f:,} of {int(applicable.sum()):,} applicable rows ({p}%) violate the {label}.",
        expected={"expect": cfg.model_dump(by_alias=True, exclude_none=True)["expect"]},
    )


def _condition_columns(cond: Any) -> list[str]:
    if isinstance(cond, Comparison):
        return [cond.column] + ([cond.other_column] if cond.other_column else [])
    if isinstance(cond, AllOf):
        return [c for sub in cond.all for c in _condition_columns(sub)]
    if isinstance(cond, AnyOf):
        return [c for sub in cond.any for c in _condition_columns(sub)]
    if isinstance(cond, Not):
        return _condition_columns(cond.not_)
    return []


_DISPATCH: dict[str, Callable[..., RuleResult]] = {
    "not_null": _not_null,
    "unique": _unique,
    "allowed_values": _allowed,
    "range": _range,
    "regex": _regex,
    "referential_integrity": _referential,
    "freshness": _freshness,
    "row_count": _row_count,
    "duplicate_rows": _dup_rows,
    "schema": _schema,
    "expectation": _expectation,
}


def summarize(results: list[tuple[dict[str, Any], RuleResult]]) -> dict[str, Any]:
    """Dataset- and column-level summary over (rule_definition, result) pairs."""
    by_status = {"pass": 0, "fail": 0, "error": 0}
    by_column: dict[str, dict[str, int]] = {}
    failed_by_severity: dict[str, int] = {}
    for rule, res in results:
        by_status[res.status] += 1
        if res.status == "fail":
            sev = rule.get("severity", "warning")
            failed_by_severity[sev] = failed_by_severity.get(sev, 0) + 1
        for col in rule.get("columns") or ["(dataset)"]:
            entry = by_column.setdefault(col, {"pass": 0, "fail": 0, "error": 0})
            entry[res.status] += 1
    total = len(results)
    return {
        "total": total,
        "passed": by_status["pass"],
        "failed": by_status["fail"],
        "errored": by_status["error"],
        "pass_rate": round(100 * by_status["pass"] / total, 2) if total else None,
        "failed_by_severity": failed_by_severity,
        "by_column": by_column,
    }


def numpy_safe(o: Any) -> Any:
    """Recursively convert numpy scalars for JSON storage."""
    if isinstance(o, dict):
        return {str(k): numpy_safe(v) for k, v in o.items()}
    if isinstance(o, list | tuple):
        return [numpy_safe(v) for v in o]
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, float) and not np.isfinite(o):
        return None
    if isinstance(o, pd.Timestamp | datetime):
        return o.isoformat()
    return o
