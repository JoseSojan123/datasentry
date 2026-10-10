from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.services import datasets as dsvc
from datasentry_core.rules import RuleContext, numpy_safe, run_rule, summarize, validate_rule


def reference_values_for(db: Session, ds: m.Dataset, rules: list[m.QualityRule]) -> dict[int, dict[str, set[Any]]]:
    out: dict[int, dict[str, set[Any]]] = {}
    for r in rules:
        if r.rule_type != "referential_integrity" or not r.enabled:
            continue
        ref_id = int(r.config["reference_dataset_id"])
        ref = db.get(m.Dataset, ref_id)
        if ref is None or ref.workspace_id != ds.workspace_id or not ref.current_version_id:
            continue
        ver = db.get(m.DatasetVersion, ref.current_version_id)
        df = dsvc.load_frame(db, ver)
        col = r.config["reference_column"]
        if col in df.columns:
            out.setdefault(ref_id, {})[col] = set(df[col].dropna().astype(str))
    return out


def upsert_inline_rules(db: Session, ds: m.Dataset, specs: list[dict[str, Any]], principal: Any) -> list[m.QualityRule]:
    existing = list(db.scalars(select(m.QualityRule).where(m.QualityRule.dataset_id == ds.id)))
    out = []
    for spec in specs:
        rule_type = spec.get("type") or spec.get("rule_type")
        columns = spec.get("columns") or ([spec["column"]] if spec.get("column") else [])
        config = validate_rule(rule_type, columns, spec.get("config") or {})
        match = next((r for r in existing if r.rule_type == rule_type and r.columns == columns and r.config == config), None)
        if match is None:
            match = m.QualityRule(workspace_id=ds.workspace_id, dataset_id=ds.id, rule_type=rule_type, columns=columns,
                                  config=config, severity=spec.get("severity", "warning"),
                                  name=spec.get("name") or f"{rule_type} {', '.join(columns)}".strip(),
                                  created_by=getattr(principal, "user_id", None))
            db.add(match)
            db.flush()
            existing.append(match)
        out.append(match)
    return out


def run_rules(
    db: Session,
    ds: m.Dataset,
    version: m.DatasetVersion,
    trigger: str,
    rules: list[m.QualityRule] | None = None,
    as_of: datetime | None = None,
) -> m.CheckRun:
    started = time.perf_counter()
    if rules is None:
        rules = list(db.scalars(select(m.QualityRule).where(m.QualityRule.dataset_id == ds.id, m.QualityRule.enabled.is_(True))
                                .order_by(m.QualityRule.id)))
    df = dsvc.load_frame(db, version)
    ctx = RuleContext(as_of=as_of or datetime.now(UTC), reference_values=reference_values_for(db, ds, rules),
                      semantic_types={c.name: c.semantic_type for c in version.columns},
                      store_samples=(ds.settings or {}).get("store_failure_samples", True))
    run = m.CheckRun(dataset_id=ds.id, version_id=version.id, trigger=trigger)
    db.add(run)
    db.flush()
    pairs = []
    for rule in rules:
        res = run_rule(df, rule.rule_type, rule.columns or [], rule.config or {}, ctx)
        snap = rule.to_engine()
        pairs.append((snap, res))
        db.add(m.CheckResult(run_id=run.id, rule_id=rule.id, rule_snapshot=numpy_safe(snap), status=res.status,
                             rows_evaluated=res.rows_evaluated, failed_rows=res.failed_rows, failure_pct=res.failure_pct,
                             duration_ms=res.duration_ms, observed=numpy_safe(res.observed), expected=numpy_safe(res.expected),
                             explanation=res.explanation, sample_failures=numpy_safe(res.sample_failures)))
    run.summary = numpy_safe(summarize(pairs))
    run.duration_ms = round((time.perf_counter() - started) * 1000, 2)
    db.flush()
    return run


def run_results(db: Session, run_id: int) -> list[m.CheckResult]:
    return list(db.scalars(select(m.CheckResult).where(m.CheckResult.run_id == run_id).order_by(m.CheckResult.id)))


def result_dicts(db: Session, run: m.CheckRun) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [(r.rule_snapshot, {"status": r.status, "explanation": r.explanation, "observed": r.observed})
            for r in run_results(db, run.id)]
