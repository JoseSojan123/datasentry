# API reference

Generated from the OpenAPI schema by `scripts/gen_api_reference.py`. The interactive reference with request and response models is served by the API at `/api/docs` (Swagger UI) and `/api/redoc`; the raw schema is at `/api/openapi.json`.

**Authentication:** `Authorization: Bearer <token>` (from `POST /api/v1/auth/login`, `/auth/register` or `/auth/demo`) or `X-API-Key: dsk_…` (Settings → API keys). Viewers can read; changes need the editor role; members, API keys, workspace settings and the audit log need admin.

**Errors** always look like `{"error": {"code", "message", "details", "request_id"}}`. Rate-limited requests return 429 with `Retry-After`.

**Pagination:** list endpoints take `page` and `page_size` and return `{items, total, page, page_size, pages}`.

## Auth

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/api-keys` | List API keys (secrets are never returned) |
| POST | `/api/v1/api-keys` | Create an API key; the secret is shown only once |
| DELETE | `/api/v1/api-keys/{key_id}` | Revoke an API key |
| POST | `/api/v1/auth/demo` | Create an isolated, expiring demo workspace (optionally with synthetic sample data) |
| POST | `/api/v1/auth/login` | Exchange email and password for a token |
| GET | `/api/v1/auth/me` | Current user, workspace and role |
| PATCH | `/api/v1/auth/me/preferences` | Update notification and UI preferences |
| POST | `/api/v1/auth/register` | Create a workspace and its first (admin) user |
| GET | `/api/v1/users` | List users in the workspace |
| POST | `/api/v1/users` | Add a user to the workspace (admin) |
| PATCH | `/api/v1/users/{user_id}/role` | Change a user's role (admin) |

## Datasets

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/datasets` | List datasets with search, filters and sorting |
| POST | `/api/v1/datasets` | Register a dataset (metadata only) |
| POST | `/api/v1/datasets/upload` | Register a dataset and upload its first version in one request |
| DELETE | `/api/v1/datasets/{dataset_id}` | Delete a dataset and its history (admin) |
| GET | `/api/v1/datasets/{dataset_id}` | Dataset detail |
| PATCH | `/api/v1/datasets/{dataset_id}` | Update dataset metadata |
| POST | `/api/v1/datasets/{dataset_id}/compare` | Compare two versions (schema, nulls, categories, rows) |
| GET | `/api/v1/datasets/{dataset_id}/comparisons` | Comparison history |
| GET | `/api/v1/datasets/{dataset_id}/drift` | Drift evaluation history |
| POST | `/api/v1/datasets/{dataset_id}/drift` | Run a drift comparison between two versions or time windows |
| GET | `/api/v1/datasets/{dataset_id}/lineage-impact` | Downstream impact if this dataset fails |
| GET | `/api/v1/datasets/{dataset_id}/profile-history` | Dataset-level profile metrics over versions |
| GET | `/api/v1/datasets/{dataset_id}/rename-decisions` | Rename decisions for a dataset |
| POST | `/api/v1/datasets/{dataset_id}/rename-decisions` | Confirm or reject a potential column rename |
| PUT | `/api/v1/datasets/{dataset_id}/settings` | Update monitoring, drift, schema-change and remediation policy |
| GET | `/api/v1/datasets/{dataset_id}/versions` | Version history |
| POST | `/api/v1/datasets/{dataset_id}/versions` | Upload a new version (file) and run monitoring |
| POST | `/api/v1/datasets/{dataset_id}/versions/records` | Create a version from JSON records (used by the SDK) |
| GET | `/api/v1/drift` | Recent drift evaluations across the workspace |
| GET | `/api/v1/drift/{evaluation_id}` | Drift evaluation with per-feature evidence |
| GET | `/api/v1/versions/{version_id}` | Version detail with schema |
| GET | `/api/v1/versions/{version_id}/download` | Download the normalised data of a version as CSV |
| POST | `/api/v1/versions/{version_id}/monitor` | Re-run the full monitoring pipeline on a version |
| GET | `/api/v1/versions/{version_id}/preview` | Paginated rows of a version (nulls preserved) |
| GET | `/api/v1/versions/{version_id}/profile` | Latest profile of a version |
| POST | `/api/v1/versions/{version_id}/profile` | Recompute the profile of a version |
| POST | `/api/v1/versions/{version_id}/promote` | Make a version active (manual override, audited) |

## Demo

| Method | Path | Summary |
|---|---|---|
| POST | `/api/v1/demo/sample-data` | Load the labelled synthetic sample data |
| GET | `/api/v1/demo/scenarios` | Synthetic anomaly scenarios that can be loaded |
| POST | `/api/v1/demo/scenarios/{name}` | Load one synthetic scenario as a dataset |

