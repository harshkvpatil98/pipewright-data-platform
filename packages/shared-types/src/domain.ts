export type ProjectStatus = "active" | "draft" | "archived";
export type SourceType = "csv" | "excel" | "json" | "api" | "postgres" | "s3";
export type SourceStatus = "active" | "pending" | "disabled";
export type DatasetStatus = "registered" | "processing" | "ready" | "failed";
export type IngestionStatus = "pending" | "queued" | "running" | "succeeded" | "failed";
export type PipelineRunStatus = "queued" | "running" | "succeeded" | "failed";
export type TransformationPipelineStatus = "draft" | "active";

export type DatasetSchemaColumn = {
  name: string;
  inferred_type: string;
  canonical_type?: string;
  nullable: boolean;
};

export type DatasetSchema = {
  columns: DatasetSchemaColumn[];
  ordered_columns: string[];
};

export type DatasetSchemaSnapshot = {
  columns: DatasetSchemaColumn[];
};

export type DatasetProfileColumn = {
  name: string;
  inferred_type: string;
  null_count: number;
  null_percentage: number;
  unique_count: number;
  unique_percentage: number;
  sample_values: unknown[];
  min_value: unknown | null;
  max_value: unknown | null;
  mean_value: number | null;
  std_value: number | null;
  min_length: number | null;
  max_length: number | null;
  possible_identifier: boolean;
  mixed_type_suspected: boolean;
};

export type DatasetQualityFlags = {
  high_null_columns: string[];
  constant_value_columns: string[];
  potential_id_columns: string[];
  mixed_type_suspicions: string[];
};

export type DatasetProfileSummary = {
  file_size_bytes: number;
  row_count: number;
  column_count: number;
  duplicate_row_count: number;
  duplicate_row_percentage: number;
  total_null_cells: number;
  completeness_score: number;
  columns: DatasetProfileColumn[];
  quality_flags: DatasetQualityFlags;
};

export type DatasetIngestionRunSummary = {
  ingestion_type: "dataset_upload";
  dataset: {
    id: string;
    name: string;
    ingestion_status: IngestionStatus;
    row_count?: number;
    column_count?: number;
  };
  artifact: {
    original_filename: string;
    stored_file_name?: string;
    file_type: string;
    file_size_bytes: number;
  };
  profile?: {
    duplicate_row_count: number;
    duplicate_row_percentage: number;
    completeness_score: number;
  };
  parser_metadata?: Record<string, unknown>;
  failure_stage?: string;
  error?: string;
};

export type DatasetTransformationRunSummary = {
  transformation_type: "dataset_transformation";
  base_dataset: {
    id: string;
    name: string;
  };
  derived_dataset?: {
    id: string;
    name: string;
  };
  pipeline: {
    id: string;
    name: string;
  };
  step_count: number;
  row_count_before?: number;
  row_count_after?: number;
  column_count_before?: number;
  column_count_after?: number;
  artifact?: {
    file_type: string;
    file_size_bytes: number;
    stored_file_name?: string;
  };
  warnings?: string[];
  failure_stage?: string;
  error?: string;
};

export type SamplePipelineRunSummary = {
  project_slug: string;
  project_status: ProjectStatus;
  project_source_count: number;
  project_dataset_count: number;
  project_run_count: number;
  global_source_count_snapshot: number;
};

export type PipelineRunSummary =
  | DatasetIngestionRunSummary
  | DatasetTransformationRunSummary
  | SamplePipelineRunSummary
  | Record<string, unknown>;

export type ProjectSummary = {
  id: string;
  owner_user_id: string | null;
  name: string;
  slug: string;
  description: string | null;
  status: ProjectStatus;
  /** Which copy of the world this project is; environments are separate projects. */
  environment: "development" | "staging" | "production";
  /** When true, definition edits must be proposed for review instead of saved. */
  requires_approval: boolean;
  promoted_from_project_id: string | null;
  source_count: number;
  dataset_count: number;
  created_at: string;
  updated_at: string;
};

export type ProjectDetail = ProjectSummary;

