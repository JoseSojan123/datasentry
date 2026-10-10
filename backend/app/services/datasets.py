from __future__ import annotations

import logging
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import APIError, conflict
from app.db import models as m
from app.services import audit
from app.services.storage import storage
from datasentry_core import io as dio
from datasentry_core.profiling import ProfileConfig, profile_dataframe
from datasentry_core.rules import numpy_safe

log = logging.getLogger("datasentry.datasets")


def ensure_dataset_node(db: Session, ds: m.Dataset) -> m.LineageNode:
    node = db.scalar(select(m.LineageNode).where(m.LineageNode.dataset_id == ds.id))
    if node is None:
        node = m.LineageNode(workspace_id=ds.workspace_id, node_type="dataset", name=ds.name, dataset_id=ds.id,
                             criticality=ds.criticality, owner=ds.owner, meta={"auto_created": True})
        db.add(node)
        db.flush()
    else:
        node.name, node.criticality, node.owner = ds.name, ds.criticality, ds.owner
    return node


def create_dataset(db: Session, workspace_id: int, principal: Any, **fields: Any) -> m.Dataset:
    exists = db.scalar(select(m.Dataset.id).where(m.Dataset.workspace_id == workspace_id, m.Dataset.name == fields["name"]))
    if exists:
        raise conflict(f"A dataset named '{fields['name']}' already exists.", {"dataset_id": exists})
    ds = m.Dataset(workspace_id=workspace_id, **fields)
    db.add(ds)
    db.flush()
    ensure_dataset_node(db, ds)
    audit.record(db, workspace_id, "dataset.created", "dataset", ds.id, {"name": ds.name}, principal)
    return ds


def schema_of(version: m.DatasetVersion) -> list[dio.ColumnSchema]:
    return dio.schema_from_dicts([c.to_dict() for c in version.columns])


def load_frame(db: Session, version: m.DatasetVersion) -> pd.DataFrame:
    if not version.storage_key:
        raise APIError(409, "version_unavailable", f"Version {version.version_number} has no ingested data.")
    return storage.read_frame(db, version.storage_key)


def latest_profile(db: Session, version_id: int) -> m.Profile | None:
    return db.scalar(select(m.Profile).where(m.Profile.version_id == version_id).order_by(m.Profile.id.desc()).limit(1))


def profile_config(ds: m.Dataset) -> ProfileConfig:
    pc = ds.settings.get("profiling", {}) if ds.settings else {}
    return ProfileConfig(
        outlier_k=float(pc.get("outlier_k", 1.5)),
        rare_threshold=float(pc.get("rare_threshold", 0.01)),
        primary_key=list(ds.primary_key or []) or None,
        freshness_column=ds.freshness_column,
    )


def reference_categories(db: Session, ds: m.Dataset, exclude_version: int | None = None) -> dict[str, set[str]] | None:
    ref_id = ds.reference_version_id
    if not ref_id or ref_id == exclude_version:
        return None
    prof = latest_profile(db, ref_id)
    if not prof:
        return None
    return {n: set(c.get("frequencies", {})) for n, c in prof.columns.items()
            if "frequencies" in c and not c.get("frequencies_truncated")}


def profile_version(db: Session, ds: m.Dataset, version: m.DatasetVersion, as_of: datetime | None = None) -> m.Profile:
    df = load_frame(db, version)
    result = profile_dataframe(df, schema_of(version), profile_config(ds), as_of or datetime.now(UTC),
                               reference_categories(db, ds, version.id))
    prof = m.Profile(dataset_id=ds.id, version_id=version.id, summary=numpy_safe(result["dataset"]),
                     columns=numpy_safe(result["columns"]), config=numpy_safe(result["config"]),
                     duration_ms=result["dataset"]["profiling_duration_ms"])
    db.add(prof)
    db.flush()
    return prof


def _next_version_number(db: Session, dataset_id: int) -> int:
    return (db.scalar(select(func.max(m.DatasetVersion.version_number)).where(m.DatasetVersion.dataset_id == dataset_id)) or 0) + 1


def ingest_file(
    db: Session,
    ds: m.Dataset,
    path: Path,
    filename: str,
    principal: Any = None,
    encoding: str = "utf-8",
    origin: str = "upload",
    origin_detail: dict[str, Any] | None = None,
    type_overrides: dict[str, str] | None = None,
) -> m.DatasetVersion:
    """Validate, parse and store one file as a new dataset version.

    Failures are recorded on the version (status ``failed``) with a user-safe error; the raw file is
    retained so the ingestion can be retried.
    """
    settings = get_settings()
    started = time.perf_counter()
    fmt = dio.detect_format(filename)
    size = path.stat().st_size
    if size == 0:
        raise APIError(400, "empty_file", "The uploaded file is empty.")
    if size > settings.max_upload_mb * 1024 * 1024:
        raise APIError(413, "payload_too_large", f"File exceeds the {settings.max_upload_mb} MB limit.")
    checksum = dio.file_checksum(path)
    dup = db.scalar(select(m.DatasetVersion).where(
        m.DatasetVersion.dataset_id == ds.id, m.DatasetVersion.checksum == checksum,
        m.DatasetVersion.ingestion_status == "succeeded"))
    if dup:
        raise conflict(f"This file is identical to version {dup.version_number} (same SHA-256 checksum).",
                       {"version_id": dup.id, "checksum": checksum})
    number = _next_version_number(db, ds.id)
    base_key = f"ws{ds.workspace_id}/ds{ds.id}/v{number}"
    v = m.DatasetVersion(dataset_id=ds.id, version_number=number, file_format=fmt, checksum=checksum, size_bytes=size,
                         original_filename=dio.safe_filename(filename), origin=origin, origin_detail=origin_detail or {},
                         created_by=getattr(principal, "user_id", None))
    db.add(v)
    db.flush()
    v.raw_storage_key = f"{base_key}/raw.{fmt}"
    storage.put(db, ds.workspace_id, v.raw_storage_key, path)
    _parse_into(db, ds, v, path, encoding, type_overrides, started)
    audit.record(db, ds.workspace_id, "dataset.version_ingested" if v.ingestion_status == "succeeded" else "dataset.ingestion_failed",
                 "dataset_version", v.id, {"dataset_id": ds.id, "version": number, "rows": v.row_count,
                                           "checksum": checksum, "error": (v.ingestion_error or {}).get("code")}, principal)
    return v


