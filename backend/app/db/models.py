"""SQLAlchemy models. PostgreSQL stores metadata and analytical summaries; raw dataset files live in
the configured storage backend (local filesystem or the ``stored_files`` table for small demos).

Tenancy: every top-level record belongs to a workspace. All API queries filter by the caller's
workspace, which prevents cross-tenant (IDOR) access. Deleting a workspace cascades to its data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

SEVERITY = ("info", "warning", "critical")
CRITICALITY = ("low", "medium", "high", "critical")


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}


def _ts(nullable: bool = False, default: bool = True) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=nullable, server_default=func.now() if default else None)


def _ws_fk() -> Mapped[int]:
    return mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = _ts()


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    email: Mapped[str] = mapped_column(String(254), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="editor")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = _ts()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("role in ('admin','editor','viewer')", name="ck_users_role"),)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(16), unique=True)
    key_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), default="editor")
    created_at: Mapped[datetime] = _ts()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(120))
    tags: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    domain: Mapped[str | None] = mapped_column(String(80))
    criticality: Mapped[str] = mapped_column(String(16), default="medium")
    source_type: Mapped[str] = mapped_column(String(16), default="upload")  # upload | synthetic | public | sdk
    primary_key: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    freshness_column: Mapped[str | None] = mapped_column(String(128))
    reference_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="SET NULL", use_alter=True, name="fk_dataset_reference_version")
    )
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="SET NULL", use_alter=True, name="fk_dataset_current_version")
    )
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    health: Mapped[str] = mapped_column(String(16), default="unknown")  # healthy | warning | failing | unknown
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_dataset_name"),
        CheckConstraint("criticality in ('low','medium','high','critical')", name="ck_dataset_criticality"),
    )


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|active|superseded|quarantined|rejected|failed
    ingestion_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|succeeded|failed
    ingestion_error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ingestion_duration_ms: Mapped[float | None] = mapped_column(Float)
    original_filename: Mapped[str | None] = mapped_column(String(160))
    file_format: Mapped[str] = mapped_column(String(16))
    raw_storage_key: Mapped[str | None] = mapped_column(String(255))
    storage_key: Mapped[str | None] = mapped_column(String(255))
    checksum: Mapped[str | None] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    row_count: Mapped[int | None] = mapped_column(Integer)
    column_count: Mapped[int | None] = mapped_column(Integer)
    malformed_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    schema_fingerprint: Mapped[str | None] = mapped_column(String(32))
    parse_warnings: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    is_known_good: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    parent_version_id: Mapped[int | None] = mapped_column(ForeignKey("dataset_versions.id", ondelete="SET NULL"))
    origin: Mapped[str] = mapped_column(String(32), default="upload")  # upload | sdk | synthetic | remediation
    origin_detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()
    columns: Mapped[list[SchemaColumn]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="SchemaColumn.position"
    )
    __table_args__ = (UniqueConstraint("dataset_id", "version_number", name="uq_version_number"),)


class SchemaColumn(Base):
    __tablename__ = "dataset_schema_columns"
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    position: Mapped[int] = mapped_column(Integer)
    semantic_type: Mapped[str] = mapped_column(String(16))
    physical_type: Mapped[str] = mapped_column(String(32))
    nullable: Mapped[bool] = mapped_column(Boolean)
    version: Mapped[DatasetVersion] = relationship(back_populates="columns")
    __table_args__ = (UniqueConstraint("version_id", "name", name="uq_schema_column"),)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "position": self.position, "semantic_type": self.semantic_type,
                "physical_type": self.physical_type, "nullable": self.nullable}


class StoredFile(Base):
    """Blob storage for the ``database`` storage backend (small demo deployments only)."""

    __tablename__ = "stored_files"
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    content: Mapped[bytes] = mapped_column(LargeBinary)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = _ts()


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"), index=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB)
    columns: Mapped[dict[str, Any]] = mapped_column(JSONB)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    duration_ms: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = _ts()


class QualityRule(Base):
    __tablename__ = "quality_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    rule_type: Mapped[str] = mapped_column(String(32))
    columns: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (CheckConstraint("severity in ('info','warning','critical')", name="ck_rule_severity"),)

    def to_engine(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "rule_type": self.rule_type, "columns": self.columns,
                "config": self.config, "severity": self.severity, "enabled": self.enabled}


class CheckRun(Base):
    """One execution of a dataset's rule set against a version."""

    __tablename__ = "quality_check_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"), index=True)
    trigger: Mapped[str] = mapped_column(String(32))  # upload | manual | schedule | remediation | sdk
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = _ts()