export type SourceRecord = {
  id: string;
  project_id: string;
  name: string;
  source_type: SourceType;
  description: string | null;
  status: SourceStatus;
  config_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type DatasetRecord = {
  id: string;
  project_id: string;
  source_id: string | null;
  uploaded_by_user_id: string | null;
  pipeline_run_id: string | null;
  parent_dataset_id: string | null;
  created_from_pipeline_id: string | null;
  name: string;
  original_filename: string | null;
  file_name: string | null;
  file_type: string | null;
  file_size_bytes: number | null;
  is_derived: boolean;
  status: DatasetStatus;
  ingestion_status: IngestionStatus;
  row_count: number | null;
  column_count: number | null;
  schema_snapshot: DatasetSchemaSnapshot | null;
  schema_json: DatasetSchema | null;
  profile_json: DatasetProfileSummary | null;
  preview_json: DatasetPreview | null;
  ingestion_error: string | null;
  last_profiled_at: string | null;
  /**
   * How the file was read: separator, header row, every column's type and date
   * format. Null for datasets ingested before Phase 11 — inventing one would
   * be a claim about how they were read.
   */
  ingest_spec_json: IngestSpec | null;
  created_at: string;
  updated_at: string;
};

export type DatasetPreview = {
  dataset_id: string;
  columns: string[];
  rows: Array<Record<string, unknown>>;
};

export type DatasetProfile = {
  dataset_id: string;
  profile: DatasetProfileSummary | null;
};

export type PipelineRunRecord = {
  id: string;
  project_id: string;
  triggered_by_user_id: string;
  pipeline_id: string | null;
  triggered_by_username: string | null;
  run_type: string;
  status: PipelineRunStatus;
  started_at: string | null;
  completed_at: string | null;
  summary_json: PipelineRunSummary | null;
  logs_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type DatasetAuditSummary = {
  id: string;
  name: string;
  is_derived: boolean;
  parent_dataset_id: string | null;
  project: { id: string; name: string };
  ownership: { uploaded_by_user_id: string | null };
  artifact: {
    file_name: string | null;
    original_filename: string | null;
    file_type: string | null;
    file_size_bytes: number | null;
    file_path: string | null;
  };
  metrics: {
    row_count: number | null;
    column_count: number | null;
    ingestion_status: IngestionStatus;
    created_at: string;
    updated_at: string;
    last_profiled_at: string | null;
  };
  profile_highlights: {
    duplicate_row_count: number | null;
    duplicate_row_percentage: number | null;
    completeness_score: number | null;
    high_null_columns: string[];
    constant_value_columns: string[];
    potential_id_columns: string[];
  };
  lineage: {
    created_from_pipeline_id: string | null;
    pipeline_run_id: string | null;
    parent_dataset_id: string | null;
  };
  schema_summary: {
    column_count: number | null;
    sample_column_names: string[];
  };
  warnings: string[];
};

export type RunAuditHighlights = {
  stage_count: number;
  failed_stage: string | null;
  derived_dataset_created: boolean;
  ingestion_type: string | null;
  transformation_type: string | null;
};

/** A version a run published -- its output pin (time travel, Phase 18). */
export type RunOutputVersion = {
  dataset_id: string;
  dataset_name: string | null;
  version_number: number;
  content_hash: string | null;
  retention_state: "active" | "pending_delete" | "pruned";
};

/** A durable reference to one version of one dataset, as recorded in a run's
 * execution context. */
export type ExecutionVersionPin = {
  dataset_id: string;
  version_number: number | null;
  content_hash: string | null;
  role?: "base" | "step" | "output";
  step_index?: number | null;
};

/** What a transformation run recorded about how it ran: enough to run it
 * again the same way. */
export type ExecutionContext = {
  schema: number;
  semantic_version: string;
  evaluated_at: string;
  timezone: string;
  clock_functions: string[];
  steps: Record<string, unknown>[];
  steps_digest: string;
  inputs: ExecutionVersionPin[];
  outputs: ExecutionVersionPin[];
  replay_of: string | null;
};

export type RunAuditSummary = {
  id: string;
  run_type: string;
  status: PipelineRunStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  project_id: string;
  triggered_by_user_id: string;
  pipeline_id: string | null;
  related_dataset_ids: string[];
  summary_json: Record<string, unknown> | null;
  logs_json: Record<string, unknown> | null;
  highlights: RunAuditHighlights;
  warnings: string[];
  output_versions: RunOutputVersion[];
  execution_context: ExecutionContext | null;
  replayable: boolean;
  replay_reason: string | null;
};

export type ReplayComparison = {
  method: string;
  columns_equal: boolean;
  types_equal: boolean;
  rows_equal: boolean;
  rows_original: number | null;
  rows_replay: number | null;
  differences: string[];
};

export type ReplayStatus =
  | "equivalent"
  | "divergent"
  | "incompatible"
  | "unavailable"
  | "failed"
  | "unverifiable";

export type ReplayResult = {
  status: ReplayStatus;
  reason: string | null;
  original_run_id: string;
  replay_run_id: string | null;
  replay_dataset_id: string | null;
  original_output: ExecutionVersionPin | null;
  replay_output: ExecutionVersionPin | null;
  comparison: ReplayComparison | null;
  evaluated_at: string | null;
  semantic_version: string | null;
};

export type ComparisonDatasetSide = {
  id: string;
  name: string;
  is_derived: boolean;
  row_count: number | null;
  column_count: number | null;
};

export type DatasetComparisonSummary = {
  left_dataset: ComparisonDatasetSide;
  right_dataset: ComparisonDatasetSide;
  row_count_delta: number | null;
  column_count_delta: number | null;
  profile_delta: {
    duplicate_row_count_before: number | null;
    duplicate_row_count_after: number | null;
    completeness_score_before: number | null;
    completeness_score_after: number | null;
  };
  schema_delta: {
    added_columns: string[];
    removed_columns: string[];
    changed_type_columns: { column_name: string; before_type: string; after_type: string }[];
  };
  lineage_context: {
    related_by_parent_child: boolean;
    parent_dataset_id: string | null;
    created_from_pipeline_id: string | null;
    related_run_id: string | null;
  };
  comparison_notes: string[];
};

export type RunComparisonDatasetRef = {
  id: string;
  name: string;
};

export type RunComparisonSummary = {
  run_id: string;
  run_type: string;
  status: PipelineRunStatus;
  pipeline_id: string | null;
  base_dataset: RunComparisonDatasetRef | null;
  derived_dataset: RunComparisonDatasetRef | null;
  row_count_before: number | null;
  row_count_after: number | null;
  column_count_before: number | null;
  column_count_after: number | null;
  step_count: number | null;
  summary_available: boolean;
  comparison_notes: string[];
  raw_summary_present: boolean;
};

export type StatisticalTestType = "welch_t_test" | "proportion_z_test" | "chi_square_distribution";

export type DatasetStatisticalTestRequestPayload = {
  test_type: StatisticalTestType;
  column_name: string;
};

export type StatisticalTestDatasetResultSide = {
  id: string;
  name: string;
  sample_size: number;
};

export type DatasetStatisticalTestResult = {
  test_type: StatisticalTestType;
  column_name: string;
  left_dataset: StatisticalTestDatasetResultSide;
  right_dataset: StatisticalTestDatasetResultSide;
  statistic: number | null;
  p_value: number | null;
  effect_summary: string;
  assumptions_notes: string[];
  interpretation: string;
  warnings: string[];
  left_mean: number | null;
  right_mean: number | null;
  left_proportion: number | null;
  right_proportion: number | null;
  category_count: number | null;
};

export type SavedStatisticalTestCreatePayload = {
  name: string;
  description?: string | null;
  left_dataset_id: string;
  right_dataset_id: string;
  test_type: StatisticalTestType;
  column_name: string;
  options_json?: Record<string, unknown> | unknown[] | null;
};

export type SavedStatisticalTestUpdatePayload = {
  name?: string | null;
  description?: string | null;
};

export type SavedStatisticalTestRead = {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  test_type: string;
  column_name: string;
  options_json: Record<string, unknown> | unknown[] | null;
  left_dataset_id: string;
  right_dataset_id: string;
  left_dataset_name: string;
  right_dataset_name: string;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
};

export type SavedStatisticalTestListItem = {
  id: string;
  project_id: string;
  name: string;
  test_type: string;
  column_name: string;
  left_dataset_id: string;
  right_dataset_id: string;
  left_dataset_name: string;
  right_dataset_name: string;
  last_run_at: string | null;
  updated_at: string;
};

export type SavedStatisticalTestListResponse = { items: SavedStatisticalTestListItem[] };

export type SavedStatisticalTestRunRead = {
  id: string;
  saved_test_id: string;
  project_id: string;
  status: string;
  executed_by_user_id: string | null;
  result: DatasetStatisticalTestResult | null;
  error_message: string | null;
  warnings_json: string[] | null;
  created_at: string;
};

export type SavedStatisticalTestRunsResponse = { items: SavedStatisticalTestRunRead[] };

export type SavedStatisticalTestDetail = {
  saved_test: SavedStatisticalTestRead;
  runs: SavedStatisticalTestRunRead[];
  comparison_note: string | null;
};

export type DestinationType = "postgres" | "s3" | "local_export";
export type DestinationStatus = "active" | "disabled";

export type DestinationRecord = {
  id: string;
  project_id: string;
  name: string;
  destination_type: DestinationType;
  status: DestinationStatus;
  /** API returns secrets redacted as "***". */
  config_json: Record<string, unknown>;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
};

export type DestinationListResponse = { items: DestinationRecord[] };

export type DestinationCreatePayload = {
  name: string;
  destination_type: DestinationType;
  status?: DestinationStatus;
  config_json: Record<string, unknown>;
};

export type DestinationUpdatePayload = {
  name?: string | null;
  status?: DestinationStatus | null;
  config_json?: Record<string, unknown> | null;
};

export type DestinationTestResult = {
  success: boolean;
  checked_at: string;
  message: string;
  latency_ms: number | null;
  warnings: string[];
};

export type BiIntegrationType = "power_bi" | "tableau";

export type BiIntegrationRecord = {
  id: string;
  project_id: string;
  name: string;
  integration_type: BiIntegrationType;
  status: DestinationStatus;
  /** API returns secrets redacted as "***". */
  config_json: Record<string, unknown>;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
};

export type BiIntegrationListResponse = { items: BiIntegrationRecord[] };

export type BiIntegrationCreatePayload = {
  name: string;
  integration_type: BiIntegrationType;
  status?: DestinationStatus;
  config_json: Record<string, unknown>;
};

export type BiIntegrationUpdatePayload = {
  name?: string | null;
  status?: DestinationStatus | null;
  config_json?: Record<string, unknown> | null;
};

export type BiMetadataItem = { id: string; name: string };

export type BiConnectionMetadataResponse = {
  integration_type: BiIntegrationType;
  metadata_kind: string;
  items: BiMetadataItem[];
};

export type DatasetPublishPostgresPayload = {
  destination_id: string;
  table_name: string;
  write_mode: "replace" | "append";
};

export type DestinationPublishSummary = {
  id: string;
  name: string;
  destination_type: string;
};

export type DatasetPublishPostgresResponse = {
  success: boolean;
  message: string;
  run: PipelineRunRecord;
  target_table: string;
  target_schema: string | null;
  write_mode: string;
  row_count_written: number | null;
  row_count_attempted: number | null;
  destination: DestinationPublishSummary;
  summary_json: Record<string, unknown> | null;
};

export type BiConnectionPublishSummary = {
  id: string;
  name: string;
  integration_type: string;
};

export type DatasetPublishPowerBiPayload = {
  connection_id: string;
  workspace_id: string;
  target_dataset_name: string;
  target_table_name?: string | null;
  write_mode: "replace" | "append";
};

export type DatasetPublishPowerBiResponse = {
  success: boolean;
  message: string;
  run: PipelineRunRecord;
  connection: BiConnectionPublishSummary;
  workspace_id: string;
  target_dataset_name: string;
  target_table_name: string;
  write_mode: string;
  row_count_published: number | null;
  row_count_attempted: number | null;
  power_bi_dataset_id: string | null;
  provider_outcome: string | null;
  summary_json: Record<string, unknown> | null;
};

export type DatasetPublishTableauPayload = {
  connection_id: string;
  tableau_project_id: string;
  datasource_name: string;
  write_mode: "replace" | "create_only";
};

export type DatasetPublishTableauResponse = {
  success: boolean;
  message: string;
  run: PipelineRunRecord;
  connection: BiConnectionPublishSummary;
  tableau_site_id: string | null;
  tableau_project_id: string;
  datasource_name: string;
  write_mode: string;
  row_count_published: number | null;
  row_count_attempted: number | null;
  tableau_datasource_id: string | null;
  provider_outcome: string | null;
  summary_json: Record<string, unknown> | null;
};

export type ProjectListResponse = { items: ProjectSummary[] };

/** A run as the cross-project operator view (/runs) shows it. */
export type OperatorRunRow = {
  id: string;
  project_id: string;
  project_name: string;
  run_type: string;
  status: string;
  pipeline_name: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type OperatorRunsResponse = { items: OperatorRunRow[] };

/** A dataset as the cross-project search view (/datasets) shows it. */
export type OperatorDatasetRow = {
  id: string;
  project_id: string;
  project_name: string;
  name: string;
  status: string;
  ingestion_status: string;
  is_derived: boolean;
  file_type: string | null;
  row_count: number | null;
  column_count: number | null;
  created_at: string;
};

export type OperatorDatasetsResponse = { items: OperatorDatasetRow[] };

/** One entry in the admin cross-project Audit Center (/audits). */
export type AuditCenterRow = {
  id: string;
  created_at: string;
  actor_username: string | null;
  project_id: string | null;
  project_name: string | null;
  method: string;
  path: string;
  action: string;
  resource_type: string | null;
  outcome: string;
  status_code: number;
  correlation_id: string | null;
};

export type AuditCenterResponse = {
  items: AuditCenterRow[];
  retention_days: number;
};
export type SourceListResponse = { items: SourceRecord[] };
export type DatasetListResponse = { items: DatasetRecord[] };
export type PipelineRunListResponse = { items: PipelineRunRecord[] };

/** One immutable snapshot in a dataset's history (time travel, Phase 18). The
 * storage key is deliberately not part of the contract. */
export type DatasetVersion = {
  id: string;
  dataset_id: string;
  version_number: number;
  content_hash: string | null;
  file_name: string | null;
  file_type: string | null;
  row_count: number | null;
  column_count: number | null;
  pipeline_run_id: string | null;
  created_by_user_id: string | null;
  created_at: string;
  /** `active`; `pending_delete` (a retention sweep marked it -- removal follows
   * a grace period unless something pins it first); or `pruned` (data removed,
   * this record kept as a tombstone). */
  retention_state: "active" | "pending_delete" | "pruned";
  delete_after: string | null;
  pruned_at: string | null;
  /** Open pins holding the version (a rollback or replay in progress). */
  active_pins: number;
};

export type DatasetVersionListResponse = {
  /** Newest first, so the current head reads at the top. */
  items: DatasetVersion[];
  /** The head version number, or null for a dataset with no recorded history. */
  current_version: number | null;
};

export type DatasetVersionDiffRequest = {
  from_version: number;
  to_version: number;
  /** Columns that uniquely identify a row in BOTH versions; without them the
   * diff cannot classify changed rows and says so. */
  identity_columns?: string[];
};

export type DatasetVersionDiff = {
  dataset_id: string;
  from_version: number;
  to_version: number;
  identical: boolean;
  rows_before: number | null;
  rows_after: number | null;
  columns_added: string[];
  columns_removed: string[];
  rows_added: number | null;
  rows_removed: number | null;
  rows_changed: number | null;
  changed_available: boolean;
  reason: string | null;
  sample_added: Record<string, unknown>[];
  sample_removed: Record<string, unknown>[];
  sample_changed: Record<string, unknown>[];
  cells_changed_by_column: Record<string, number>;
  sample_limit: number;
  method: string;
};

/** SQL over one recorded version of a stored dataset (time travel). Exactly
 * one of `version_number` / `as_of` picks the version; neither means the head.
 * The data is exposed as a table named `dataset`. */
export type DatasetTemporalQueryRequest = {
  sql: string;
  version_number?: number | null;
  as_of?: string | null;
  parameters?: Record<string, unknown>;
  row_limit?: number;
};

export type DatasetTemporalQueryResponse = {
  dataset_id: string;
  version_number: number;
  version_published_at: string;
  requested_as_of: string | null;
  table_name: string;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  row_limit: number;
  duration_ms: number;
  warnings: string[];
};

export type CreateProjectPayload = {
  name: string;
  description?: string | null;
  status: ProjectStatus;
  slug?: string | null;
};

export type CreateSourcePayload = {
  name: string;
  source_type: SourceType;
  description?: string | null;
  status: SourceStatus;
  config_json: Record<string, unknown>;
};

export type CreateDatasetPayload = {
  name: string;
  source_id?: string | null;
  original_filename?: string | null;
  status: DatasetStatus;
  row_count?: number | null;
  column_count?: number | null;
  schema_snapshot?: Record<string, unknown> | null;
};

export type DatasetUploadResponse = {
  dataset: DatasetRecord;
  run: PipelineRunRecord;
};

export type TransformationStepType =
  | "rename_columns"
  | "cast_column_types"
  | "trim_strings"
  | "drop_columns"
  | "select_columns"
  | "fill_nulls"
  | "drop_null_rows"
  | "remove_duplicates"
  | "filter_rows"
  | "parse_dates";

export type TransformationStep = {
  step_type: TransformationStepType;
  config: Record<string, unknown>;
};

export type TransformationPipelineRecord = {
  id: string;
  project_id: string;
  base_dataset_id: string;
  created_by_user_id: string | null;
  name: string;
  description: string | null;
  status: TransformationPipelineStatus;
  steps_json: TransformationStep[];
  step_count: number;
  created_at: string;
  updated_at: string;
};

export type TransformationPipelineListResponse = {
  items: TransformationPipelineRecord[];
};

export type TransformationPipelineCreatePayload = {
  name: string;
  description?: string | null;
  status?: TransformationPipelineStatus;
  steps_json: TransformationStep[];
};

export type TransformationPipelineUpdatePayload = {
  name?: string;
  description?: string | null;
  status?: TransformationPipelineStatus;
  steps_json?: TransformationStep[];
};

export type TransformationPreviewSchemaColumn = {
  name: string;
  /** The seven-word vocabulary the API has always spoken. */
  inferred_type: string;
  /**
   * The same column read into the canonical type lattice, e.g. "decimal(38,10)"
   * or "timestamp(6,tz)". Optional because responses produced before the
   * lattice existed do not carry it.
   */
  canonical_type?: string | null;
  nullable?: boolean | null;
};

/** Where one step would run on a full run against the source, and why. */
export type ExecutionStepPlacement = {
  node: string;
  pushed: boolean;
  reason: string;
};

/**
 * Where a pipeline's work would happen.
 *
 * Describes the RUN, not the preview: a preview always reads the materialised
 * file. "Nothing pushes down, because this is a stored file" is the useful
 * answer, and it is invisible otherwise.
 */
export type ExecutionPlanRead = {
  source_type: string;
  surface: string;
  pushed_steps: number;
  local_steps: number;
  sql?: string | null;
  placements: ExecutionStepPlacement[];
  note?: string;
};

/** What one applied step did to the frame, from the pass that already ran. */
export type TransformationStepOutcome = {
  index: number;
  step_type: string;
  rows_before: number;
  rows_after: number;
  columns_before: number;
  columns_after: number;
};

export type TransformationPreviewSchema = {
  ordered_columns: string[];
  columns: TransformationPreviewSchemaColumn[];
};

export type TransformationPreviewResponse = {
  preview_rows: Record<string, unknown>[];
  preview_columns: string[];
  row_count_before: number;
  row_count_after: number;
  column_count_before: number;
  column_count_after: number;
  schema_before: TransformationPreviewSchema;
  schema_after: TransformationPreviewSchema;
  warnings: string[];
};

export type TransformationPreviewRequestPayload = {
  steps: TransformationStep[];
};

export type SuggestionConfidence = "low" | "medium" | "high";

export type TransformationSourceSignal = {
  signal: string;
  detail?: string | null;
  value?: unknown;
};

export type TransformationSuggestion = {
  suggestion_id: string;
  step_type: TransformationStepType | string;
  title: string;
  explanation: string;
  confidence: SuggestionConfidence;
  config: Record<string, unknown>;
  source_signals: TransformationSourceSignal[];
  priority: number;
};

export type DatasetTransformationSuggestionsResponse = {
  dataset_id: string;
  project_id: string;
  suggestions: TransformationSuggestion[];
};

export type TransformationRunResponse = {
  run: PipelineRunRecord;
  dataset: DatasetRecord;
};

export type ScheduleType =
  | "transformation_pipeline_run"
  | "postgres_publish"
  /** The nightly connector schema watch — see `service_connectors/sweep.py`. */
  | "connector_schema_watch";

export type ScheduledOperationRecord = {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  schedule_type: ScheduleType;
  cron_expression: string;
  timezone: string | null;
  enabled: boolean;
  target_config_json: Record<string, unknown>;
  created_by_user_id: string | null;
  last_triggered_at: string | null;
  next_run_at: string | null;
  last_run_started_at: string | null;
  last_run_finished_at: string | null;
  last_run_status: string | null;
  last_error_message: string | null;
  execution_count: number;
  retry_count_current: number;
  max_retries: number;
  next_retry_at: string | null;
  last_failure_at: string | null;
  claim_owner_id?: string | null;
  claim_acquired_at?: string | null;
  claim_expires_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type ScheduleListResponse = { items: ScheduledOperationRecord[] };

export type ScheduleCreatePayload = {
  name: string;
  description?: string | null;
  schedule_type: ScheduleType;
  cron_expression: string;
  timezone?: string | null;
  enabled?: boolean;
  target_config: Record<string, unknown>;
};

export type ScheduleUpdatePayload = {
  name?: string;
  description?: string | null;
  cron_expression?: string;
  timezone?: string | null;
  enabled?: boolean;
  target_config?: Record<string, unknown>;
};

export type ScheduleTogglePayload = { enabled: boolean };

export type ScheduleTriggerResponse = {
  success: boolean;
  message: string;
  schedule: ScheduledOperationRecord;
  triggered_run: PipelineRunRecord | null;
  transformation: TransformationRunResponse | null;
  postgres_publish: DatasetPublishPostgresResponse | null;
};

export type AuthUser = {
  id: string;
  username: string;
  role: string;
  is_active: boolean;
  email?: string | null;
  display_name?: string | null;
  created_at: string;
  updated_at: string;
};

export type ApiToken = {
  id: string;
  name: string;
  prefix: string;
  scope: "read" | "write" | "admin";
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
};

export type ApiTokenListResponse = { items: ApiToken[] };

export type ApiTokenCreatedResponse = { token: ApiToken; secret: string };

export type OneTimeCode = {
  user_id: string;
  username: string;
  /** Null when the code was emailed to the person: the admin never sees it. */
  code: string | null;
  purpose: string;
  expires_in_minutes: number;
  emailed: boolean;
  /** Masked address it went to, when emailed. */
  emailed_to: string | null;
  /** Why it was not emailed although the account has an address. */
  email_error: string | null;
};

export type UserNotificationRecord = {
  id: string;
  user_id: string;
  project_id: string | null;
  type: string;
  level: string;
  title: string;
  message: string;
  related_run_id: string | null;
  related_schedule_id: string | null;
  related_dataset_id: string | null;
  related_pipeline_id: string | null;
  is_read: boolean;
  created_at: string;
  updated_at: string;
  read_at: string | null;
};

export type UserNotificationListResponse = {
  items: UserNotificationRecord[];
  unread_count: number;
};

export type ExternalNotificationTargetType = "email" | "slack_webhook";

export const EXTERNAL_NOTIFICATION_EVENT_TYPES = [
  "schedule_run_failed",
  "schedule_run_succeeded",
  "dataset_publish_failed",
  "dataset_publish_succeeded",
  "transformation_run_failed",
  "transformation_run_succeeded",
] as const;

export type ExternalNotificationEventType = (typeof EXTERNAL_NOTIFICATION_EVENT_TYPES)[number];

export type ExternalNotificationTargetRecord = {
  id: string;
  project_id: string;
  name: string;
  target_type: ExternalNotificationTargetType;
  enabled: boolean;
  config_json: Record<string, unknown>;
  subscribed_event_types: string[];
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
};

export type ExternalNotificationTargetListResponse = {
  items: ExternalNotificationTargetRecord[];
};

export type ExternalNotificationTargetCreatePayload = {
  name: string;
  target_type: ExternalNotificationTargetType;
  enabled: boolean;
  config_json: Record<string, unknown>;
  subscribed_event_types: string[];
};

export type ExternalNotificationTargetUpdatePayload = {
  name?: string;
  enabled?: boolean;
  config_json?: Record<string, unknown>;
  subscribed_event_types?: string[];
};

export type ExternalNotificationTargetTestResponse = {
  success: boolean;
  message: string;
};

export type ServiceHealthStatus = "healthy" | "degraded" | "unhealthy";

export type ServiceStatusRecord = {
  name: string;
  status: ServiceHealthStatus;
  details: Record<string, unknown>;
};

export type SchedulerOperationalSnapshot = {
  internal_api_configured: boolean;
  scheduler_runtime_id_configured: boolean;
  total_schedules: number;
  due_now_count: number;
  lease_active_count: number;
  stale_lease_count: number;
  note: string;
};

export type RuntimeComponentHeartbeat = {
  component: string;
  host: string | null;
  last_beat_at: string | null;
  age_seconds: number | null;
  interval_seconds: number | null;
  status: string;
  healthy: boolean;
  detail: Record<string, unknown>;
};

export type RuntimeSnapshot = {
  components: RuntimeComponentHeartbeat[];
  healthy: boolean;
};

export type PlatformStatusResponse = {
  status: ServiceHealthStatus;
  service: string;
  environment: string;
  version: string;
  services: ServiceStatusRecord[];
  checked_at: string;
  scheduler: SchedulerOperationalSnapshot;
  runtime: RuntimeSnapshot;
};

export type HealthLiveResponse = {
  status: string;
  service: string;
  environment: string;
  version: string;
  timestamp: string;
};

export type LoginPayload = {
  username: string;
  password: string;
};

export type AuthTokenResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: AuthUser;
};

/** The password step's result: either a session, or a demand for the code. */
export type LoginResult = {
  status: "ok" | "mfa_required";
  access_token: string | null;
  token_type: string;
  expires_in: number | null;
  user: AuthUser | null;
  mfa_ticket: string | null;
};

export type MfaStatus = {
  enrolled: boolean;
  active: boolean;
  recovery_codes_remaining: number;
};

export type MfaEnrollResponse = {
  secret: string;
  otpauth_uri: string;
  qr_svg: string;
};

export type MfaRecoveryCodesResponse = {
  recovery_codes: string[];
};

/**
 * Phase 11 — ingestion intelligence.
 *
 * Every stage of the sniffing pipeline returns one of these: what it decided,
 * how sure it is, and the evidence it decided from. A `certainty` of
 * `"ambiguous"` with `blocking: true` means the file genuinely does not say —
 * an unreadable date, a separator that could be decimal or thousands — and the
 * import waits for an answer rather than picking one.
 */
export type IngestCertainty = "certain" | "likely" | "uncertain" | "ambiguous";

export type IngestFinding = {
  stage: string;
  value: unknown;
  certainty: IngestCertainty;
  confidence: number;
  reason: string;
  candidates: { value: unknown; score: number; reason: string }[];
  evidence: string[];
  needs_review: boolean;
  blocking: boolean;
};

export type IngestColumnSpec = {
  name: string;
  type: string;
  date_format: string | null;
  decimal: string | null;
  thousands: string | null;
  null_tokens: string[];
  rename: string | null;
  include: boolean;
};

export type IngestSpec = {
  version: number;
  format: string;
  container: string;
  options: Record<string, unknown>;
  columns: IngestColumnSpec[];
  derived_from: string | null;
};

export type IngestAnalysis = {
  container: string;
  format: string;
  read_options: Record<string, unknown>;
  findings: IngestFinding[];
  columns: {
    name: string;
    type_name: string;
    finding: IngestFinding;
    rejected: { value: string; count: number }[];
    null_tokens: string[];
    conformity: number;
    excel_errors: number;
  }[];
  members: { name: string; size_bytes: number }[];
  tables: string[];
  warnings: string[];
  blocked_by: IngestFinding[];
  needs_review: number;
  row_count_sampled: number;
};

export type AnalyseUploadResponse = {
  file_name: string;
  file_size_bytes: number;
  analysis: IngestAnalysis;
  spec: IngestSpec;
  preview: {
    columns: string[];
    dtypes: Record<string, string>;
    rows: Record<string, unknown>[];
  };
  conversion_notes: string[];
  matched_spec: {
    id: string;
    label: string;
    use_count: number;
    last_used_at: string | null;
    applied: boolean;
  } | null;
  questions: IngestFinding[];
};

export type IngestSpecRecord = {
  id: string;
  label: string;
  name_pattern: string;
  column_fingerprint: string;
  file_format: string;
  spec: IngestSpec;
  use_count: number;
  last_used_at: string | null;
  created_at: string | null;
};

export type IngestSpecListResponse = { items: IngestSpecRecord[] };
