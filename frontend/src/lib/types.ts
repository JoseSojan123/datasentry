export type Severity = "info" | "warning" | "critical";
export type Health = "healthy" | "warning" | "failing" | "unknown";
export type Role = "admin" | "editor" | "viewer";

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface User {
  id: number;
  email: string;
  display_name: string;
  role: Role;
  workspace_id: number;
  preferences: Record<string, unknown>;
}

export interface Workspace {
  id: number;
  name: string;
  is_demo: boolean;
  expires_at: string | null;
  settings: Record<string, any>;
}

export interface Session {
  access_token: string;
  expires_at: string;
  user: User;
  workspace: Workspace;
}

export interface ColumnSchema {
  name: string;
  position: number;
  semantic_type: "numeric" | "categorical" | "datetime" | "boolean" | "text";
  physical_type: string;
  nullable: boolean;
}

export interface Version {
  id: number;
  dataset_id: number;
  version_number: number;
  status: string;
  ingestion_status: "pending" | "succeeded" | "failed";
  ingestion_error: { code: string; message: string } | null;
  ingestion_duration_ms: number | null;
  original_filename: string | null;
  file_format: string;
  checksum: string | null;
  size_bytes: number | null;
  row_count: number | null;
  column_count: number | null;
  malformed_rows: number;
  schema_fingerprint: string | null;
  parse_warnings: string[];
  is_known_good: boolean;
  parent_version_id: number | null;
  origin: string;
  origin_detail: Record<string, any>;
  created_at: string;
  columns?: ColumnSchema[];
}

export interface Dataset {
  id: number;
  name: string;
  description: string | null;
  owner: string | null;
  tags: string[];
  domain: string | null;
  criticality: "low" | "medium" | "high" | "critical";
  source_type: "upload" | "synthetic" | "public" | "sdk";
  primary_key: string[];
  freshness_column: string | null;
  reference_version_id: number | null;
  current_version_id: number | null;
  health: Health;
  settings: Record<string, any>;
  created_at: string;
  updated_at: string;
  current_version: Version | null;
  open_incidents: number;
  version_count: number;
  rule_count: number;
}

export interface Finding {
  id?: string;
  source: string;
  kind: string;
  column: string | null;
  severity: Severity;
  message: string;
  rule_id?: number;
  rule_name?: string;
  statistics?: Record<string, number | null>;
  check_run_id?: number;
  drift_evaluation_id?: number;
  comparison_id?: number;
  model_evaluation_id?: number;
}

export interface Profile {
  id: number;
  version_id: number;
  summary: Record<string, any>;
  columns: Record<string, Record<string, any>>;
  config: Record<string, any>;
  duration_ms: number;
  created_at: string;
}

export interface Rule {
  id: number;
  dataset_id: number;
  name: string;
  rule_type: string;
  columns: string[];
  config: Record<string, any>;
  severity: Severity;
  enabled: boolean;
  created_at: string;
  last_result: { status: string; failure_pct: number | null; failed_rows: number | null; explanation: string; created_at: string } | null;
}

export interface CheckResult {
  id: number;
  run_id: number;
  rule_id: number | null;
  rule: { name: string; rule_type: string; columns: string[]; severity: Severity; config: Record<string, any> };
  status: "pass" | "fail" | "error";
  rows_evaluated: number;
  failed_rows: number | null;
  failure_pct: number | null;
  duration_ms: number;
  observed: Record<string, any>;
  expected: Record<string, any>;
  explanation: string;
  sample_failures: Record<string, any>[];
  created_at: string;
}

export interface CheckRun {
  id: number;
  dataset_id: number;
  version_id: number;
  trigger: string;
  summary: { total: number; passed: number; failed: number; errored: number; pass_rate: number | null; failed_by_severity: Record<string, number> };
  duration_ms: number;
  created_at: string;
  results?: CheckResult[];
}

export interface DriftFeature {
  id: number;
  feature: string;
  semantic_type: string;
  method: string;
  status: "no_drift" | "drift" | "inconclusive" | "insufficient_data" | "skipped";
  severity: "none" | "info" | "warning" | "critical";
  n_reference: number;
  n_current: number;
  significant: boolean | null;
  statistics: Record<string, any>;
  evidence: Record<string, any>;
  explanation: string;
}

export interface DriftEvaluation {
  id: number;
  dataset_id: number;
  dataset_name?: string;
  reference_version_id: number;
  current_version_id: number;
  config: Record<string, any>;
  windows: Record<string, any>;
  summary: Record<string, any>;
  other_findings: Record<string, any>[];
  overall_severity: "none" | Severity;
  trigger: string;
  created_at: string;
  features?: DriftFeature[];
}

export interface Comparison {
  id: number;
  dataset_id: number;
  base_version_id: number;
  target_version_id: number;
  overall_severity: string;
  created_at: string;
  result: {
    summary: Record<string, any>;
    changes: { kind: string; column: string | null; severity: Severity; message: string; to?: string; confidence?: number; evidence?: Record<string, number>; ambiguous?: boolean; values?: string[] }[];
    rename_candidates: { from: string; to: string; confidence: number; ambiguous: boolean; evidence: Record<string, number> }[];
  };
}

export interface ModelVersion {
  id: number;
  model_id: number;
  version: string;
  input_schema: { name: string; type: string }[];
  baseline_metrics: Record<string, any>;
  artifact: Record<string, any>;
  feature_logging: "none" | "aggregate" | "full";
  retention_days: number;
  reference_source: Record<string, any> | null;
  reference_features: string[];
  created_at: string;
}

