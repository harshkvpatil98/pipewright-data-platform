import type { ConnectorConfigField, ConnectorSpec } from "@platform/shared-types";

/** Broad groups for the catalogue, in the order people look for them. */
export const SOURCE_GROUPS: { id: string; label: string; categories: string[] }[] = [
  { id: "database", label: "Databases", categories: ["database", "warehouse", "lakehouse"] },
  { id: "saas", label: "Apps", categories: ["saas"] },
  { id: "api", label: "APIs", categories: ["api"] },
  { id: "storage", label: "Files and storage", categories: ["storage", "file"] },
  { id: "other", label: "Other", categories: ["nosql", "timeseries", "streaming"] },
];

/** Connectors a source can be made from, tested ones first, then by name. */
export function importableConnectors(specs: ConnectorSpec[], query: string, group: string | null): ConnectorSpec[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const categories = group ? SOURCE_GROUPS.find((entry) => entry.id === group)?.categories ?? [] : null;
  return specs
    .filter((spec) => spec.capabilities.includes("read"))
    .filter((spec) => (categories ? categories.includes(spec.category) : true))
    .filter((spec) => {
      const text = `${spec.label} ${spec.description} ${spec.type.replace(/_/g, " ")}`.toLowerCase();
      return words.every((word) => text.includes(word));
    })
    .sort(
      (a, b) =>
        Number(b.available) - Number(a.available) ||
        Number(b.verified) - Number(a.verified) ||
        a.label.localeCompare(b.label),
    );
}

/** The form's starting values: each field's default, as text. */
export function initialValues(fields: ConnectorConfigField[]): Record<string, string> {
  return Object.fromEntries(
    fields.map((field) => [field.name, field.default === null || field.default === undefined ? "" : String(field.default)]),
  );
}

/** The config to send: empty fields left out (the connector fills its defaults), numbers and switches typed. */
export function connectorConfig(fields: ConnectorConfigField[], values: Record<string, string>): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  for (const field of fields) {
    const raw = values[field.name] ?? "";
    if (field.kind === "boolean") {
      config[field.name] = raw === "true";
      continue;
    }
    if (!raw.trim()) continue;
    config[field.name] = field.kind === "number" ? Number(raw) : field.kind === "secret" ? raw : raw.trim();
  }
  return config;
}

/** The first required field left empty, by its label, or null. */
export function firstMissing(fields: ConnectorConfigField[], values: Record<string, string>): string | null {
  const missing = fields.find((field) => field.required && field.kind !== "boolean" && !(values[field.name] ?? "").trim());
  return missing ? missing.label : null;
}

/**
 * Fields shown up front, and the rest for a "More settings" section.
 * Connectors declare their important settings first, so everything required
 * plus the first few fields stay visible; optional fields after those wait.
 */
export function splitFields(fields: ConnectorConfigField[], upFront = 4): {
  main: ConnectorConfigField[];
  more: ConnectorConfigField[];
} {
  const main: ConnectorConfigField[] = [];
  const more: ConnectorConfigField[] = [];
  fields.forEach((field, index) => (field.required || index < upFront ? main : more).push(field));
  return { main, more };
}