def _parse_into(db: Session, ds: m.Dataset, v: m.DatasetVersion, path: Path, encoding: str,
                type_overrides: dict[str, str] | None, started: float) -> None:
    settings = get_settings()
    try:
        overrides = {**(ds.settings or {}).get("type_overrides", {}), **(type_overrides or {})}
        df, schema, report = dio.load_and_normalize(path, v.file_format, encoding=encoding, max_rows=settings.max_rows,
                                                    overrides=overrides)
        if df.empty:
            raise dio.IngestionError("The file has a header but no data rows.", code="empty_file")
    except dio.IngestionError as exc:
        v.ingestion_status, v.status = "failed", "failed"
        v.ingestion_error = {"code": exc.code, "message": str(exc), "details": exc.details}
        v.ingestion_duration_ms = round((time.perf_counter() - started) * 1000, 2)
        db.flush()
        return
    except Exception:  # noqa: BLE001 - recorded, never leaked
        log.exception("ingestion failed dataset=%s version=%s", ds.id, v.id)
        v.ingestion_status, v.status = "failed", "failed"
        v.ingestion_error = {"code": "internal_error", "message": "Unexpected error while parsing the file."}
        v.ingestion_duration_ms = round((time.perf_counter() - started) * 1000, 2)
        db.flush()
        return
    store_frame(db, ds, v, df, schema)
    v.malformed_rows = report.malformed_rows
    v.parse_warnings = report.warnings
    v.ingestion_status = "succeeded"
    v.status = "pending"
    v.ingestion_error = None
    v.ingestion_duration_ms = round((time.perf_counter() - started) * 1000, 2)
    db.flush()


def store_frame(db: Session, ds: m.Dataset, v: m.DatasetVersion, df: pd.DataFrame, schema: list[dio.ColumnSchema]) -> None:
    v.storage_key = f"ws{ds.workspace_id}/ds{ds.id}/v{v.version_number}/data.parquet"
    storage.put_frame(db, ds.workspace_id, v.storage_key, df)
    v.row_count, v.column_count = int(len(df)), int(df.shape[1])
    v.schema_fingerprint = dio.schema_fingerprint(schema)
    v.columns.clear()
    db.flush()
    for c in schema:
        v.columns.append(m.SchemaColumn(name=c.name, position=c.position, semantic_type=c.semantic_type.value,
                                        physical_type=c.physical_type, nullable=c.nullable))
    db.flush()


def retry_ingestion(db: Session, ds: m.Dataset, v: m.DatasetVersion) -> None:
    if not v.raw_storage_key:
        raise APIError(409, "no_raw_file", "The raw upload for this version is not available.")
    started = time.perf_counter()
    with storage.local_copy(db, v.raw_storage_key) as p:
        _parse_into(db, ds, v, p, (v.origin_detail or {}).get("encoding", "utf-8"), None, started)


def ingest_frame(db: Session, ds: m.Dataset, df: pd.DataFrame, principal: Any, origin: str, filename: str = "data.csv",
                 origin_detail: dict[str, Any] | None = None) -> m.DatasetVersion:
    """Ingest an in-memory frame (SDK JSON upload, synthetic seed) through the same CSV path as uploads."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / dio.safe_filename(filename)
        if p.suffix == ".parquet":
            df.to_parquet(p, index=False)
        else:
            p = p.with_suffix(".csv")
            df.to_csv(p, index=False)
        return ingest_file(db, ds, p, p.name, principal, origin=origin, origin_detail=origin_detail)


def preview(db: Session, v: m.DatasetVersion, offset: int, limit: int) -> dict[str, Any]:
    df = load_frame(db, v)
    page = df.iloc[offset: offset + limit]
    rows = []
    for rec in page.to_dict(orient="records"):
        rows.append({k: (None if pd.isna(val) else (val.isoformat() if isinstance(val, pd.Timestamp) else
                                                      (val.item() if hasattr(val, "item") else val)))
                     for k, val in rec.items()})
    return {"columns": [c.to_dict() for c in v.columns], "rows": rows, "offset": offset, "limit": limit, "total": int(len(df))}