class CheckResult(Base):
    __tablename__ = "quality_check_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("quality_check_runs.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("quality_rules.id", ondelete="CASCADE"), index=True)
    rule_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(8))
    rows_evaluated: Mapped[int] = mapped_column(Integer)
    failed_rows: Mapped[int | None] = mapped_column(Integer)
    failure_pct: Mapped[float | None] = mapped_column(Float)
    duration_ms: Mapped[float] = mapped_column(Float)
    observed: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    expected: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    explanation: Mapped[str] = mapped_column(Text)
    sample_failures: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = _ts()


class VersionComparison(Base):
    __tablename__ = "version_comparisons"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    base_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"))
    target_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    overall_severity: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = _ts()


class RenameDecision(Base):
    __tablename__ = "column_rename_decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    from_column: Mapped[str] = mapped_column(String(128))
    to_column: Mapped[str] = mapped_column(String(128))
    decision: Mapped[str] = mapped_column(String(16))  # confirmed | rejected
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()
    __table_args__ = (UniqueConstraint("dataset_id", "from_column", "to_column", name="uq_rename_decision"),)


class DriftEvaluation(Base):
    __tablename__ = "drift_evaluations"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    reference_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"))
    current_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    windows: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB)
    other_findings: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    overall_severity: Mapped[str] = mapped_column(String(16))
    trigger: Mapped[str] = mapped_column(String(32), default="manual")
    created_at: Mapped[datetime] = _ts()
    features: Mapped[list[DriftFeatureResult]] = relationship(cascade="all, delete-orphan", order_by="DriftFeatureResult.id")


class DriftFeatureResult(Base):
    __tablename__ = "drift_feature_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_id: Mapped[int] = mapped_column(ForeignKey("drift_evaluations.id", ondelete="CASCADE"), index=True)
    feature: Mapped[str] = mapped_column(String(128))
    semantic_type: Mapped[str] = mapped_column(String(16))
    method: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24))
    severity: Mapped[str] = mapped_column(String(16))
    n_reference: Mapped[int] = mapped_column(Integer)
    n_current: Mapped[int] = mapped_column(Integer)
    significant: Mapped[bool | None] = mapped_column(Boolean)
    statistics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    explanation: Mapped[str] = mapped_column(Text)


class MLModel(Base):
    __tablename__ = "ml_models"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    task: Mapped[str] = mapped_column(String(16))  # classification | regression
    target: Mapped[str | None] = mapped_column(String(200))
    positive_label: Mapped[str | None] = mapped_column(String(64))
    reference_dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id", ondelete="SET NULL"))
    criticality: Mapped[str] = mapped_column(String(16), default="medium")
    owner: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = _ts()
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_model_name"),
        CheckConstraint("task in ('classification','regression')", name="ck_model_task"),
    )


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("ml_models.id", ondelete="CASCADE"), index=True)
    version: Mapped[str] = mapped_column(String(40))
    input_schema: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    baseline_metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    artifact: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    feature_logging: Mapped[str] = mapped_column(String(16), default="aggregate")  # none | aggregate | full
    reference_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    retention_days: Mapped[int] = mapped_column(Integer, default=90)
    created_at: Mapped[datetime] = _ts()
    __table_args__ = (UniqueConstraint("model_id", "version", name="uq_model_version"),)


class PredictionRecord(Base):
    __tablename__ = "prediction_records"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id", ondelete="CASCADE"))
    record_id: Mapped[str] = mapped_column(String(128))
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    features: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    prediction: Mapped[str] = mapped_column(String(64))
    prediction_value: Mapped[float | None] = mapped_column(Float)
    score: Mapped[float | None] = mapped_column(Float)
    label: Mapped[str | None] = mapped_column(String(64))
    labeled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    schema_violations: Mapped[list[Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _ts()
    __table_args__ = (
        UniqueConstraint("model_version_id", "record_id", name="uq_prediction_record"),
        Index("ix_predictions_version_time", "model_version_id", "predicted_at"),
    )


class PredictionBatch(Base):
    """Aggregated per-batch feature statistics used when raw feature logging is disabled."""

    __tablename__ = "prediction_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id", ondelete="CASCADE"), index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    n_predictions: Mapped[int] = mapped_column(Integer)
    feature_stats: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _ts()


class ModelEvaluation(Base):
    __tablename__ = "model_evaluations"
    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id", ondelete="CASCADE"), index=True)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    n_predictions: Mapped[int] = mapped_column(Integer)
    n_labelled: Mapped[int] = mapped_column(Integer)
    label_coverage: Mapped[float] = mapped_column(Float)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    input_drift: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    prediction_drift: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    performance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    schema_violation_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16))  # ok | warning | critical | unknown
    trigger: Mapped[str] = mapped_column(String(32), default="manual")
    created_at: Mapped[datetime] = _ts()


