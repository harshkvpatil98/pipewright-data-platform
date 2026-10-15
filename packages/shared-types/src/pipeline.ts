/**
 * Contracts for extraction, data quality, and schema drift.
 * These mirror the Pydantic schemas in service-extraction and service-quality.
 */

/** The SQL databases, which import tables and queries directly. */
export type SqlConnectorType = "postgresql" | "mysql" | "sqlite";

/** A SQL database or any connector in the catalogue that can read. */
export type ConnectorType = SqlConnectorType | (string & {});

export const SQL_CONNECTOR_TYPES: readonly SqlConnectorType[] = ["postgresql", "mysql", "sqlite"];

/** What a connector listed, stored on an import; null means everything it returns. */
export type SourceStream = {
  name: string;
  namespace: string | null;
  kind: string;
  detail: Record<string, unknown>;
};

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
  /** What a connector needs to read this back beyond its name. */
  detail?: Record<string, unknown>;
};

export type DiscoveredTablesResponse = {
  items: DiscoveredTable[];
  /** False for a source that cannot list what it holds; it is imported whole. */
  can_list?: boolean;
  /** True when imports can bring only what is new since the last run. */
  can_resume?: boolean;
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
  source_kind: "table" | "query" | "stream";
  source_schema: string | null;
  source_table: string | null;
  query_sql: string | null;
  /** source_kind "stream": what to read from a non-database source. */
  stream_json?: SourceStream | null;
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

// ------------------------------------------------------------- live feeds

export type StreamKind =
  | "webhook"
  | "postgres_cdc"
  | "mysql_cdc"
  | "mongodb_cdc"
  | "sqlserver_cdc"
  | "kafka"
  | "event_hubs"
  | "kinesis"
  | "pubsub"
  | "pulsar"
  | "rabbitmq"
  | "nats"
  | "mqtt";

export type LiveFamily = "webhook" | "change_capture" | "queue";

/** How sure a kind is that each event is saved once (D1). */
export type LiveGuarantee = "position" | "message_id" | "at_least_once";

export type LiveKindField = {
  key: string;
  label: string;
  kind: "string" | "secret" | "number" | "boolean" | "select" | "text";
  required: boolean;
  default: unknown;
  help: string;
  placeholder: string;
  options: string[];
};

export type LiveKind = {
  key: StreamKind;
  label: string;
  family: LiveFamily;
  description: string;
  fields: LiveKindField[];
  connection_types: string[];
  guarantee: LiveGuarantee;
  guarantee_title: string;
  guarantee_detail: string;
  tier: number;
  tier_label: string;
  tier_badge: string;
  tier_explanation: string;
  verified_by: string;
  available: boolean;
  unavailable_reason: string | null;
};

export type LiveKindListResponse = { items: LiveKind[] };

/** A table a change-capture feed keeps current as a dataset. */
export type LiveTable = {
  id: string;
  table_name: string;
  key_columns: string[];
  dataset_id: string | null;
  state: "waiting" | "snapshot" | "following" | "log_only" | "failed";
  snapshot_rows: number | null;
  rows_now: number | null;
  applied_seq: number;
  last_saved_at: string | null;
  last_error: string | null;
};

/** A live feed: rows that arrive instead of being asked for. */
export type StreamSource = {
  id: string;
  project_id: string;
  name: string;
  kind: StreamKind;
  kind_label: string;
  family: LiveFamily;
  guarantee: LiveGuarantee;
  guarantee_title: string;
  guarantee_detail: string;
  tier: number;
  tier_label: string;
  status: "active" | "paused" | "failing" | string;
  connection_id: string | null;
  connection_name: string | null;
  tables: string[];
  slot_name: string | null;
  /** The kind's settings; a secret shows only whether it is set. */
  settings: Record<string, unknown>;
  webhook_path: string | null;
  cursor: string | null;
  dataset_id: string | null;
  dataset_name: string | null;
  events_count: number;
  behind: number | null;
  read_every_seconds: number;
  save_every_seconds: number;
  keep_events_hours: number;
  failures: number;
  next_read_at: string | null;
  last_read_count: number;
  last_event_at: string | null;
  last_polled_at: string | null;
  last_materialised_at: string | null;
  last_error: string | null;
  live_tables: LiveTable[];
  live_recipe_count: number;
  /** Every dataset this feed keeps: its log, its tables, its live recipes' outputs. */
  dataset_ids: string[];
  created_at: string;
  updated_at: string;
};

/** The create response: the read plus the one-time webhook token. */
export type StreamSourceCreated = StreamSource & {
  token: string | null;
  webhook_path_with_token: string | null;
};

export type StreamSourceListResponse = { items: StreamSource[] };

export type StreamSourceCreate = {
  name: string;
  kind: StreamKind;
  connection_id?: string | null;
  tables?: string[];
  settings?: Record<string, unknown>;
  read_every_seconds?: number;
  save_every_seconds?: number;
};

export type StreamSourceUpdate = {
  name?: string;
  status?: "active" | "paused";
  tables?: string[];
  settings?: Record<string, unknown>;
  read_every_seconds?: number;
  save_every_seconds?: number;
  keep_events_hours?: number;
};

export type LiveTestResult = { ok: boolean; message: string; details: string[] };

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
  read: number;
  stored: number;
  rounds: number;
  notes: string[];
  guarantee: string;
};

