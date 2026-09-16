/** Contracts for the connector catalogue. Mirrors service-connectors. */

export type ConnectorCategory =
  | "database"
  | "warehouse"
  | "api"
  | "storage"
  | "saas"
  | "nosql"
  | "file"
  | "timeseries"
  | "streaming"
  | "lakehouse";

/**
 * How much is known about whether a connector actually works.
 *
 * With nineteen connectors, "five are unverified" is a footnote. With two
 * hundred, an undifferentiated list is a lie by omission — so the tier travels
 * with every connector and is shown wherever one is chosen.
 */
export type ConnectorTier = 1 | 2 | 3 | 4;

export type ConnectorCapability =
  | "test"
  | "discover"
  | "schema"
  | "read"
  | "incremental"
  | "write";

export type ConfigFieldKind =
  | "string"
  | "secret"
  | "number"
  | "boolean"
  | "select"
  | "text";

export type ConnectorConfigField = {
  name: string;
  label: string;
  kind: ConfigFieldKind;
  required: boolean;
  default: unknown;
  help: string | null;
  options: string[];
  placeholder: string | null;
};

export type ConnectorSpec = {
  type: string;
  label: string;
  category: ConnectorCategory;
  description: string;
  config_fields: ConnectorConfigField[];
  capabilities: ConnectorCapability[];
  secret_fields: string[];
  driver_package: string | null;
  documentation_url: string | null;
  /** False when the driver this connector needs is not installed here. */
  available: boolean;
  unavailable_reason: string | null;
  tier: ConnectorTier;
  tier_label: string;
  tier_badge: string;
  tier_explanation: string;
  /** False for tier 4: written from documentation and never executed. */
  verified: boolean;
  /** The test file backing a tier above 4, so the claim is a citation. */
  verified_by: string | null;
  /** "handwritten" | "manifest" | "dialect" | "matrix". */
  origin: string;
};

export type ConnectorTierSummary = {
  tier: ConnectorTier;
  label: string;
  badge: string;
  explanation: string;
  count: number;
  verified: boolean;
};

export type ConnectorHealth = {
  total: number;
  available: number;
  verified: number;
  tiers: ConnectorTierSummary[];
  categories: { category: string; total: number; available: number; verified: number }[];
  origins: Record<string, number>;
  missing_packages: { package: string; unlocks: number }[];
  formats: number;
  store_format_combinations: number;
};

export type ConnectorCatalogResponse = {
  items: ConnectorSpec[];
  categories: ConnectorCategory[];
};

export type FileFormat = {
  name: string;
  label: string;
  extensions: string[];
  /** Whether the format stores column types alongside the values. */
  typed: boolean;
  writable: boolean;
  description: string;
};

export type FormatCatalogResponse = {
  items: FileFormat[];
  compressions: string[];
};

export type ConnectorTestResponse = {
  success: boolean;
  message: string;
  latency_ms: number | null;
  server_version: string | null;
  warnings: string[];
};

export type ConnectorStream = {
  name: string;
  namespace: string | null;
  kind: string;
  qualified_name: string;
  detail: Record<string, unknown>;
};

export type StreamListResponse = {
  connector_type: string;
  items: ConnectorStream[];
};

/**
 * The connector schema watch — see `service_connectors/sweep.py`.
 *
 * SaaS vendors change APIs without telling anybody, and a pipeline built on
 * `attributes.created` keeps working until the morning it is
 * `attributes.created_at`. The watch re-reads each connection's schema on a
 * schedule and files a drift incident rather than letting a run fail at 3am.
 */
export type WatchedStream = {
  connection_id: string;
  connector_type: string;
  stream: string;
  columns: number;
  /** "live" when the source described itself, "declared" when a manifest did. */
  source: string;
  observed_at: string | null;
  last_severity: string;
  last_summary: string | null;
  drift_count: number;
};

export type ConnectorWatchStatus = {
  items: WatchedStream[];
  /** Connectors whose schema can be compared without a live credential. */
  describable: string[];
};

export type ConnectorSweepOutcome = {
  connection_id: string;
  connection_name: string;
  connector_type: string;
  stream: string;
  checked: boolean;
  severity: string;
  summary: string;
  added_columns: string[];
  removed_columns: string[];
  type_changes: { column: string; previous_type: string; current_type: string }[];
  skipped_reason: string;
  first_look: boolean;
  incident_id: string | null;
  source: string;
};

export type ConnectorSweepReport = {
  checked_at: string;
  connections: number;
  streams_checked: number;
  streams_skipped: number;
  drifted: number;
  breaking: number;
  incidents: string[];
  skipped_connections: { connection_id: string; name: string; reason: string }[];
  results: ConnectorSweepOutcome[];
};
