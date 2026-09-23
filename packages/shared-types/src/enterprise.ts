/** Contracts for tenancy, fine-grained security, retention, and usage. */

export type ColumnAction = "allow" | "mask" | "hash" | "redact" | "deny";
export type ErasureKind = "email" | "phone" | "id" | "name";

export type Organisation = {
  id: string;
  name: string;
  slug: string;
  plan: string;
  max_projects: number | null;
  max_datasets: number | null;
  is_active: boolean;
  project_count: number;
  member_count: number;
  created_at: string;
};

export type OrganisationListResponse = { items: Organisation[] };

export type LimitsResponse = {
  limited: boolean;
  organisation: string | null;
  plan: string | null;
  projects: { used: number; limit: number | null } | null;
  datasets: { used: number; limit: number | null } | null;
  warnings: string[];
  reason: string | null;
};

export type SecurityRowRule = {
  column: string;
  operator: string;
  value: unknown;
};

export type SecurityColumnRule = {
  column: string;
  action: ColumnAction;
};

export type SecurityPolicy = {
  id: string;
  project_id: string;
  dataset_id: string;
  name: string;
  role: "viewer" | "operator" | "editor" | "admin";
  row_rules: SecurityRowRule[];
  column_rules: SecurityColumnRule[];
  enabled: boolean;
  created_at: string;
};

export type SecurityPolicyListResponse = {
  items: SecurityPolicy[];
  warnings: string[];
};

export type SecurityPreview = {
  dataset_id: string;
  role: string;
  /** Set when previewed as a specific person rather than a bare role. */
  viewed_as_username?: string | null;
  rows_before: number;
  rows_after: number;
  rows_hidden: number;
  columns_masked: string[];
  columns_removed: string[];
  policies_applied: string[];
  restricted: boolean;
  summary: string;
  sample_rows: Record<string, unknown>[];
};

export type RetentionPolicy = {
  id: string;
  project_id: string;
  resource_type: string;
  resource_label: string;
  retain_days: number;
  enabled: boolean;
  /** Report-only until somebody has looked at what it would remove. */
  dry_run: boolean;
  last_run_at: string | null;
  last_deleted_count: number;
};

export type RetentionListResponse = {
  items: RetentionPolicy[];
  retainable: Record<string, string>;
};

export type RetentionRunResponse = {
  plans: Record<string, unknown>[];
  total_matched: number;
  total_deleted: number;
  summary: string;
};

export type ErasureRequest = {
  id: string;
  project_id: string;
  subject_kind: ErasureKind;
  status: string;
  datasets_searched: number;
  rows_affected: number;
  report: Record<string, unknown> | null;
  completed_at: string | null;
  created_at: string;
};

export type ErasureListResponse = { items: ErasureRequest[] };

export type UsageTotal = {
  subject_type: string;
  subject_id: string | null;
  subject_name: string;
  runs: number;
  rows_processed: number;
  compute_seconds: number;
  bytes_written: number;
  average_rows_per_run: number;
};

export type UsageResponse = {
  period_days: number;
  since: string;
  totals: UsageTotal[];
  rows_processed: number;
  compute_seconds: number;
  bytes_written: number;
  summary: string;
};

export type SsoStatus = {
  oidc_configured: boolean;
  issuer: string | null;
  saml: { supported: boolean; reason: string; alternative: string };
  note: string;
};
