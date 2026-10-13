/**
 * Turns the parser metadata stored on an upload run into words.
 *
 * The metadata mixes plain settings (`encoding: "utf-8"`) with structured
 * evidence (`findings: [{stage, value, reason, ...}]`). Rendering every value
 * with `String()` printed the evidence as "[object Object],[object Object]",
 * so each key is either given a label and a readable value or deliberately
 * left out. Nothing here ever stringifies an object.
 */

export type ParserFact = { label: string; value: string };

export type ParserNote = {
  stage: string;
  label: string;
  /** The sentence the reader wrote about this decision. */
  reason: string;
  needsReview: boolean;
};

export type ParserDescription = { facts: ParserFact[]; notes: ParserNote[] };

const FACT_LABELS: Record<string, string> = {
  format: "File format",
  container: "Packaged as",
  encoding: "Text encoding",
  delimiter: "Column separator",
  quote_char: "Quote character",
  escape_char: "Escape character",
  sheet_name: "Sheet",
  has_header: "First row is headings",
  skip_rows: "Lines skipped before the table",
  table: "Table",
  record_element: "Record element",
  spec_supplied: "Saved import settings",
};

/** Keys shown elsewhere on the page, or which only repeat another key. */
const OMITTED = new Set([
  "findings",
  "needs_review",
  "row_count",
  "column_count",
  "sheet",
  "column_widths",
  "tables",
  "archive_members",
]);

const STAGE_LABELS: Record<string, string> = {
  format: "File format",
  container: "Packaging",
  encoding: "Text encoding",
  delimiter: "Column separator",
  quote_char: "Quotes",
  header_row: "Header row",
  column_boundaries: "Column widths",
  column_type: "Column type",
  date_format: "Dates",
  number_format: "Numbers",
  excel_serial_dates: "Excel dates",
  formula_errors: "Formula errors",
  heterogeneous_records: "Record shapes",
  malformed_lines: "Unreadable lines",
  ragged_rows: "Uneven rows",
  record_element: "Records",
  records_path: "Records",
  table_choice: "Table",
};

const SEPARATOR_NAMES: Record<string, string> = {
  ",": "comma",
  ";": "semicolon",
  "\t": "tab",
  "|": "pipe",
  " ": "space",
};

function humanise(key: string): string {
  const spaced = key.replace(/_/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function formatValue(key: string, value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "boolean") {
    if (key === "spec_supplied") return value ? "Used" : null;
    return value ? "Yes" : "No";
  }
  if (typeof value === "number") {
    if (key === "skip_rows" && value === 0) return null;
    return String(value);
  }
  if (typeof value === "string") {
    if (key === "delimiter") {
      const name = SEPARATOR_NAMES[value];
      return name ? `${name} (${value === "\t" ? "\\t" : value})` : value;
    }
    if (key === "format" || key === "container") return value.toUpperCase();
    return value;
  }
  if (Array.isArray(value) && value.every((item) => ["string", "number"].includes(typeof item))) {
    return value.length > 0 ? value.join(", ") : null;
  }
  // Structured values are evidence, not settings; they are described as notes
  // or not at all, never printed as "[object Object]".
  return null;
}

type RawFinding = {
  stage?: unknown;
  reason?: unknown;
  needs_review?: unknown;
  blocking?: unknown;
};

function readNotes(findings: unknown): ParserNote[] {
  if (!Array.isArray(findings)) return [];
  const notes: ParserNote[] = [];
  for (const item of findings) {
    if (!item || typeof item !== "object") continue;
    const finding = item as RawFinding;
    const stage = typeof finding.stage === "string" ? finding.stage : "";
    const reason = typeof finding.reason === "string" ? finding.reason.trim() : "";
    if (!reason) continue;
    notes.push({
      stage,
      label: STAGE_LABELS[stage] ?? (stage ? humanise(stage) : "Note"),
      reason,
      needsReview: finding.needs_review === true || finding.blocking === true,
    });
  }
  // Anything that asks for a second look comes first.
  return notes.sort((a, b) => Number(b.needsReview) - Number(a.needsReview));
}

export function describeParserMetadata(
  metadata: Record<string, unknown> | null | undefined,
): ParserDescription {
  if (!metadata) return { facts: [], notes: [] };
  const facts: ParserFact[] = [];
  for (const [key, value] of Object.entries(metadata)) {
    if (OMITTED.has(key)) continue;
    const formatted = formatValue(key, value);
    if (formatted === null) continue;
    facts.push({ label: FACT_LABELS[key] ?? humanise(key), value: formatted });
  }
  return { facts, notes: readNotes(metadata.findings) };
}