export type StreamMaterialiseResponse = {
  source: StreamSource;
  dataset_id: string | null;
  version_number: number;
  events_saved: number;
  changes_applied: number;
  recipe_outputs: number;
};

export type ThroughputPoint = { minute: string; events: number };
export type ThroughputResponse = { items: ThroughputPoint[] };

export type LiveWindowKind = "tumbling" | "hopping" | "sliding" | "session";
export type LiveMeasureOp = "count" | "sum" | "average" | "lowest" | "highest" | "first" | "last";

export type LiveWindow = {
  kind: LiveWindowKind;
  size_seconds?: number | null;
  advance_seconds?: number | null;
  gap_seconds?: number | null;
  time_column: string;
  lateness_seconds: number;
  late: "drop" | "restate";
  restate_for_seconds: number;
};

export type LiveMeasure = { name: string; op: LiveMeasureOp; column?: string | null };

export type LiveLookup = {
  dataset_id: string;
  on: { event: string; dataset: string }[];
  columns: string[];
  keep_unmatched: boolean;
};

export type LiveRecipeCreate = {
  name: string;
  recipe_id?: string | null;
  lookup?: LiveLookup | null;
  window?: LiveWindow | null;
  group_by?: string[];
  measures?: LiveMeasure[];
};

export type LiveRecipeUpdate = Partial<LiveRecipeCreate> & {
  status?: "active" | "paused";
  clear_recipe?: boolean;
  clear_lookup?: boolean;
};

export type LiveRecipe = {
  id: string;
  source_id: string;
  name: string;
  recipe_id: string | null;
  lookup: LiveLookup | null;
  window: LiveWindow | null;
  group_by: string[];
  measures: LiveMeasure[];
  output_dataset_id: string | null;
  output_dataset_name: string | null;
  status: "active" | "paused" | "failed" | string;
  last_error: string | null;
  processed_seq: number;
  events_in: number;
  late_dropped: number;
  late_restated: number;
  without_time: number;
  unmatched: number;
  open_windows: number;
  /** The watermark: every window ending by then is final. */
  complete_up_to: string | null;
  description: string;
  last_processed_at: string | null;
  last_saved_at: string | null;
  created_at: string;
  updated_at: string;
};

export type LiveRecipeListResponse = { items: LiveRecipe[] };

export type LiveRecipeResult = {
  window_start: string;
  window_end: string;
  group: unknown[];
  values: Record<string, unknown>;
  events: number;
  final: boolean;
  restated: number;
};

export type LiveRecipeResultsResponse = {
  recipe: LiveRecipe;
  group_by: string[];
  measures: string[];
  items: LiveRecipeResult[];
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
