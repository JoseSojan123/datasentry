"""Typed result objects returned by the SDK. They wrap the raw API payload (available as ``.raw``)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Version:
    id: int
    dataset_id: int
    version_number: int
    status: str
    ingestion_status: str
    row_count: int | None
    column_count: int | None
    checksum: str | None
    columns: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Version:
        return cls(d["id"], d["dataset_id"], d["version_number"], d["status"], d["ingestion_status"], d.get("row_count"),
                   d.get("column_count"), d.get("checksum"), d.get("columns", []), d)


@dataclass
class MonitoringResult:
    status: str
    findings: list[dict[str, Any]]
    incident_id: int | None
    proposal_ids: list[int]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, d: dict[str, Any] | None) -> MonitoringResult | None:
        if not d:
            return None
        return cls(d.get("status", "unknown"), d.get("findings", []), d.get("incident_id"), d.get("proposal_ids", []), d)

    @property
    def healthy(self) -> bool:
        return self.status == "healthy"


@dataclass
class Dataset:
    id: int
    name: str
    description: str | None
    health: str
    current_version_id: int | None
    reference_version_id: int | None
    criticality: str
    current_version: Version | None = None
    monitoring: MonitoringResult | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, d: dict[str, Any], monitoring: dict[str, Any] | None = None) -> Dataset:
        cv = d.get("current_version")
        return cls(d["id"], d["name"], d.get("description"), d.get("health", "unknown"), d.get("current_version_id"),
                   d.get("reference_version_id"), d.get("criticality", "medium"), Version.from_api(cv) if cv else None,
                   MonitoringResult.from_api(monitoring), d)


@dataclass
class Profile:
    id: int
    version_id: int
    summary: dict[str, Any]
    columns: dict[str, dict[str, Any]]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Profile:
        return cls(d["id"], d["version_id"], d["summary"], d["columns"], d)

    @property
    def row_count(self) -> int:
        return int(self.summary.get("row_count", 0))

    def column(self, name: str) -> dict[str, Any]:
        return self.columns[name]


@dataclass
class RuleResult:
    rule_id: int | None
    rule_type: str
    columns: list[str]
    status: str
    rows_evaluated: int
    failed_rows: int | None
    failure_pct: float | None
    explanation: str
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def passed(self) -> bool:
        return self.status == "pass"


@dataclass
class ValidationResult:
    run_id: int
    version_id: int
    summary: dict[str, Any]
    results: list[RuleResult]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> ValidationResult:
        results = [RuleResult(r.get("rule_id"), r["rule"]["rule_type"], r["rule"].get("columns", []), r["status"],
                              r["rows_evaluated"], r.get("failed_rows"), r.get("failure_pct"), r["explanation"], r)
                   for r in d.get("results", [])]
        return cls(d["id"], d["version_id"], d["summary"], results, d)

    @property
    def passed(self) -> bool:
        return self.summary.get("failed", 0) == 0 and self.summary.get("errored", 0) == 0

    @property
    def failures(self) -> list[RuleResult]:
        return [r for r in self.results if r.status != "pass"]


@dataclass
class DriftResult:
    id: int
    overall_severity: str
    summary: dict[str, Any]
    features: list[dict[str, Any]]
    other_findings: list[dict[str, Any]]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> DriftResult:
        return cls(d["id"], d["overall_severity"], d["summary"], d.get("features", []), d.get("other_findings", []), d)

    @property
    def drifted_features(self) -> list[str]:
        return [f["feature"] for f in self.features if f["status"] == "drift"]

    def feature(self, name: str) -> dict[str, Any]:
        return next(f for f in self.features if f["feature"] == name)


@dataclass
class Model:
    id: int
    name: str
    task: str
    versions: list[dict[str, Any]]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Model:
        return cls(d["id"], d["name"], d["task"], d.get("versions", []), d)


@dataclass
class ModelEvaluation:
    id: int
    status: str
    n_predictions: int
    n_labelled: int
    label_coverage: float
    metrics: dict[str, Any]
    performance: dict[str, Any]
    input_drift: dict[str, Any]
    prediction_drift: dict[str, Any]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> ModelEvaluation:
        return cls(d["id"], d["status"], d["n_predictions"], d["n_labelled"], d["label_coverage"], d["metrics"],
                   d["performance"], d["input_drift"], d["prediction_drift"], d)


@dataclass
class Incident:
    id: int
    title: str
    severity: str
    status: str
    findings: list[dict[str, Any]]
    impact: dict[str, Any]
    priority: dict[str, Any]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Incident:
        return cls(d["id"], d["title"], d["severity"], d["status"], d.get("findings", []), d.get("impact", {}),
                   d.get("priority", {}), d)
