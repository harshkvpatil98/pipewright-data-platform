/**
 * The logic behind the "review before you commit" step, kept out of the DOM.
 *
 * Same reasoning as the Studio grid: the maths is where the bugs are, and it
 * is far cheaper to test without rendering anything. What is here is the part
 * that decides *what the person is being asked* — which findings need an
 * answer, which are worth a glance, and whether the spec they have edited is
 * ready to import.
 */

import type {
  AnalyseUploadResponse,
  IngestCertainty,
  IngestColumnSpec,
  IngestFinding,
  IngestSpec,
} from "@platform/shared-types";

/** How a certainty reads, and how much attention it deserves. */
export const CERTAINTY_LABEL: Record<IngestCertainty, string> = {
  certain: "The file says so",
  likely: "Very likely",
  uncertain: "A guess",
  ambiguous: "The file does not say",
};

export const CERTAINTY_TONE: Record<IngestCertainty, string> = {
  certain: "border-success-line bg-success-soft text-success",
  likely: "border-line bg-surface-2 text-ink-2",
  uncertain: "border-warning-line bg-warning-soft text-warning",
  ambiguous: "border-danger-line bg-danger-soft text-danger",
};

/** A stage name as a person would say it. */
export const STAGE_LABEL: Record<string, string> = {
  container: "Compression",
  format: "File format",
  encoding: "Character encoding",
  delimiter: "Column separator",
  quote_char: "Quote character",
  header_row: "Header row",
  ragged_rows: "Rows with the wrong width",
  column_type: "Column type",
  date_format: "Date format",
  number_format: "Decimal separator",
  records_path: "Where the records are",
  record_element: "Which element is a row",
  json_shape: "JSON layout",
  nested_arrays: "Arrays",
  heterogeneous_records: "Missing fields",
  merged_cells: "Merged cells",
  formula_errors: "Formula errors",
  excel_serial_dates: "Dates stored as numbers",
  embedded_schema: "Declared schema",
  sql_dump: "SQL dump",
  table_choice: "Which table",
  column_boundaries: "Column positions",
  xml_namespace: "XML namespace",
  xml_attributes: "Attributes",
  malformed_lines: "Unreadable lines",
  variable_labels: "Variable labels",
  value_labels: "Coded values",
  row_groups: "Row groups",
};

export function stageLabel(stage: string): string {
  return STAGE_LABEL[stage] ?? stage.replace(/_/g, " ");
}

/**
 * The questions that must be answered before anything is imported.
 *
 * Separate from "worth a glance" on purpose. A list that mixes "this is
 * definitely UTF-8" with "this date could be either month" trains people to
 * skim past both.
 */
export function blockingQuestions(analysis: AnalyseUploadResponse): IngestFinding[] {
  return analysis.questions.length > 0
    ? analysis.questions
    : analysis.analysis.blocked_by;
}

/** Findings worth showing but not worth stopping for. */
export function reviewableFindings(analysis: AnalyseUploadResponse): IngestFinding[] {
  const blocking = new Set(blockingQuestions(analysis).map((finding) => finding.stage));
  return [
    ...analysis.analysis.findings,
    ...analysis.analysis.columns.map((column) => column.finding),
  ].filter((finding) => finding.needs_review && !blocking.has(finding.stage));
}

/** The decisions that were settled outright, for the "what it worked out" list. */
export function settledFindings(analysis: AnalyseUploadResponse): IngestFinding[] {
  return analysis.analysis.findings.filter((finding) => !finding.needs_review);
}

/**
 * Whether the edited spec can be imported.
 *
 * A date column with no format is the case this exists for: the import would
 * raise, and finding that out after the upload has already been sent is a
 * worse experience than a disabled button with a reason next to it.
 */
export function specProblems(spec: IngestSpec): string[] {
  const problems: string[] = [];
  const names = new Map<string, number>();

  for (const column of spec.columns) {
    if (!column.include) continue;
    const finalName = (column.rename || column.name).trim();
    if (!finalName) {
      problems.push(`${column.name} has no name.`);
      continue;
    }
    names.set(finalName, (names.get(finalName) ?? 0) + 1);
    if ((column.type === "date" || column.type.startsWith("timestamp")) && !column.date_format) {
      problems.push(`${finalName} is a date but no format has been chosen.`);
    }
  }

  for (const [name, count] of names) {
    if (count > 1) problems.push(`${count} columns would all be called "${name}".`);
  }

  if (spec.columns.every((column) => !column.include)) {
    problems.push("Every column is excluded, so there would be nothing to import.");
  }

  return problems;
}

/** Answer one blocking question by editing the spec it belongs to. */
export function answerQuestion(
  spec: IngestSpec,
  finding: IngestFinding,
  chosen: unknown,
): IngestSpec {
  const column = columnOf(finding);
  if (!column) return spec;

  return {
    ...spec,
    columns: spec.columns.map((existing) => {
      if (existing.name !== column) return existing;
      if (finding.stage === "date_format") {
        const format = String(chosen);
        return {
          ...existing,
          date_format: format,
          type: format.includes("%H") ? "timestamp(naive)" : "date",
        };
      }
      if (finding.stage === "number_format") {
        const decimal = String(chosen);
        return {
          ...existing,
          decimal,
          thousands: decimal === "," ? "." : ",",
          type: "float64",
        };
      }
      return existing;
    }),
  };
}

/**
 * Which column a finding is about.
 *
 * The reason carries it as `Column x: ...`, because the finding is produced by
 * a detector that works on one column's values and does not otherwise know
 * where it sits.
 */
export function columnOf(finding: IngestFinding): string | null {
  const match = /^Column (.+?): /.exec(finding.reason);
  return match ? match[1] : null;
}

/** Update one column in a spec, immutably. */
export function editColumn(
  spec: IngestSpec,
  name: string,
  change: Partial<IngestColumnSpec>,
): IngestSpec {
  return {
    ...spec,
    columns: spec.columns.map((column) =>
      column.name === name ? { ...column, ...change } : column,
    ),
  };
}

/** The types a person may choose for a column, in the order they are offered. */
export const COLUMN_TYPES = [
  "string",
  "int64",
  "float64",
  "boolean",
  "date",
  "timestamp(naive)",
  "json",
] as const;

/** A confidence as a percentage a person reads, not a float. */
export function confidenceLabel(finding: IngestFinding): string {
  if (finding.certainty === "certain") return "certain";
  return `${Math.round(finding.confidence * 100)}% sure`;
}
