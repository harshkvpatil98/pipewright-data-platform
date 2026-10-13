import type { DestinationType } from "@platform/shared-types";

import type { IconName } from "@/components/ui/icon";

export type DestinationField = {
  key: string;
  label: string;
  kind: "text" | "number" | "password" | "select";
  required?: boolean;
  placeholder?: string;
  help?: string;
  options?: { value: string; label: string }[];
  defaultValue?: string;
};

export type DestinationKind = {
  type: DestinationType;
  label: string;
  icon: IconName;
  /** What it receives, in a few words. */
  receives: string;
  description: string;
  /** Delivers into tables (databases) or files (storage). */
  delivers: "table" | "file";
  fields: DestinationField[];
};

const serverFields = (port: string): DestinationField[] => [
  { key: "host", label: "Server address", kind: "text", required: true, placeholder: "db.example.com" },
  { key: "port", label: "Port", kind: "number", required: true, defaultValue: port },
  { key: "database", label: "Database", kind: "text", required: true },
  { key: "username", label: "User name", kind: "text", required: true },
  {
    key: "password",
    label: "Password",
    kind: "password",
    required: true,
    help: "Stored encrypted. Use an account that can only write where Pipewright delivers.",
  },
];

/** Every kind of destination that receives datasets, in the order people pick them. */
export const DESTINATION_KINDS: DestinationKind[] = [
  {
    type: "postgres",
    label: "PostgreSQL",
    icon: "database",
    receives: "Tables",
    description: "Replace a table, add rows to it, or update matching rows.",
    delivers: "table",
    fields: [
      ...serverFields("5432"),
      { key: "schema", label: "Schema", kind: "text", placeholder: "public", help: "Leave empty for the default." },
      {
        key: "ssl_mode",
        label: "Encryption",
        kind: "select",
        defaultValue: "prefer",
        options: [
          { value: "prefer", label: "Use it when the server offers it" },
          { value: "require", label: "Always require it" },
          { value: "verify-full", label: "Require it and check the certificate" },
          { value: "disable", label: "Never use it" },
        ],
      },
    ],
  },
  {
    type: "mysql",
    label: "MySQL",
    icon: "database",
    receives: "Tables",
    description: "MySQL or MariaDB. Replace a table, add rows, or update matching rows.",
    delivers: "table",
    fields: serverFields("3306"),
  },
  {
    type: "s3",
    label: "S3 or compatible storage",
    icon: "folder",
    receives: "Files",
    description: "CSV or Parquet files in a bucket: Amazon S3, MinIO, Cloudflare R2, Wasabi.",
    delivers: "file",
    fields: [
      { key: "bucket", label: "Bucket", kind: "text", required: true },
      { key: "prefix", label: "Folder in the bucket", kind: "text", placeholder: "exports", help: "Leave empty to write at the top." },
      { key: "region", label: "Region", kind: "text", placeholder: "us-east-1" },
      {
        key: "endpoint_url",
        label: "Address",
        kind: "text",
        placeholder: "https://minio.example.com",
        help: "Only for S3-compatible stores. Leave empty for Amazon S3.",
      },
      { key: "access_key_id", label: "Access key", kind: "text", required: true },
      { key: "secret_access_key", label: "Secret key", kind: "password", required: true, help: "Stored encrypted." },
    ],
  },
  {
    type: "local_export",
    label: "Server folder",
    icon: "folder",
    receives: "Files",
    description: "CSV or Parquet files in a folder on the server Pipewright runs on.",
    delivers: "file",
    fields: [
      {
        key: "path",
        label: "Folder",
        kind: "text",
        required: true,
        placeholder: "exports",
        help: "A folder inside the server's shared files folder.",
      },
    ],
  },
];

export const KIND_BY_TYPE = new Map(DESTINATION_KINDS.map((kind) => [kind.type, kind]));

/** The form's starting values for a kind. */
export function emptyValues(kind: DestinationKind): Record<string, string> {
  return Object.fromEntries(kind.fields.map((field) => [field.key, field.defaultValue ?? ""]));
}

/** A saved destination's values, secrets left blank so they are only replaced when typed. */
export function valuesFrom(kind: DestinationKind, config: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(
    kind.fields.map((field) => [
      field.key,
      field.kind === "password" ? "" : String(config[field.key] ?? field.defaultValue ?? ""),
    ]),
  );
}

/**
 * The config to send. Empty optional fields are left out; an empty secret is
 * left out when editing, which keeps the saved one.
 */
export function configFrom(kind: DestinationKind, values: Record<string, string>): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  for (const field of kind.fields) {
    const raw = (values[field.key] ?? "").trim();
    if (!raw) continue;
    config[field.key] = field.kind === "number" ? Number.parseInt(raw, 10) : field.kind === "password" ? values[field.key] : raw;
  }
  return config;
}

/** The first required field left empty, for a message before saving. */
export function missingField(kind: DestinationKind, values: Record<string, string>, editing: boolean): string | null {
  for (const field of kind.fields) {
    if (!field.required) continue;
    if (editing && field.kind === "password") continue;
    if (!(values[field.key] ?? "").trim()) return field.label;
  }
  return null;
}
