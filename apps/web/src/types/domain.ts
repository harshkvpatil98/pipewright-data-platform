export type ProjectStatus = "active" | "draft" | "archived";
export type SourceType = "csv" | "excel" | "json" | "api" | "postgres" | "s3";
export type SourceStatus = "active" | "pending" | "disabled";
export type DatasetStatus = "registered" | "processing" | "ready" | "failed";
export type IngestionStatus = "pending" | "queued" | "running" | "succeeded" | "failed";

export type ProjectSummary = {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  status: ProjectStatus;
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
  name: string;
  original_filename: string | null;
  file_name: string | null;
  file_type: string | null;
  file_size_bytes: number | null;
  status: DatasetStatus;
  ingestion_status: IngestionStatus;
  row_count: number | null;
  column_count: number | null;
  schema_snapshot: Record<string, unknown> | null;
  schema_json: Record<string, unknown> | null;
  profile_json: Record<string, unknown> | null;
  preview_json: Record<string, unknown> | null;
  ingestion_error: string | null;
  last_profiled_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ProjectListResponse = { items: ProjectSummary[] };
export type SourceListResponse = { items: SourceRecord[] };
export type DatasetListResponse = { items: DatasetRecord[] };

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
