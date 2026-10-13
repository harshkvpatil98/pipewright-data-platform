/**
 * The product's vocabulary, in the buyer's language.
 *
 * Engine names (`float64`, `not_null`, `config.conditions must be a non-empty
 * list.`) are truths for engineers and noise for everyone else. This module is
 * the single place raw names become display names, so no surface invents its
 * own translation and the review's "engineer dialect" finding cannot creep
 * back one string at a time. The raw value always survives alongside the
 * label (a title attribute, a muted suffix) — the goal is demotion, not
 * concealment.
 */

const TYPE_LABELS: Record<string, string> = {
  string: "Text",
  str: "Text",
  text: "Text",
  int: "Whole number",
  int64: "Whole number",
  integer: "Whole number",
  float: "Decimal number",
  float64: "Decimal number",
  double: "Decimal number",
  number: "Decimal number",
  decimal: "Decimal (exact)",
  bool: "True / false",
  boolean: "True / false",
  date: "Date",
  datetime: "Date & time",
  timestamp: "Date & time",
  time: "Time",
  object: "Nested value",
  json: "Nested value",
  bytes: "Binary",
  unknown: "Unknown",
  null: "Empty",
};

/** Display name for a column type; falls back to a cleaned Title-case. */
export function typeLabel(raw: string | null | undefined): string {
  if (!raw) return "Unknown";
  const key = raw.trim().toLowerCase();
  return TYPE_LABELS[key] ?? prettify(key);
}

const RULE_TYPE_LABELS: Record<string, string> = {
  not_null: "Must have a value",
  unique: "No duplicate values",
  range: "Within a range",
  min_max: "Within a range",
  regex: "Matches a pattern",
  pattern: "Matches a pattern",
  allowed_values: "One of the allowed values",
  in_set: "One of the allowed values",
  min_length: "At least this long",
  max_length: "At most this long",
  freshness: "Recently updated",
  row_count: "Row count in bounds",
};

/** Display name for a quality rule type. */
export function ruleTypeLabel(raw: string | null | undefined): string {
  if (!raw) return "Rule";
  const key = raw.trim().toLowerCase();
  return RULE_TYPE_LABELS[key] ?? prettify(key);
}

const SEVERITY_LABELS: Record<string, string> = {
  error: "Error: failing rows are set aside",
  warn: "Warning: reported, nothing is blocked",
  warning: "Warning: reported, nothing is blocked",
};

/** The one-word form, for a badge beside a check's name. */
export function severityShortLabel(raw: string | null | undefined): string {
  const key = (raw ?? "error").trim().toLowerCase();
  return key === "warn" || key === "warning" ? "Warning" : "Error";
}

/**
 * A check's settings in words: "Column customer_email · between 0 and 100".
 * The stored config was shown as raw JSON, which says the same thing to an
 * engineer and nothing to anyone else.
 */
export function describeCheckSettings(config: Record<string, unknown> | null | undefined): string {
  if (!config) return "";
  const value = (raw: unknown): string =>
    Array.isArray(raw) ? raw.map((item) => String(item)).join(", ") : String(raw);
  const parts: string[] = [];
  const used = new Set<string>();
  const take = (key: string) => {
    used.add(key);
    return config[key];
  };
  if (config.column !== undefined) parts.push(`Column ${value(take("column"))}`);
  if (config.columns !== undefined) parts.push(`Columns ${value(take("columns"))}`);
  const min = config.min ?? config.min_value;
  const max = config.max ?? config.max_value;
  ["min", "min_value", "max", "max_value"].forEach((key) => used.add(key));
  if (min !== undefined && max !== undefined) parts.push(`between ${value(min)} and ${value(max)}`);
  else if (min !== undefined) parts.push(`at least ${value(min)}`);
  else if (max !== undefined) parts.push(`at most ${value(max)}`);
  if (config.pattern !== undefined) parts.push(`matching ${value(take("pattern"))}`);
  const allowed = config.allowed_values ?? config.values;
  ["allowed_values", "values"].forEach((key) => used.add(key));
  if (allowed !== undefined) parts.push(`one of ${value(allowed)}`);
  for (const [key, raw] of Object.entries(config)) {
    if (used.has(key) || raw === null || raw === undefined || typeof raw === "object" && !Array.isArray(raw)) {
      continue;
    }
    parts.push(`${prettify(key)} ${value(raw)}`);
  }
  return parts.join(" · ");
}

/** Display name for a rule severity. */
export function severityLabel(raw: string | null | undefined): string {
  if (!raw) return "Error";
  const key = raw.trim().toLowerCase();
  return SEVERITY_LABELS[key] ?? prettify(key);
}

/**
 * Step-validation messages come from the engine as contracts
 * ("config.conditions must be a non-empty list."). Tests pin those strings,
 * so they are translated here rather than changed at the source.
 */
const STEP_MESSAGES: Record<string, string> = {
  "config.conditions must be a non-empty list.":
    "Add at least one condition to keep rows.",
  "config.aggregations must be a non-empty list.":
    "Add at least one aggregation (for example: total of amount).",
  "config.replacements must be a non-empty list.":
    "Add at least one replacement (find → replace with).",
  "config.columns must be a non-empty list.":
    "Choose at least one column.",
  "config.mappings must be a non-empty list.":
    "Choose at least one column and the type to read it as.",
};

/** A validation message a person can act on, derived from the engine's. */
export function friendlyStepMessage(raw: string | null | undefined): string {
  if (!raw) return "";
  const exact = STEP_MESSAGES[raw.trim()];
  if (exact) return exact;
  // Generic de-jargoning: strip the config. prefix and translate the
  // "non-empty list" idiom; anything else passes through unchanged.
  return raw
    .replace(/\bconfig\.([a-z_]+)\b/g, (_m, field: string) => `“${prettify(field)}”`)
    .replace(/must be a non-empty list\.?/i, "needs at least one entry.");
}

function prettify(key: string): string {
  const words = key.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** "partially_failed" reads as "Partially failed": any stored code, in sentence case. */
export function sentenceLabel(raw: string | null | undefined): string {
  if (!raw) return "";
  const spaced = raw.replace(/[_-]+/g, " ").trim().toLowerCase();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

const FILE_FORMAT_LABELS: Record<string, string> = {
  csv: "CSV",
  excel: "Excel",
  xlsx: "Excel",
  html: "HTML",
  pdf: "PDF",
  parquet: "Parquet",
  json: "JSON",
};

/** A file format as people name it: CSV, Excel, PDF. */
export function fileFormatLabel(raw: string | null | undefined): string {
  if (!raw) return "";
  return FILE_FORMAT_LABELS[raw.toLowerCase()] ?? raw.toUpperCase();
}

const TRIGGER_LABELS: Record<string, string> = {
  manual: "By hand",
  schedule: "On schedule",
  scheduled: "On schedule",
  backfill: "Backfill",
  api: "From the API",
  retry: "Retry",
};

/** How a run started, in words. */
export function triggerLabel(raw: string | null | undefined): string {
  if (!raw) return "";
  return TRIGGER_LABELS[raw] ?? sentenceLabel(raw);
}