## Health

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/health` | Liveness (no configuration exposed) |
| GET | `/api/v1/ready` | Readiness: database reachable and migrated |

## Incidents & remediation

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/incidents` | Incidents with filters, search and priority sorting |
| GET | `/api/v1/incidents/{incident_id}` | Incident with timeline, comments, evidence and remediation |
| POST | `/api/v1/incidents/{incident_id}/assign` | Assign or unassign an incident |
| POST | `/api/v1/incidents/{incident_id}/comments` | Comment on an incident |
| GET | `/api/v1/incidents/{incident_id}/investigation` | Lineage subgraph for the incident investigation view |
| POST | `/api/v1/incidents/{incident_id}/status` | Change incident status (resolution requires a note) |
| GET | `/api/v1/remediations` | Remediation proposals across incidents |
| GET | `/api/v1/remediations/catalog` | Available remediation actions and their risk levels |
| GET | `/api/v1/remediations/{proposal_id}` | Proposal with executions and verification |
| POST | `/api/v1/remediations/{proposal_id}/approve` | Approve a proposal |
| POST | `/api/v1/remediations/{proposal_id}/execute` | Execute an approved proposal and verify the result |
| POST | `/api/v1/remediations/{proposal_id}/reject` | Reject a proposal |
| GET | `/api/v1/settings/remediation` | Workspace remediation policy |
| PUT | `/api/v1/settings/remediation` | Set remediation mode and auto-execution allowlist (admin) |

## Jobs

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/jobs` | Scheduled jobs with last/next run |
| POST | `/api/v1/jobs` | Create a scheduled job |
| GET | `/api/v1/jobs/executions` | Job execution history |
| POST | `/api/v1/jobs/run-due` | Run due jobs (for external cron triggers; needs X-Cron-Secret) |
| DELETE | `/api/v1/jobs/{job_id}` | Delete a job |
| PATCH | `/api/v1/jobs/{job_id}` | Update or pause a job |
| POST | `/api/v1/jobs/{job_id}/run` | Run a job now (overlap-protected) |

## Lineage

| Method | Path | Summary |
|---|---|---|
| POST | `/api/v1/lineage/edges` | Declare a dependency (rejected if it would create a cycle) |
| DELETE | `/api/v1/lineage/edges/{edge_id}` | Remove a dependency |
| GET | `/api/v1/lineage/graph` | Full lineage graph with validation issues |
| POST | `/api/v1/lineage/nodes` | Declare a transformation, feature table, report or consumer |
| DELETE | `/api/v1/lineage/nodes/{node_id}` | Delete a declared node and its edges |
| PATCH | `/api/v1/lineage/nodes/{node_id}` | Update node criticality/owner/description |
| GET | `/api/v1/lineage/nodes/{node_id}/impact` | Downstream impact of a node |
| GET | `/api/v1/lineage/nodes/{node_id}/upstream` | Upstream dependencies of a node |

## Models

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/models` | Model registry |
| POST | `/api/v1/models` | Register a model |
| GET | `/api/v1/models/{model_id}` | Model detail |
| POST | `/api/v1/models/{model_id}/evaluate` | Evaluate performance, input drift and prediction drift |
| GET | `/api/v1/models/{model_id}/evaluations` | Evaluation history |
| POST | `/api/v1/models/{model_id}/labels` | Attach (possibly delayed) ground-truth labels |
| GET | `/api/v1/models/{model_id}/predictions` | Recent prediction records (features shown only with full logging) |
| POST | `/api/v1/models/{model_id}/predictions` | Log a batch of predictions (idempotent on record_id) |
| GET | `/api/v1/models/{model_id}/series` | Daily prediction volume, label coverage and mean score |
| POST | `/api/v1/models/{model_id}/versions` | Register a model version with schema and baseline metrics |

## Notifications

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/notifications` | In-app notifications |
| POST | `/api/v1/notifications/read-all` | Mark All Read |
| POST | `/api/v1/notifications/{notification_id}/read` | Mark Read |

## Overview

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/activity` | Recent activity feed |
| GET | `/api/v1/audit` | Audit log (admin) |
| GET | `/api/v1/overview` | Dashboard metrics computed from stored records |
| GET | `/api/v1/search` | Search datasets, models, incidents and lineage nodes |

## Quality rules

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/check-runs/{run_id}` | One rule execution run with all results |
| GET | `/api/v1/datasets/{dataset_id}/check-runs` | Rule execution runs for a dataset |
| GET | `/api/v1/datasets/{dataset_id}/rules` | Rules of a dataset with their latest result |
| POST | `/api/v1/datasets/{dataset_id}/rules` | Create a rule |
| POST | `/api/v1/datasets/{dataset_id}/validate` | Execute rules against a version |
| GET | `/api/v1/rule-types` | Supported rule types with their JSON configuration schemas |
| DELETE | `/api/v1/rules/{rule_id}` | Delete a rule (its execution history is removed too) |
| PATCH | `/api/v1/rules/{rule_id}` | Update a rule |
| GET | `/api/v1/rules/{rule_id}/history` | Execution history of one rule |
