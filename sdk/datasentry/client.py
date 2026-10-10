from __future__ import annotations

import io
import json
import os
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from .types import (
    Dataset,
    DriftResult,
    Incident,
    Model,
    ModelEvaluation,
    MonitoringResult,
    Profile,
    ValidationResult,
    Version,
)

DEFAULT_TIMEOUT = 120.0
PREDICTION_BATCH = 5000


class DataSentryError(Exception):
    """Raised for non-2xx responses. Carries the API's structured error."""

    def __init__(self, status: int, code: str, message: str, details: Any = None, request_id: str | None = None):
        super().__init__(f"[{status} {code}] {message}" + (f" (request {request_id})" if request_id else ""))
        self.status, self.code, self.message, self.details, self.request_id = status, code, message, details, request_id


def _iso(v: datetime | str | None) -> str | None:
    if v is None or isinstance(v, str):
        return v
    return v.isoformat()


class DataSentry:
    """Client for the DataSentry REST API.

    >>> client = DataSentry(api_url="http://localhost:8000", api_key="dsk_…")
    >>> ds = client.register_dataset(name="customer_events", data=df)
    >>> client.validate(ds.id, rules=[{"type": "not_null", "column": "customer_id"}]).summary
    """

    def __init__(self, api_url: str | None = None, api_key: str | None = None, timeout: float = DEFAULT_TIMEOUT,
                 http_client: httpx.Client | None = None):
        self.api_url = (api_url or os.environ.get("DATASENTRY_API_URL") or "http://localhost:8000").rstrip("/")
        key = api_key or os.environ.get("DATASENTRY_API_KEY")
        headers = {"User-Agent": "datasentry-python/0.1.0"}
        if key:
            headers["X-API-Key"] = key
        if http_client is not None:  # e.g. FastAPI's TestClient in tests
            self._http = http_client
            self._http.headers.update(headers)
            self._base = "/api/v1"
        else:
            self._http = httpx.Client(base_url=self.api_url, headers=headers, timeout=timeout)
            self._base = "/api/v1"

    # ------------------------------------------------------------------ plumbing
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> DataSentry:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _request(self, method: str, path: str, **kw: Any) -> Any:
        resp = self._http.request(method, self._base + path, **kw)
        if resp.status_code >= 400:
            try:
                err = resp.json().get("error", {})
            except ValueError:
                err = {}
            raise DataSentryError(resp.status_code, err.get("code", "http_error"), err.get("message", resp.text[:200]),
                                  err.get("details"), err.get("request_id"))
        return resp.json() if resp.content else None

    @staticmethod
    def _file_payload(data: Any, name: str) -> tuple[str, bytes, str]:
        if isinstance(data, str | Path):
            p = Path(data)
            return p.name, p.read_bytes(), "application/octet-stream"
        if hasattr(data, "to_csv"):  # pandas DataFrame
            buf = io.StringIO()
            data.to_csv(buf, index=False)
            return f"{name}.csv", buf.getvalue().encode(), "text/csv"
        if isinstance(data, list):
            import csv

            buf = io.StringIO()
            if data:
                w = csv.DictWriter(buf, fieldnames=list(data[0].keys()))
                w.writeheader()
                w.writerows(data)
            return f"{name}.csv", buf.getvalue().encode(), "text/csv"
        raise TypeError("data must be a pandas DataFrame, a list of dicts, or a path to a CSV/Parquet file")

    # ------------------------------------------------------------------ datasets
    def register_dataset(self, name: str, data: Any = None, description: str | None = None, owner: str | None = None,
                         tags: Sequence[str] = (), domain: str | None = None, criticality: str = "medium",
                         primary_key: Sequence[str] = (), freshness_column: str | None = None, encoding: str = "utf-8") -> Dataset:
        """Register a dataset; if ``data`` is given it is uploaded as version 1 and monitored."""
        meta = {"name": name, "description": description, "owner": owner, "tags": list(tags), "domain": domain,
                "criticality": criticality, "primary_key": list(primary_key), "freshness_column": freshness_column}
        if data is None:
            return Dataset.from_api(self._request("POST", "/datasets", json=meta))
        out = self._request("POST", "/datasets/upload", files={"file": self._file_payload(data, name)},
                            data={"metadata": json.dumps(meta), "encoding": encoding})
        return Dataset.from_api(out["dataset"], out.get("monitoring"))

    def get_dataset(self, dataset: int | str) -> Dataset:
        if isinstance(dataset, str):
            items = self._request("GET", "/datasets", params={"q": dataset, "page_size": 200})["items"]
            match = next((d for d in items if d["name"] == dataset), None)
            if match is None:
                raise DataSentryError(404, "not_found", f"Dataset '{dataset}' not found")
            return Dataset.from_api(match)
        return Dataset.from_api(self._request("GET", f"/datasets/{dataset}"))

    def list_datasets(self, query: str | None = None, page: int = 1, page_size: int = 50) -> list[Dataset]:
        params = {"page": page, "page_size": page_size, **({"q": query} if query else {})}
        return [Dataset.from_api(d) for d in self._request("GET", "/datasets", params=params)["items"]]

    def create_version(self, dataset_id: int, data: Any, run_monitoring: bool = True, encoding: str = "utf-8") -> tuple[Version, MonitoringResult | None]:
        """Upload a new version of a dataset. Returns the version and the monitoring outcome."""
        out = self._request("POST", f"/datasets/{dataset_id}/versions", files={"file": self._file_payload(data, "batch")},
                            data={"encoding": encoding, "run_monitoring": str(run_monitoring).lower()})
        return Version.from_api(out["version"]), MonitoringResult.from_api(out.get("monitoring"))

    def versions(self, dataset_id: int) -> list[Version]:
        return [Version.from_api(v) for v in self._request("GET", f"/datasets/{dataset_id}/versions", params={"page_size": 200})["items"]]

    def profile(self, dataset_id: int, version_id: int | None = None, recompute: bool = False) -> Profile:
        vid = version_id or self._request("GET", f"/datasets/{dataset_id}")["current_version_id"]
        if vid is None:
            raise DataSentryError(409, "no_version", "Dataset has no active version")
        if recompute:
            return Profile.from_api(self._request("POST", f"/versions/{vid}/profile"))
        return Profile.from_api(self._request("GET", f"/versions/{vid}/profile"))

    # ------------------------------------------------------------------ rules
    def add_rule(self, dataset_id: int, rule_type: str, columns: Sequence[str] = (), config: dict[str, Any] | None = None,
                 severity: str = "warning", name: str | None = None) -> dict[str, Any]:
        return self._request("POST", f"/datasets/{dataset_id}/rules", json={
            "name": name or f"{rule_type} {', '.join(columns)}".strip(), "rule_type": rule_type, "columns": list(columns),
            "config": config or {}, "severity": severity})

    def rules(self, dataset_id: int) -> list[dict[str, Any]]:
        return self._request("GET", f"/datasets/{dataset_id}/rules")["items"]

    def validate(self, dataset_id: int, rules: list[dict[str, Any]] | None = None, version_id: int | None = None,
                 only_inline: bool | None = None) -> ValidationResult:
        """Execute rules. Inline ``rules`` (``{"type": ..., "column": ...}``) are created if new and, by default,
        are the only rules run; pass ``only_inline=False`` to run them together with the dataset's saved rules."""
        body = {"version_id": version_id, "rules": rules,
                "only_inline": bool(rules) if only_inline is None else only_inline}
        return ValidationResult.from_api(self._request("POST", f"/datasets/{dataset_id}/validate", json=body))

    # ------------------------------------------------------------------ drift / comparison
    def compare_drift(self, dataset_id: int, reference_version_id: int | None = None, current_version_id: int | None = None,
                      config: dict[str, Any] | None = None, window_column: str | None = None,
                      reference_window: tuple[Any, Any] | None = None, current_window: tuple[Any, Any] | None = None) -> DriftResult:
        body: dict[str, Any] = {"reference_version_id": reference_version_id, "current_version_id": current_version_id,
                                "config": config or {}, "window_column": window_column}
        if reference_window:
            body["reference_start"], body["reference_end"] = map(_iso, reference_window)
        if current_window:
            body["current_start"], body["current_end"] = map(_iso, current_window)
        return DriftResult.from_api(self._request("POST", f"/datasets/{dataset_id}/drift", json=body))

    def compare_versions(self, dataset_id: int, base_version_id: int, target_version_id: int) -> dict[str, Any]:
        return self._request("POST", f"/datasets/{dataset_id}/compare",
                             json={"base_version_id": base_version_id, "target_version_id": target_version_id})

    # ------------------------------------------------------------------ models
    def register_model(self, name: str, task: str, description: str | None = None, target: str | None = None,
                       positive_label: Any = None, reference_dataset_id: int | None = None, criticality: str = "medium",
                       owner: str | None = None) -> Model:
        return Model.from_api(self._request("POST", "/models", json={
            "name": name, "task": task, "description": description, "target": target,
            "positive_label": None if positive_label is None else str(positive_label),
            "reference_dataset_id": reference_dataset_id, "criticality": criticality, "owner": owner}))

    def create_model_version(self, model_id: int, version: str, input_schema: list[dict[str, Any]] | None = None,
                             baseline_metrics: dict[str, Any] | None = None, artifact: dict[str, Any] | None = None,
                             feature_logging: str | None = None, retention_days: int | None = None) -> dict[str, Any]:
        return self._request("POST", f"/models/{model_id}/versions", json={
            "version": version, "input_schema": input_schema or [], "baseline_metrics": baseline_metrics or {},
            "artifact": artifact or {}, "feature_logging": feature_logging, "retention_days": retention_days})

    def log_predictions(self, model_id: int, model_version: str, predictions: Iterable[dict[str, Any]]) -> dict[str, int]:
        """Log predictions in batches. Each item: record_id, prediction, optional timestamp, features, score, label."""
        totals = {"accepted": 0, "duplicates": 0, "schema_violations": 0}
        batch: list[dict[str, Any]] = []

        def flush() -> None:
            if batch:
                out = self._request("POST", f"/models/{model_id}/predictions", json={"model_version": model_version, "predictions": batch})
                for k in totals:
                    totals[k] += out.get(k, 0)
                batch.clear()

        for p in predictions:
            item = {**p, "timestamp": _iso(p.get("timestamp"))}
            batch.append({k: v for k, v in item.items() if v is not None or k == "label"})
            if len(batch) >= PREDICTION_BATCH:
                flush()
        flush()
        return totals

    def log_labels(self, model_id: int, model_version: str, labels: Iterable[dict[str, Any]]) -> dict[str, Any]:
        return self._request("POST", f"/models/{model_id}/labels", json={
            "model_version": model_version, "labels": [{**x, "labeled_at": _iso(x.get("labeled_at"))} for x in labels]})

    def evaluate_model(self, model_id: int, model_version: str, current_window: tuple[Any, Any] | None = None,
                       reference_window: tuple[Any, Any] | None = None) -> ModelEvaluation:
        body: dict[str, Any] = {"model_version": model_version}
        if current_window:
            body["current_start"], body["current_end"] = map(_iso, current_window)
        if reference_window:
            body["reference_start"], body["reference_end"] = map(_iso, reference_window)
        return ModelEvaluation.from_api(self._request("POST", f"/models/{model_id}/evaluate", json=body))

    # ------------------------------------------------------------------ lineage
    def add_lineage_node(self, name: str, node_type: str, criticality: str = "medium", description: str | None = None,
                         owner: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/lineage/nodes", json={"name": name, "node_type": node_type, "criticality": criticality,
                                                              "description": description, "owner": owner})

    def lineage_graph(self) -> dict[str, Any]:
        return self._request("GET", "/lineage/graph")

    def node_id(self, *, dataset_id: int | None = None, model_id: int | None = None, name: str | None = None) -> int:
        for n in self.lineage_graph()["nodes"]:
            if (dataset_id and n["dataset_id"] == dataset_id) or (model_id and n["model_id"] == model_id) or (name and n["name"] == name):
                return n["id"]
        raise DataSentryError(404, "not_found", "Lineage node not found")

    def register_lineage(self, source_id: int, target_id: int, dependency_type: str = "reads", provenance: str = "declared",
                         meta: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("POST", "/lineage/edges", json={"source_id": source_id, "target_id": target_id,
                                                              "dependency_type": dependency_type, "provenance": provenance,
                                                              "meta": meta or {}})

    def impact(self, node_id: int) -> dict[str, Any]:
        return self._request("GET", f"/lineage/nodes/{node_id}/impact")

    # ------------------------------------------------------------------ incidents
    def incidents(self, status: str | Sequence[str] | None = None, dataset_id: int | None = None,
                  severity: str | None = None, page_size: int = 50) -> list[Incident]:
        params: dict[str, Any] = {"page_size": page_size}
        if status:
            params["status"] = status if isinstance(status, str) else ",".join(status)
        if dataset_id:
            params["dataset_id"] = dataset_id
        if severity:
            params["severity"] = severity
        return [Incident.from_api(i) for i in self._request("GET", "/incidents", params=params)["items"]]

    def get_incident(self, incident_id: int) -> Incident:
        return Incident.from_api(self._request("GET", f"/incidents/{incident_id}"))
