"""Generate docs/data-dictionary.md from the SQLAlchemy models, so the document cannot drift from the schema.

    cd backend && python ../scripts/gen_data_dictionary.py
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db import models as m  # noqa: E402

PURPOSE = {
    "workspaces": "Tenant boundary. Demo workspaces carry an expiry and are purged by maintenance.",
    "users": "Accounts with a role (admin, editor, viewer) in one workspace; scrypt password hash.",
    "api_keys": "SDK and automation keys; only an HMAC of the key is stored.",
    "datasets": "Monitored datasets with owner, criticality, settings (gate mode, thresholds, policies) and health.",
    "dataset_versions": "Each uploaded or derived batch: ingestion result, checksum, status, lineage to its parent version.",
    "dataset_schema_columns": "Inferred schema of a version (semantic and physical type per column).",
    "stored_files": None,
    "profiles": "Per-version profile: summary and per-column statistics, with the config used.",
    "quality_rules": "Validated rule definitions (type, columns, config, severity).",
    "quality_check_runs": None,
    "quality_check_results": "Per-rule outcome of a run: rows evaluated, failures, observed vs expected, samples, explanation.",
    "version_comparisons": "Schema and profile diff between two versions, including rename candidates.",
    "column_rename_decisions": "User confirmations or rejections of rename candidates.",
    "drift_evaluations": "One drift comparison between a reference and a current version, with config and summary.",
    "drift_feature_results": "Per-feature drift statistics, corrected p-values, status and evidence.",
    "ml_models": "Registered models (task, target, positive label, reference dataset, criticality).",
    "model_versions": "Model versions with input schema, baseline metrics and feature-logging policy.",
    "prediction_records": "Logged predictions and delayed labels (raw features only with full logging).",
    "prediction_batches": None,
    "model_evaluations": "Windowed model evaluation: metrics with intervals, input and prediction drift, status.",
    "lineage_nodes": "Datasets, transformations, feature tables, models, reports and consumers.",
    "lineage_edges": "Dependencies with provenance (confirmed, declared, inferred).",
    "incidents": "Deduplicated incidents with findings, impact, priority, assignment and resolution.",
    "incident_events": None,
    "incident_comments": "Investigation notes from editors.",
    "remediation_proposals": "Proposed actions with preconditions, risk, mode and approval state.",
    "remediation_executions": "Each execution attempt with its result and post-action verification.",
    "scheduled_jobs": "Recurring profile, validate, drift, monitor and model-evaluation jobs.",
    "job_executions": "Job run history with status, duration, retries and errors.",
    "notifications": "In-app notifications (and email, when SMTP is configured).",
    "audit_events": "Append-only record of security-relevant and state-changing actions.",
}


def main() -> None:
    lines = [
        "# Data dictionary",
        "",
        "Generated from `backend/app/db/models.py` by `scripts/gen_data_dictionary.py`. Do not edit by hand.",
        "",
        "Every table except `workspaces` carries a `workspace_id` (directly or through its parent) and every API query "
        "is scoped to the caller's workspace. Timestamps are stored in UTC.",
        "",
    ]
    classes = {c.__tablename__: c for _, c in inspect.getmembers(m, inspect.isclass)
               if issubclass(c, m.Base) and c is not m.Base and hasattr(c, "__tablename__")}
    order = [t.name for t in m.Base.metadata.sorted_tables]
    lines.append("| Table | Purpose |")
    lines.append("|---|---|")
    for name in order:
        doc = inspect.getdoc(classes[name]) if name in classes else ""
        purpose = PURPOSE.get(name) or ((doc or "").split("\n\n")[0].replace("\n", " ") if doc and doc != inspect.getdoc(m.Base) else "")
        lines.append(f"| [`{name}`](#{name.replace('_', '-')}) | {purpose} |")
    lines.append("")
    for name in order:
        table = m.Base.metadata.tables[name]
        lines += [f"## {name}", ""]
        doc = inspect.getdoc(classes[name]) if name in classes else None
        text = PURPOSE.get(name) or (doc if doc and doc != inspect.getdoc(m.Base) else None)
        if text:
            lines += [text, ""]
        lines += ["| Column | Type | Null | Key / default |", "|---|---|---|---|"]
        for col in table.columns:
            keys = []
            if col.primary_key:
                keys.append("PK")
            for fk in col.foreign_keys:
                keys.append(f"FK → `{fk.target_fullname}`" + (f" ({fk.ondelete.lower()})" if fk.ondelete else ""))
            if col.unique:
                keys.append("unique")
            if col.default is not None and getattr(col.default, "is_scalar", False):
                keys.append(f"default `{col.default.arg}`")
            lines.append(f"| `{col.name}` | {str(col.type).lower()} | {'yes' if col.nullable else 'no'} | {', '.join(keys)} |")
        idx = [i for i in table.indexes] + [c for c in table.constraints if c.__class__.__name__ == "UniqueConstraint" and len(c.columns) > 1]
        if idx:
            lines.append("")
            lines.append("Indexes and constraints: " + "; ".join(
                f"`{getattr(i, 'name', None) or 'unnamed'}` ({', '.join(c.name for c in i.columns)})" for i in idx))
        lines.append("")
    out = ROOT / "docs" / "data-dictionary.md"
    out.write_text("\n".join(lines))
    print(f"Wrote {out} ({len(order)} tables)")


if __name__ == "__main__":
    main()
