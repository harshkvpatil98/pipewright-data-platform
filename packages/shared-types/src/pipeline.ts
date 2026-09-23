/**
 * Contracts for extraction, data quality, and schema drift.
 * These mirror the Pydantic schemas in service-extraction and service-quality.
 */

export type ConnectorType = "postgresql" | "mysql" | "sqlite";

export type LoadMode = "full_refresh" | "incremental_append" | "incremental_merge";

export type ExtractionConnection = {
  id: string;
  project_id: string;
  name: string;
  connector_type: ConnectorType;
  description: string | null;
  status: string;
  config_json: Record<string, unknown>;
  last_tested_at: string | null;
  last_test_status: string | null;
  last_test_message: string | null;
  created_at: string;
  updated_at: string;
};

export type ExtractionConnectionListResponse = {
  items: ExtractionConnection[];
};

export type ConnectionTestResponse = {
  success: boolean;
  message: string;
  latency_ms: number | null;
  server_version: string | null;
  warnings: string[];
};

export type DiscoveredTable = {
  schema_name: string | null;
  name: string;
  kind: string;
  qualified_name: string;
};

export type DiscoveredTablesResponse = {
  items: DiscoveredTable[];
};

export type DiscoveredColumn = {
  name: string;
  data_type: string;
  nullable: boolean;
  primary_key: boolean;
};

export type DiscoveredColumnsResponse = {
  table: string;
  schema_name: string | null;
  items: DiscoveredColumn[];
};

export type ExtractionPreviewResponse = {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  warnings: string[];
};

export type ExtractionJob = {
  id: string;
  project_id: string;
  connection_id: string;
  name: string;
  description: string | null;
  source_kind: "table" | "query";
  source_schema: string | null;
  source_table: string | null;
  query_sql: string | null;
  load_mode: LoadMode;
  cursor_column: string | null;
  primary_key_columns: string[] | null;
  max_rows: number;
  /** Transformation steps applied at extraction; the pushable prefix runs in
   * the source database, the rest here, before the dataset is written. */
  steps: { step_type: string; config: Record<string, unknown> }[];
  watermark_value: string | null;
  watermark_updated_at: string | null;
  target_dataset_id: string | null;
  enabled: boolean;
  last_run_at: string | null;
  last_run_status: string | null;
  last_row_count: number | null;
  last_error_message: string | null;
  execution_count: number;
  created_at: string;
  updated_at: string;
};

export type ExtractionJobListResponse = {
  items: ExtractionJob[];
};

export type ExtractionRunResponse = {
  job: ExtractionJob;
  dataset_id: string;
  run_id: string;
  rows_extracted: number;
  rows_added: number;
  rows_updated: number;
  total_rows: number;
  load_mode: LoadMode;
  watermark_value: string | null;
  truncated: boolean;
  warnings: string[];
  /** Where the job's steps ran, when it has any. */
  shaping: ExtractionShapingPlan | null;
};

/** The planner's record of a shaped extraction: what the source ran as SQL,
 * what ran here, and why for each placement. */
export type ExtractionShapingPlan = {
  surface: string;
  pushed_steps: number;
  local_steps: number;
  sql: string | null;
  placements: { node: string; pushed: boolean; reason: string }[];
  note: string;
  /** Semantics-preserving rewrites applied before the split, in words. */
  rewrites?: string[];
};

// ------------------------------------------------------------ stream sources

export type StreamKind = "webhook" | "postgres_cdc";

/** A source that delivers rows instead of being polled for them: a
 * token-keyed webhook endpoint, or a PostgreSQL change log followed through a
 * logical replication slot. Both materialise into one append-only dataset. */
export type StreamSource = {
  id: string;
  project_id: string;
  name: string;
  kind: StreamKind;
  status: string;
  connection_id: string | null;
  connection_name: string | null;
  tables: string[];
  slot_name: string | null;
  webhook_path: string | null;
  cursor: string | null;
  dataset_id: string | null;
  dataset_name: string | null;
  events_count: number;
  last_event_at: string | null;
  last_polled_at: string | null;
  last_materialised_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
};