export interface ModelEvaluation {
  id: number;
  model_version_id: number;
  window_start: string | null;
  window_end: string | null;
  n_predictions: number;
  n_labelled: number;
  label_coverage: number;
  metrics: Record<string, any>;
  input_drift: Record<string, any>;
  prediction_drift: Record<string, any>;
  performance: Record<string, any>;
  schema_violation_count: number;
  status: "ok" | "warning" | "critical" | "unknown";
  trigger: string;
  created_at: string;
}

export interface MLModel {
  id: number;
  name: string;
  description: string | null;
  task: "classification" | "regression";
  target: string | null;
  positive_label: string | null;
  reference_dataset_id: number | null;
  criticality: string;
  owner: string | null;
  created_at: string;
  versions: ModelVersion[];
  latest_evaluation: ModelEvaluation | null;
  prediction_count: number;
  open_incidents: number;
}

export interface LineageNode {
  id: number;
  node_type: "dataset" | "transformation" | "feature_table" | "model" | "report" | "consumer";
  name: string;
  description: string | null;
  dataset_id: number | null;
  model_id: number | null;
  criticality: string;
  owner: string | null;
  meta: Record<string, any>;
  health?: Health | null;
  open_incidents?: number;
  role?: "source" | "affected" | "upstream";
  impact?: "confirmed" | "potential" | null;
  depth?: number;
  path?: number[] | null;
}

export interface LineageEdge {
  id: number;
  source_id: number;
  target_id: number;
  dependency_type: string;
  provenance: "confirmed" | "declared" | "inferred";
  meta: Record<string, any>;
  on_impact_path?: boolean;
}

export interface ImpactNode {
  node_id: number;
  type: string;
  name: string;
  criticality: string;
  depth: number;
  path: number[];
  edge_path: number[];
  impact: "confirmed" | "potential";
}

export interface Impact {
  sources?: number[];
  affected: ImpactNode[];
  counts: { total: number; confirmed: number; potential: number; models: number; reports: number; transformations: number };
  consequences?: string[];
  investigation_steps?: string[];
  cost_estimate?: { label: string; assumptions: string; estimated_cost: number } | null;
}

export interface IncidentEvent {
  id: number;
  event_type: string;
  message: string;
  data: Record<string, any>;
  actor: string;
  created_at: string;
}

export interface Precondition {
  name: string;
  passed: boolean;
  detail: string;
  blocking: boolean;
}

export interface Execution {
  id: number;
  proposal_id: number;
  attempt: number;
  status: string;
  started_at: string;
  finished_at: string | null;
  result: Record<string, any>;
  verification: Record<string, any>;
  error: string | null;
}

export interface Proposal {
  id: number;
  incident_id: number;
  incident_title?: string;
  dataset_id: number | null;
  version_id: number | null;
  action: string;
  title: string;
  description: string;
  params: Record<string, any>;
  reason: string;
  evidence: Finding[];
  preconditions: Precondition[];
  expected_outcome: string;
  rollback: string;
  risk_level: "low" | "medium" | "high";
  changes_data: boolean | null;
  execution_mode: "recommend" | "approval" | "auto";
  approval_required: boolean;
  status: string;
  approved_at: string | null;
  created_at: string;
  executions?: Execution[];
}

export interface Incident {
  id: number;
  title: string;
  severity: Severity;
  status: "open" | "acknowledged" | "investigating" | "resolved" | "reopened";
  dataset_id: number | null;
  version_id: number | null;
  model_id: number | null;
  findings: Finding[];
  impact: Impact;
  priority: { score: number; urgency: string; components: Record<string, number>; method: string };
  priority_score: number;
  assigned_to: number | null;
  occurrence_count: number;
  first_seen_at: string;
  last_seen_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  resolution: Record<string, any> | null;
  resolution_seconds: number | null;
}

export interface IncidentDetail extends Incident {
  dataset_name: string | null;
  model_name: string | null;
  version_number: number | null;
  version_status: string | null;
  assignee_name: string | null;
  events: IncidentEvent[];
  comments: { id: number; body: string; author: string | null; created_at: string }[];
  proposals: Proposal[];
  related: Record<string, number[]>;
}

export interface Job {
  id: number;
  name: string;
  job_type: string;
  target_id: number | null;
  params: Record<string, any>;
  pending_retry_attempt: number | null;
  interval_seconds: number;
  enabled: boolean;
  max_retries: number;
  retry_backoff_seconds: number;
  timeout_seconds: number;
  next_run_at: string;
  last_run_at: string | null;
  last_success_at: string | null;
  last_status: string | null;
  consecutive_failures: number;
  running: boolean;
}

export interface JobExecution {
  id: number;
  job_id: number | null;
  job_type: string;
  trigger: string;
  status: string;
  attempt: number;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  result: Record<string, any>;
  error: string | null;
}

export interface Notification {
  id: number;
  kind: string;
  severity: Severity;
  title: string;
  body: string;
  link: string | null;
  read: boolean;
  created_at: string;
}

export interface AuditEvent {
  id: number;
  action: string;
  entity_type: string;
  entity_id: string | null;
  actor: string;
  data: Record<string, any>;
  created_at: string;
}

export interface Overview {
  datasets: { total: number; healthy: number; warning: number; failing: number; unknown: number };
  incidents: { open: number; critical: number; warning: number; resolved_7d: number };
  top_incidents: Incident[];
  recent_drift: { id: number; dataset_id: number; dataset_name: string; severity: string; features_drifted: number; created_at: string }[];
  recent_job_failures: JobExecution[];
  models: { model_id: number; name: string; status: string; label_coverage: number | null; input_drift_features: number | null; performance: string | null }[];
  remediation: Record<string, number>;
  incident_trend: { day: string; severity: string; count: number }[];
  check_trend: { day: string; status: string; count: number }[];
  sample_data_loaded: boolean;
}
