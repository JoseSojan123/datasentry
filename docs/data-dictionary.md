# Data dictionary

Generated from `backend/app/db/models.py` by `scripts/gen_data_dictionary.py`. Do not edit by hand.

Every table except `workspaces` carries a `workspace_id` (directly or through its parent) and every API query is scoped to the caller's workspace. Timestamps are stored in UTC.

| Table | Purpose |
|---|---|
| [`workspaces`](#workspaces) | Tenant boundary. Demo workspaces carry an expiry and are purged by maintenance. |
| [`datasets`](#datasets) | Monitored datasets with owner, criticality, settings (gate mode, thresholds, policies) and health. |
| [`scheduled_jobs`](#scheduled-jobs) | Recurring profile, validate, drift, monitor and model-evaluation jobs. |
| [`stored_files`](#stored-files) | Blob storage for the ``database`` storage backend (small demo deployments only). |
| [`users`](#users) | Accounts with a role (admin, editor, viewer) in one workspace; scrypt password hash. |
| [`api_keys`](#api-keys) | SDK and automation keys; only an HMAC of the key is stored. |
| [`column_rename_decisions`](#column-rename-decisions) | User confirmations or rejections of rename candidates. |
| [`dataset_versions`](#dataset-versions) | Each uploaded or derived batch: ingestion result, checksum, status, lineage to its parent version. |
| [`job_executions`](#job-executions) | Job run history with status, duration, retries and errors. |
| [`ml_models`](#ml-models) | Registered models (task, target, positive label, reference dataset, criticality). |
| [`notifications`](#notifications) | In-app notifications (and email, when SMTP is configured). |
| [`quality_rules`](#quality-rules) | Validated rule definitions (type, columns, config, severity). |
| [`audit_events`](#audit-events) | Append-only record of security-relevant and state-changing actions. |
| [`dataset_schema_columns`](#dataset-schema-columns) | Inferred schema of a version (semantic and physical type per column). |
| [`drift_evaluations`](#drift-evaluations) | One drift comparison between a reference and a current version, with config and summary. |
| [`incidents`](#incidents) | Deduplicated incidents with findings, impact, priority, assignment and resolution. |
| [`lineage_nodes`](#lineage-nodes) | Datasets, transformations, feature tables, models, reports and consumers. |
| [`model_versions`](#model-versions) | Model versions with input schema, baseline metrics and feature-logging policy. |
| [`profiles`](#profiles) | Per-version profile: summary and per-column statistics, with the config used. |
| [`quality_check_runs`](#quality-check-runs) | One execution of a dataset's rule set against a version. |
| [`version_comparisons`](#version-comparisons) | Schema and profile diff between two versions, including rename candidates. |
| [`drift_feature_results`](#drift-feature-results) | Per-feature drift statistics, corrected p-values, status and evidence. |
| [`incident_comments`](#incident-comments) | Investigation notes from editors. |
| [`incident_events`](#incident-events) | Timeline entries for an incident (state changes, detections, remediation steps). |
| [`lineage_edges`](#lineage-edges) | Dependencies with provenance (confirmed, declared, inferred). |
| [`model_evaluations`](#model-evaluations) | Windowed model evaluation: metrics with intervals, input and prediction drift, status. |
| [`prediction_batches`](#prediction-batches) | Aggregated per-batch feature statistics used when raw feature logging is disabled. |
| [`prediction_records`](#prediction-records) | Logged predictions and delayed labels (raw features only with full logging). |
| [`quality_check_results`](#quality-check-results) | Per-rule outcome of a run: rows evaluated, failures, observed vs expected, samples, explanation. |
| [`remediation_proposals`](#remediation-proposals) | Proposed actions with preconditions, risk, mode and approval state. |
| [`remediation_executions`](#remediation-executions) | Each execution attempt with its result and post-action verification. |

## workspaces

Tenant boundary. Demo workspaces carry an expiry and are purged by maintenance.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `name` | varchar(120) | no |  |
| `is_demo` | boolean | no | default `False` |
| `expires_at` | datetime | yes |  |
| `settings` | jsonb | no |  |
| `created_at` | datetime | no |  |

## datasets

Monitored datasets with owner, criticality, settings (gate mode, thresholds, policies) and health.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `workspace_id` | integer | no | FK → `workspaces.id` (cascade) |
| `name` | varchar(120) | no |  |
| `description` | text | yes |  |
| `owner` | varchar(120) | yes |  |
| `tags` | jsonb | no |  |
| `domain` | varchar(80) | yes |  |
| `criticality` | varchar(16) | no | default `medium` |
| `source_type` | varchar(16) | no | default `upload` |
| `primary_key` | jsonb | no |  |
| `freshness_column` | varchar(128) | yes |  |
| `reference_version_id` | integer | yes | FK → `dataset_versions.id` (set null) |
| `current_version_id` | integer | yes | FK → `dataset_versions.id` (set null) |
| `settings` | jsonb | no |  |
| `health` | varchar(16) | no | default `unknown` |
| `created_at` | datetime | no |  |
| `updated_at` | datetime | no |  |

Indexes and constraints: `ix_datasets_workspace_id` (workspace_id); `uq_dataset_name` (workspace_id, name)

## scheduled_jobs

Recurring profile, validate, drift, monitor and model-evaluation jobs.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `workspace_id` | integer | no | FK → `workspaces.id` (cascade) |
| `name` | varchar(160) | no |  |
| `job_type` | varchar(32) | no |  |
| `target_id` | integer | yes |  |
| `params` | jsonb | no |  |
| `interval_seconds` | integer | no |  |
| `enabled` | boolean | no | default `True` |
| `max_retries` | integer | no | default `2` |
| `retry_backoff_seconds` | integer | no | default `60` |
| `timeout_seconds` | integer | no | default `300` |
| `next_run_at` | datetime | no |  |
| `last_run_at` | datetime | yes |  |
| `last_success_at` | datetime | yes |  |
| `last_status` | varchar(16) | yes |  |
| `consecutive_failures` | integer | no | default `0` |
| `locked_until` | datetime | yes |  |
| `locked_by` | varchar(80) | yes |  |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_scheduled_jobs_next_run_at` (next_run_at); `ix_scheduled_jobs_workspace_id` (workspace_id)

## stored_files

Blob storage for the ``database`` storage backend (small demo deployments only).

| Column | Type | Null | Key / default |
|---|---|---|---|
| `key` | varchar(255) | no | PK |
| `workspace_id` | integer | no | FK → `workspaces.id` (cascade) |
| `content` | blob | no |  |
| `size_bytes` | bigint | no |  |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_stored_files_workspace_id` (workspace_id)

## users

Accounts with a role (admin, editor, viewer) in one workspace; scrypt password hash.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `workspace_id` | integer | no | FK → `workspaces.id` (cascade) |
| `email` | varchar(254) | no | unique |
| `display_name` | varchar(120) | no |  |
| `password_hash` | varchar(255) | no |  |
| `role` | varchar(16) | no | default `editor` |
| `is_active` | boolean | no | default `True` |
| `preferences` | jsonb | no |  |
| `created_at` | datetime | no |  |
| `last_login_at` | datetime | yes |  |

Indexes and constraints: `ix_users_workspace_id` (workspace_id)

## api_keys

SDK and automation keys; only an HMAC of the key is stored.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `workspace_id` | integer | no | FK → `workspaces.id` (cascade) |
| `user_id` | integer | no | FK → `users.id` (cascade) |
| `name` | varchar(120) | no |  |
| `prefix` | varchar(16) | no | unique |
| `key_hash` | varchar(128) | no |  |
| `role` | varchar(16) | no | default `editor` |
| `created_at` | datetime | no |  |
| `last_used_at` | datetime | yes |  |
| `expires_at` | datetime | yes |  |
| `revoked_at` | datetime | yes |  |

Indexes and constraints: `ix_api_keys_user_id` (user_id); `ix_api_keys_workspace_id` (workspace_id)

## column_rename_decisions

User confirmations or rejections of rename candidates.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `dataset_id` | integer | no | FK → `datasets.id` (cascade) |
| `from_column` | varchar(128) | no |  |
| `to_column` | varchar(128) | no |  |
| `decision` | varchar(16) | no |  |
| `decided_by` | integer | yes | FK → `users.id` (set null) |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_column_rename_decisions_dataset_id` (dataset_id); `uq_rename_decision` (dataset_id, from_column, to_column)

## dataset_versions

Each uploaded or derived batch: ingestion result, checksum, status, lineage to its parent version.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `dataset_id` | integer | no | FK → `datasets.id` (cascade) |
| `version_number` | integer | no |  |
| `status` | varchar(16) | no | default `pending` |
| `ingestion_status` | varchar(16) | no | default `pending` |
| `ingestion_error` | jsonb | yes |  |
| `ingestion_duration_ms` | float | yes |  |
| `original_filename` | varchar(160) | yes |  |
| `file_format` | varchar(16) | no |  |
| `raw_storage_key` | varchar(255) | yes |  |
| `storage_key` | varchar(255) | yes |  |
| `checksum` | varchar(64) | yes |  |
| `size_bytes` | bigint | yes |  |
| `row_count` | integer | yes |  |
| `column_count` | integer | yes |  |
| `malformed_rows` | integer | no | default `0` |
| `schema_fingerprint` | varchar(32) | yes |  |
| `parse_warnings` | jsonb | no |  |
| `is_known_good` | boolean | no | default `False` |
| `parent_version_id` | integer | yes | FK → `dataset_versions.id` (set null) |
| `origin` | varchar(32) | no | default `upload` |
| `origin_detail` | jsonb | no |  |
| `created_by` | integer | yes | FK → `users.id` (set null) |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_dataset_versions_checksum` (checksum); `ix_dataset_versions_dataset_id` (dataset_id); `uq_version_number` (dataset_id, version_number)

## job_executions

Job run history with status, duration, retries and errors.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `job_id` | integer | yes | FK → `scheduled_jobs.id` (cascade) |
| `workspace_id` | integer | no | FK → `workspaces.id` (cascade) |
| `job_type` | varchar(32) | no |  |
| `trigger` | varchar(16) | no |  |
| `status` | varchar(16) | no |  |
| `attempt` | integer | no | default `1` |
| `started_at` | datetime | yes |  |
| `finished_at` | datetime | yes |  |
| `duration_ms` | float | yes |  |
| `result` | jsonb | no |  |
| `error` | text | yes |  |
| `worker` | varchar(80) | yes |  |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_job_executions_job_id` (job_id); `ix_job_executions_workspace_id` (workspace_id)

## ml_models

Registered models (task, target, positive label, reference dataset, criticality).

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `workspace_id` | integer | no | FK → `workspaces.id` (cascade) |
| `name` | varchar(120) | no |  |
| `description` | text | yes |  |
| `task` | varchar(16) | no |  |
| `target` | varchar(200) | yes |  |
| `positive_label` | varchar(64) | yes |  |
| `reference_dataset_id` | integer | yes | FK → `datasets.id` (set null) |
| `criticality` | varchar(16) | no | default `medium` |
| `owner` | varchar(120) | yes |  |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_ml_models_workspace_id` (workspace_id); `uq_model_name` (workspace_id, name)

## notifications

In-app notifications (and email, when SMTP is configured).

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `workspace_id` | integer | no | FK → `workspaces.id` (cascade) |
| `user_id` | integer | yes | FK → `users.id` (cascade) |
| `kind` | varchar(32) | no |  |
| `severity` | varchar(16) | no | default `info` |
| `title` | varchar(240) | no |  |
| `body` | text | no | default `` |
| `link` | varchar(240) | yes |  |
| `dedup_key` | varchar(120) | yes |  |
| `read_at` | datetime | yes |  |
| `email_status` | varchar(16) | yes |  |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_notifications_dedup_key` (dedup_key); `ix_notifications_user_id` (user_id); `ix_notifications_workspace_id` (workspace_id)

## quality_rules

Validated rule definitions (type, columns, config, severity).

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `workspace_id` | integer | no | FK → `workspaces.id` (cascade) |
| `dataset_id` | integer | no | FK → `datasets.id` (cascade) |
| `name` | varchar(160) | no |  |
| `rule_type` | varchar(32) | no |  |
| `columns` | jsonb | no |  |
| `config` | jsonb | no |  |
| `severity` | varchar(16) | no | default `warning` |
| `enabled` | boolean | no | default `True` |
| `created_by` | integer | yes | FK → `users.id` (set null) |
| `created_at` | datetime | no |  |
| `updated_at` | datetime | no |  |

Indexes and constraints: `ix_quality_rules_workspace_id` (workspace_id); `ix_quality_rules_dataset_id` (dataset_id)

## audit_events

Append-only record of security-relevant and state-changing actions.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | bigint | no | PK |
| `workspace_id` | integer | no | FK → `workspaces.id` (cascade) |
| `actor_user_id` | integer | yes | FK → `users.id` (set null) |
| `actor_api_key_id` | integer | yes | FK → `api_keys.id` (set null) |
| `actor_label` | varchar(120) | no | default `system` |
| `action` | varchar(64) | no |  |
| `entity_type` | varchar(40) | no |  |
| `entity_id` | varchar(40) | yes |  |
| `data` | jsonb | no |  |
| `ip` | varchar(64) | yes |  |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_audit_events_workspace_id` (workspace_id); `ix_audit_entity` (workspace_id, entity_type, entity_id); `ix_audit_events_action` (action)

## dataset_schema_columns

Inferred schema of a version (semantic and physical type per column).

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `version_id` | integer | no | FK → `dataset_versions.id` (cascade) |
| `name` | varchar(128) | no |  |
| `position` | integer | no |  |
| `semantic_type` | varchar(16) | no |  |
| `physical_type` | varchar(32) | no |  |
| `nullable` | boolean | no |  |

Indexes and constraints: `ix_dataset_schema_columns_version_id` (version_id); `uq_schema_column` (version_id, name)

## drift_evaluations

One drift comparison between a reference and a current version, with config and summary.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `dataset_id` | integer | no | FK → `datasets.id` (cascade) |
| `reference_version_id` | integer | no | FK → `dataset_versions.id` (cascade) |
| `current_version_id` | integer | no | FK → `dataset_versions.id` (cascade) |
| `config` | jsonb | no |  |
| `windows` | jsonb | no |  |
| `summary` | jsonb | no |  |
| `other_findings` | jsonb | no |  |
| `overall_severity` | varchar(16) | no |  |
| `trigger` | varchar(32) | no | default `manual` |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_drift_evaluations_dataset_id` (dataset_id)

## incidents

Deduplicated incidents with findings, impact, priority, assignment and resolution.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `workspace_id` | integer | no | FK → `workspaces.id` (cascade) |
| `dataset_id` | integer | yes | FK → `datasets.id` (cascade) |
| `version_id` | integer | yes | FK → `dataset_versions.id` (set null) |
| `model_id` | integer | yes | FK → `ml_models.id` (cascade) |
| `title` | varchar(240) | no |  |
| `severity` | varchar(16) | no |  |
| `status` | varchar(16) | no | default `open` |
| `fingerprint` | varchar(64) | no |  |
| `findings` | jsonb | no |  |
| `impact` | jsonb | no |  |
| `priority` | jsonb | no |  |
| `priority_score` | float | no | default `0` |
| `assigned_to` | integer | yes | FK → `users.id` (set null) |
| `occurrence_count` | integer | no | default `1` |
| `first_seen_at` | datetime | no |  |
| `last_seen_at` | datetime | no |  |
| `acknowledged_at` | datetime | yes |  |
| `resolved_at` | datetime | yes |  |
| `resolution` | jsonb | yes |  |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_incident_fingerprint_status` (workspace_id, fingerprint, status); `ix_incidents_dataset_id` (dataset_id); `ix_incidents_priority_score` (priority_score); `ix_incidents_workspace_id` (workspace_id); `ix_incidents_model_id` (model_id)

## lineage_nodes

Datasets, transformations, feature tables, models, reports and consumers.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `workspace_id` | integer | no | FK → `workspaces.id` (cascade) |
| `node_type` | varchar(24) | no |  |
| `name` | varchar(160) | no |  |
| `description` | text | yes |  |
| `dataset_id` | integer | yes | FK → `datasets.id` (cascade) |
| `model_id` | integer | yes | FK → `ml_models.id` (cascade) |
| `criticality` | varchar(16) | no | default `medium` |
| `owner` | varchar(120) | yes |  |
| `meta` | jsonb | no |  |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_lineage_nodes_model_id` (model_id); `ix_lineage_nodes_workspace_id` (workspace_id); `ix_lineage_nodes_dataset_id` (dataset_id); `uq_lineage_node` (workspace_id, node_type, name)

## model_versions

Model versions with input schema, baseline metrics and feature-logging policy.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `model_id` | integer | no | FK → `ml_models.id` (cascade) |
| `version` | varchar(40) | no |  |
| `input_schema` | jsonb | no |  |
| `baseline_metrics` | jsonb | no |  |
| `artifact` | jsonb | no |  |
| `feature_logging` | varchar(16) | no | default `aggregate` |
| `reference_profile` | jsonb | no |  |
| `retention_days` | integer | no | default `90` |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_model_versions_model_id` (model_id); `uq_model_version` (model_id, version)

## profiles

Per-version profile: summary and per-column statistics, with the config used.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `dataset_id` | integer | no | FK → `datasets.id` (cascade) |
| `version_id` | integer | no | FK → `dataset_versions.id` (cascade) |
| `summary` | jsonb | no |  |
| `columns` | jsonb | no |  |
| `config` | jsonb | no |  |
| `duration_ms` | float | no |  |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_profiles_dataset_id` (dataset_id); `ix_profiles_version_id` (version_id)

## quality_check_runs

One execution of a dataset's rule set against a version.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `dataset_id` | integer | no | FK → `datasets.id` (cascade) |
| `version_id` | integer | no | FK → `dataset_versions.id` (cascade) |
| `trigger` | varchar(32) | no |  |
| `summary` | jsonb | no |  |
| `duration_ms` | float | no | default `0` |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_quality_check_runs_dataset_id` (dataset_id); `ix_quality_check_runs_version_id` (version_id)

## version_comparisons

Schema and profile diff between two versions, including rename candidates.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `dataset_id` | integer | no | FK → `datasets.id` (cascade) |
| `base_version_id` | integer | no | FK → `dataset_versions.id` (cascade) |
| `target_version_id` | integer | no | FK → `dataset_versions.id` (cascade) |
| `result` | jsonb | no |  |
| `overall_severity` | varchar(16) | no |  |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_version_comparisons_dataset_id` (dataset_id)

## drift_feature_results

Per-feature drift statistics, corrected p-values, status and evidence.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `evaluation_id` | integer | no | FK → `drift_evaluations.id` (cascade) |
| `feature` | varchar(128) | no |  |
| `semantic_type` | varchar(16) | no |  |
| `method` | varchar(32) | no |  |
| `status` | varchar(24) | no |  |
| `severity` | varchar(16) | no |  |
| `n_reference` | integer | no |  |
| `n_current` | integer | no |  |
| `significant` | boolean | yes |  |
| `statistics` | jsonb | no |  |
| `evidence` | jsonb | no |  |
| `explanation` | text | no |  |

Indexes and constraints: `ix_drift_feature_results_evaluation_id` (evaluation_id)

## incident_comments

Investigation notes from editors.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `incident_id` | integer | no | FK → `incidents.id` (cascade) |
| `user_id` | integer | yes | FK → `users.id` (set null) |
| `body` | text | no |  |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_incident_comments_incident_id` (incident_id)

## incident_events

Timeline entries for an incident (state changes, detections, remediation steps).

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `incident_id` | integer | no | FK → `incidents.id` (cascade) |
| `event_type` | varchar(40) | no |  |
| `message` | text | no |  |
| `data` | jsonb | no |  |
| `actor_user_id` | integer | yes | FK → `users.id` (set null) |
| `actor_label` | varchar(80) | no | default `system` |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_incident_events_incident_id` (incident_id)

## lineage_edges

Dependencies with provenance (confirmed, declared, inferred).

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `workspace_id` | integer | no | FK → `workspaces.id` (cascade) |
| `source_id` | integer | no | FK → `lineage_nodes.id` (cascade) |
| `target_id` | integer | no | FK → `lineage_nodes.id` (cascade) |
| `dependency_type` | varchar(32) | no | default `reads` |
| `provenance` | varchar(16) | no | default `declared` |
| `meta` | jsonb | no |  |
| `created_by` | integer | yes | FK → `users.id` (set null) |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_lineage_edges_target_id` (target_id); `ix_lineage_edges_workspace_id` (workspace_id); `ix_lineage_edges_source_id` (source_id); `uq_lineage_edge` (source_id, target_id)

## model_evaluations

Windowed model evaluation: metrics with intervals, input and prediction drift, status.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `model_version_id` | integer | no | FK → `model_versions.id` (cascade) |
| `window_start` | datetime | yes |  |
| `window_end` | datetime | yes |  |
| `n_predictions` | integer | no |  |
| `n_labelled` | integer | no |  |
| `label_coverage` | float | no |  |
| `metrics` | jsonb | no |  |
| `input_drift` | jsonb | no |  |
| `prediction_drift` | jsonb | no |  |
| `performance` | jsonb | no |  |
| `schema_violation_count` | integer | no | default `0` |
| `status` | varchar(16) | no |  |
| `trigger` | varchar(32) | no | default `manual` |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_model_evaluations_model_version_id` (model_version_id)

## prediction_batches

Aggregated per-batch feature statistics used when raw feature logging is disabled.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `model_version_id` | integer | no | FK → `model_versions.id` (cascade) |
| `window_start` | datetime | no |  |
| `window_end` | datetime | no |  |
| `n_predictions` | integer | no |  |
| `feature_stats` | jsonb | no |  |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_prediction_batches_model_version_id` (model_version_id)

## prediction_records

Logged predictions and delayed labels (raw features only with full logging).

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | bigint | no | PK |
| `model_version_id` | integer | no | FK → `model_versions.id` (cascade) |
| `record_id` | varchar(128) | no |  |
| `predicted_at` | datetime | no |  |
| `features` | jsonb | yes |  |
| `prediction` | varchar(64) | no |  |
| `prediction_value` | float | yes |  |
| `score` | float | yes |  |
| `label` | varchar(64) | yes |  |
| `labeled_at` | datetime | yes |  |
| `schema_violations` | jsonb | yes |  |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_predictions_version_time` (model_version_id, predicted_at); `uq_prediction_record` (model_version_id, record_id)

## quality_check_results

Per-rule outcome of a run: rows evaluated, failures, observed vs expected, samples, explanation.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `run_id` | integer | no | FK → `quality_check_runs.id` (cascade) |
| `rule_id` | integer | yes | FK → `quality_rules.id` (cascade) |
| `rule_snapshot` | jsonb | no |  |
| `status` | varchar(8) | no |  |
| `rows_evaluated` | integer | no |  |
| `failed_rows` | integer | yes |  |
| `failure_pct` | float | yes |  |
| `duration_ms` | float | no |  |
| `observed` | jsonb | no |  |
| `expected` | jsonb | no |  |
| `explanation` | text | no |  |
| `sample_failures` | jsonb | no |  |
| `created_at` | datetime | no |  |

Indexes and constraints: `ix_quality_check_results_run_id` (run_id); `ix_quality_check_results_rule_id` (rule_id)

## remediation_proposals

Proposed actions with preconditions, risk, mode and approval state.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `workspace_id` | integer | no | FK → `workspaces.id` (cascade) |
| `incident_id` | integer | no | FK → `incidents.id` (cascade) |
| `dataset_id` | integer | yes | FK → `datasets.id` (cascade) |
| `version_id` | integer | yes | FK → `dataset_versions.id` (set null) |
| `action` | varchar(40) | no |  |
| `params` | jsonb | no |  |
| `reason` | text | no |  |
| `evidence` | jsonb | no |  |
| `preconditions` | jsonb | no |  |
| `expected_outcome` | text | no |  |
| `rollback` | text | no | default `` |
| `risk_level` | varchar(8) | no |  |
| `execution_mode` | varchar(16) | no |  |
| `approval_required` | boolean | no | default `True` |
| `status` | varchar(24) | no | default `proposed` |
| `idempotency_key` | varchar(80) | no | unique |
| `approved_by` | integer | yes | FK → `users.id` (set null) |
| `approved_at` | datetime | yes |  |
| `created_at` | datetime | no |  |
| `updated_at` | datetime | no |  |

Indexes and constraints: `ix_remediation_proposals_incident_id` (incident_id); `ix_remediation_proposals_workspace_id` (workspace_id)

## remediation_executions

Each execution attempt with its result and post-action verification.

| Column | Type | Null | Key / default |
|---|---|---|---|
| `id` | integer | no | PK |
| `proposal_id` | integer | no | FK → `remediation_proposals.id` (cascade) |
| `attempt` | integer | no |  |
| `status` | varchar(24) | no |  |
| `started_at` | datetime | no |  |
| `finished_at` | datetime | yes |  |
| `result` | jsonb | no |  |
| `verification` | jsonb | no |  |
| `error` | text | yes |  |
| `executed_by` | integer | yes | FK → `users.id` (set null) |

Indexes and constraints: `ix_remediation_executions_proposal_id` (proposal_id)
