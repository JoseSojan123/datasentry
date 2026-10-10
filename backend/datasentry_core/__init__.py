"""DataSentry detection engine.

Pure-Python, framework-independent algorithms for profiling, data-quality rules,
statistical drift, schema comparison, model metrics, lineage traversal, impact
scoring and remediation policy. Nothing in this package imports FastAPI or the
database layer, so it can be reused from the API, the worker, the SDK and tests.
"""

__all__ = [
    "io",
    "profiling",
    "rules",
    "drift",
    "schema_diff",
    "model_metrics",
    "lineage",
    "impact",
    "remediation",
    "synthetic",
]
