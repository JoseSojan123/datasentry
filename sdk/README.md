# DataSentry Python SDK

Typed client for the DataSentry REST API. Every method maps to a documented `/api/v1` endpoint; nothing is computed or faked client-side.

## Install

```bash
pip install -e sdk            # from the repository root
pip install -e "sdk[pandas]"  # to pass pandas DataFrames
```

## Authenticate

Create an API key in the UI (**Settings → API keys**) or via `POST /api/v1/api-keys`. Keys are shown once and stored hashed.

```python
from datasentry import DataSentry

client = DataSentry(api_url="http://localhost:8000", api_key="dsk_xxxxxxxx_…")
# or set DATASENTRY_API_URL / DATASENTRY_API_KEY and call DataSentry()
```

## Usage

```python
dataset = client.register_dataset(name="customer_events", data=df, description="Customer activity dataset")
profile = client.profile(dataset.id)
result = client.validate(dataset.id, rules=[
    {"type": "not_null", "column": "customer_id"},
    {"type": "unique", "column": "customer_id"},
])
print(result.summary)          # {'total': 2, 'passed': 2, 'failed': 0, ...}

version, monitoring = client.create_version(dataset.id, new_df)   # runs rules, schema diff and drift
drift = client.compare_drift(dataset.id)                           # reference vs current version
model = client.register_model("churn", "classification", positive_label=1, reference_dataset_id=dataset.id)
client.create_model_version(model.id, "1.0", input_schema=[{"name": "spend", "type": "numeric"}])
client.log_predictions(model.id, "1.0", [{"record_id": "r1", "prediction": 1, "score": 0.81, "features": {"spend": 42.0}}])
client.log_labels(model.id, "1.0", [{"record_id": "r1", "label": 0}])
evaluation = client.evaluate_model(model.id, "1.0")
client.register_lineage(source_id, target_id, "reads")
open_incidents = client.incidents(status="open")
```

| Method | Endpoint |
| --- | --- |
| `register_dataset` | `POST /datasets/upload` (or `POST /datasets` without data) |
| `create_version` | `POST /datasets/{id}/versions` |
| `profile` | `GET/POST /versions/{id}/profile` |
| `add_rule`, `validate` | `POST /datasets/{id}/rules`, `POST /datasets/{id}/validate` |
| `compare_drift`, `compare_versions` | `POST /datasets/{id}/drift`, `POST /datasets/{id}/compare` |
| `register_model`, `create_model_version` | `POST /models`, `POST /models/{id}/versions` |
| `log_predictions`, `log_labels`, `evaluate_model` | `POST /models/{id}/predictions`, `/labels`, `/evaluate` |
| `add_lineage_node`, `register_lineage`, `impact` | `POST /lineage/nodes`, `POST /lineage/edges`, `GET /lineage/nodes/{id}/impact` |
| `incidents`, `get_incident` | `GET /incidents`, `GET /incidents/{id}` |

Errors raise `DataSentryError` with `status`, `code`, `message`, `details` and `request_id`.

## Examples

* `examples/quickstart.py` – register, profile, validate, upload a drifted batch, read the incident.
* `examples/public_dataset_model.py` – scikit-learn model on the public Breast Cancer Wisconsin dataset with input drift, delayed labels and evaluation.

## Tests

The SDK tests run the real API in-process (needs the backend environment and a PostgreSQL test database):

```bash
cd sdk && python -m pytest
```