class LineageNode(Base):
    __tablename__ = "lineage_nodes"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    node_type: Mapped[str] = mapped_column(String(24))
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    model_id: Mapped[int | None] = mapped_column(ForeignKey("ml_models.id", ondelete="CASCADE"), index=True)
    criticality: Mapped[str] = mapped_column(String(16), default="medium")
    owner: Mapped[str | None] = mapped_column(String(120))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = _ts()
    __table_args__ = (
        UniqueConstraint("workspace_id", "node_type", "name", name="uq_lineage_node"),
        CheckConstraint("node_type in ('dataset','transformation','feature_table','model','report','consumer')",
                        name="ck_lineage_node_type"),
    )


class LineageEdge(Base):
    __tablename__ = "lineage_edges"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    source_id: Mapped[int] = mapped_column(ForeignKey("lineage_nodes.id", ondelete="CASCADE"), index=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("lineage_nodes.id", ondelete="CASCADE"), index=True)
    dependency_type: Mapped[str] = mapped_column(String(32), default="reads")
    provenance: Mapped[str] = mapped_column(String(16), default="declared")
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()
    __table_args__ = (
        UniqueConstraint("source_id", "target_id", name="uq_lineage_edge"),
        CheckConstraint("source_id <> target_id", name="ck_lineage_no_self_loop"),
        CheckConstraint("provenance in ('confirmed','declared','inferred')", name="ck_lineage_provenance"),
    )


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[int | None] = mapped_column(ForeignKey("dataset_versions.id", ondelete="SET NULL"))
    model_id: Mapped[int | None] = mapped_column(ForeignKey("ml_models.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="open")
    fingerprint: Mapped[str] = mapped_column(String(64))
    findings: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    impact: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    priority: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    priority_score: Mapped[float] = mapped_column(Float, default=0, index=True)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = _ts()
    last_seen_at: Mapped[datetime] = _ts()
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _ts()
    __table_args__ = (
        Index("ix_incident_fingerprint_status", "workspace_id", "fingerprint", "status"),
        CheckConstraint("status in ('open','acknowledged','investigating','resolved','reopened')", name="ck_incident_status"),
    )


class IncidentEvent(Base):
    """Timeline entries for an incident (state changes, detections, remediation steps)."""

    __tablename__ = "incident_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_label: Mapped[str] = mapped_column(String(80), default="system")
    created_at: Mapped[datetime] = _ts()


class IncidentComment(Base):
    __tablename__ = "incident_comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()


class RemediationProposal(Base):
    __tablename__ = "remediation_proposals"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    version_id: Mapped[int | None] = mapped_column(ForeignKey("dataset_versions.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(40))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    preconditions: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    expected_outcome: Mapped[str] = mapped_column(Text)
    rollback: Mapped[str] = mapped_column(Text, default="")
    risk_level: Mapped[str] = mapped_column(String(8))
    execution_mode: Mapped[str] = mapped_column(String(16))  # recommend | approval | auto
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(24), default="proposed")
    # proposed | approved | rejected | executing | verified | verification_failed | failed | recommended_only
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RemediationExecution(Base):
    __tablename__ = "remediation_executions"
    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("remediation_proposals.id", ondelete="CASCADE"), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))  # running | succeeded | failed | timed_out
    started_at: Mapped[datetime] = _ts()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    verification: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    executed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    name: Mapped[str] = mapped_column(String(160))
    job_type: Mapped[str] = mapped_column(String(32))  # profile | validate | drift | monitor | model_eval | maintenance
    target_id: Mapped[int | None] = mapped_column(Integer)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    interval_seconds: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    retry_backoff_seconds: Mapped[int] = mapped_column(Integer, default=60)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(16))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = _ts()
    __table_args__ = (CheckConstraint("interval_seconds >= 60", name="ck_job_interval"),)


class JobExecution(Base):
    __tablename__ = "job_executions"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("scheduled_jobs.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[int] = _ws_fk()
    job_type: Mapped[str] = mapped_column(String(32))
    trigger: Mapped[str] = mapped_column(String(16))  # schedule | manual | external | retry
    status: Mapped[str] = mapped_column(String(16))  # queued | running | succeeded | failed | timed_out
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float | None] = mapped_column(Float)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    worker: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = _ts()


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16), default="info")
    title: Mapped[str] = mapped_column(String(240))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(240))
    dedup_key: Mapped[str | None] = mapped_column(String(120), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_status: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = _ts()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_api_key_id: Mapped[int | None] = mapped_column(ForeignKey("api_keys.id", ondelete="SET NULL"))
    actor_label: Mapped[str] = mapped_column(String(120), default="system")
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(40))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _ts()
    __table_args__ = (Index("ix_audit_entity", "workspace_id", "entity_type", "entity_id"),)
