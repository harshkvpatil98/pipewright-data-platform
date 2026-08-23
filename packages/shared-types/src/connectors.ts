/** Contracts for the connector catalogue. Mirrors service-connectors. */

export type ConnectorCategory =
  | "database"
  | "warehouse"
  | "api"
  | "storage"
  | "saas"
  | "nosql"
  | "file";

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