/** The create response: the read plus the one-time webhook token. */
export type StreamSourceCreated = StreamSource & {
  token: string | null;
  webhook_path_with_token: string | null;
};

export type StreamSourceListResponse = { items: StreamSource[] };

export type StreamEvent = {
  id: string;
  source_id: string;
  seq: number;
  kind: string;
  table_name: string | null;
  position: string | null;
  payload_json: Record<string, unknown>;
  received_at: string;
};

export type StreamPollResponse = {
  source: StreamSource;
  slot_created: boolean;
  changes_read: number;
  events_stored: number;
  lines_consumed: number;
  upto_lsn: string | null;
  note: string;
};

export type StreamMaterialiseResponse = {
  source: StreamSource;
  dataset_id: string;
  version_number: number;
  rows: number;
  columns: string[];
};

// --------------------------------------------------------------- data quality

export type RuleSeverity = "error" | "warning";

export type QualityRuleType =
  | "not_null"
  | "unique"
  | "allowed_values"
  | "range"
  | "regex_match"
  | "expression"
  | "row_count"
  | "freshness";

export type DataQualityRule = {
  id: string;
  project_id: string;
  dataset_id: string | null;
  name: string;
  description: string | null;
  rule_type: QualityRuleType;
  severity: RuleSeverity;
  config_json: Record<string, unknown>;
  enabled: boolean;
  last_evaluated_at: string | null;
  last_status: string | null;
  created_at: string;
  updated_at: string;
};

export type DataQualityRuleListResponse = {
  items: DataQualityRule[];
};

export type RuleResult = {
  rule_id: string | null;
  name: string;
  rule_type: string;
  severity: RuleSeverity;
  status: "passed" | "failed";
  evaluated_rows: number;
  failed_rows: number;
  failure_rate: number;
  message: string;
  details: Record<string, unknown>;
};

export type DataQualityEvaluationResponse = {
  evaluation_id: string;
  dataset_id: string;
  status: "passed" | "failed" | "warning";
  rules_evaluated: number;
  rules_failed: number;
  error_failures: number;
  warning_failures: number;
  rows_in: number;
  rows_passing: number;
  rows_quarantined: number;
  quarantine_dataset_id: string | null;
  results: RuleResult[];
  warnings: string[];
};

export type DataQualityResult = {
  id: string;
  evaluation_id: string;
  rule_id: string | null;
  dataset_id: string | null;
  rule_name: string;
  rule_type: string;
  severity: RuleSeverity;
  status: string;
  evaluated_rows: number;
  failed_rows: number;
  failure_rate: number;
  message: string | null;
  details_json: Record<string, unknown> | null;
  created_at: string;
};

export type DataQualityResultListResponse = {
  items: DataQualityResult[];
};

export type RuleTypeInfo = {
  rule_type: QualityRuleType;
  description: string;
  required_config: string[];
  optional_config: string[];
  row_level: boolean;
};

export type RuleCatalogResponse = {
  items: RuleTypeInfo[];
};

// --------------------------------------------------------------- schema drift

export type DriftSeverity = "none" | "compatible" | "risky" | "breaking";

export type ColumnTypeChange = {
  column: string;
  previous_type: string;
  current_type: string;
  severity: string;
};

export type SchemaDriftEvent = {
  id: string;
  project_id: string;
  dataset_id: string | null;
  previous_dataset_id: string | null;
  extraction_job_id: string | null;
  severity: DriftSeverity;
  summary: string;
  added_columns: string[] | null;
  removed_columns: string[] | null;
  type_changes: ColumnTypeChange[] | null;
  acknowledged: boolean;
  acknowledged_at: string | null;
  created_at: string;
};

export type SchemaDriftEventListResponse = {
  items: SchemaDriftEvent[];
};
