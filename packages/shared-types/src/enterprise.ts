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
  /** Session lifetime for this tenant's people, in minutes. Null follows the deployment default. */
  session_max_minutes: number | null;
  is_active: boolean;
  project_count: number;
  member_count: number;
  created_at: string;
};

/**
 * The bounds a session policy is held to, mirroring `service_auth.contracts`.
 * The server clamps to the same range whatever arrives, so these exist to make
 * the form refuse a value before it is sent rather than to be the rule.
 */
export const MIN_SESSION_MINUTES = 5;
export const MAX_SESSION_MINUTES = 60 * 24 * 30;

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

/**
 * What SAML can do on this deployment. `implemented` is about the code and
 * never changes; `supported` is about this install, and is only true when the
 * signature library is present *and* a provider is configured.
 */
export type SamlStatus = {
  supported: boolean;
  implemented: boolean;
  signature_library: string;
  signature_library_available: boolean;
  configured: boolean;
  reason: string;
  notes: string;
  alternative: string;
};

export type SsoStatus = {
  oidc_configured: boolean;
  issuer: string | null;
  saml: SamlStatus;
  note: string;
};

/** What the login screen reads to decide which sign-in buttons to show. */
export type SsoAvailability = {
  oidc_configured: boolean;
  saml_configured: boolean;
  saml: SamlStatus;
};
