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
  error: "Error — failing rows are quarantined",
  warn: "Warning — reported, nothing is blocked",
  warning: "Warning — reported, nothing is blocked",
};

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
