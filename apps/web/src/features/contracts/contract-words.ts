import type {
  ContractColumn,
  ContractColumnKind,
  ContractConsumer,
  ContractProblem,
  ContractStatus,
  ContractTerms,
} from "@platform/shared-types";
import type { BadgeTone } from "@platform/shared-ui";

import { countOf, formatCount, formatNumber } from "@/lib/format";

/** The kinds a promised column can be, in the order they are offered. */
export const KIND_WORDS: Record<ContractColumnKind, string> = {
  text: "Text",
  whole_number: "Whole number",
  decimal_number: "Decimal number",
  date: "Date",
  date_time: "Date & time",
  true_false: "True / false",
  any: "Any",
};

export const KINDS = Object.keys(KIND_WORDS) as ContractColumnKind[];

/** Only numbers can have a lowest or highest value. */
export const takesRange = (kind: ContractColumnKind) =>
  kind === "whole_number" || kind === "decimal_number" || kind === "any";

export function statusWords(status: ContractStatus): { word: string; tone: BadgeTone } {
  if (status === "broken") return { word: "Broken", tone: "danger" };
  if (status === "kept") return { word: "Kept", tone: "success" };
  return { word: "Not checked yet", tone: "neutral" };
}

/** "Contract kept", for the chip on a dataset. */
export function chipWords(status: ContractStatus): string {
  if (status === "broken") return "Contract broken";
  if (status === "kept") return "Contract kept";
  return "Contract not checked yet";
}

/** One line saying what a column's promise is: "Whole number, always filled, no repeats". */
export function columnPromise(column: ContractColumn): string {
  const parts = [KIND_WORDS[column.kind]];
  if (column.always_filled) parts.push("always filled");
  if (column.no_repeats) parts.push("no repeats");
  if (column.allowed_values?.length) {
    parts.push(`one of ${countOf(column.allowed_values.length, "value")}`);
  }
  if (column.lowest !== null && column.highest !== null) {
    parts.push(`between ${formatNumber(column.lowest)} and ${formatNumber(column.highest)}`);
  } else if (column.lowest !== null) {
    parts.push(`at least ${formatNumber(column.lowest)}`);
  } else if (column.highest !== null) {
    parts.push(`at most ${formatNumber(column.highest)}`);
  }
  return parts.join(", ");
}

/** The promises about the whole dataset, a sentence each. */
export function datasetPromises(terms: ContractTerms): string[] {
  const lines: string[] = [];
  if (terms.rows_at_least !== null && terms.rows_at_most !== null) {
    lines.push(`Between ${formatCount(terms.rows_at_least)} and ${countOf(terms.rows_at_most, "row")}.`);
  } else if (terms.rows_at_least !== null) {
    lines.push(`At least ${countOf(terms.rows_at_least, "row")}.`);
  } else if (terms.rows_at_most !== null) {
    lines.push(`At most ${countOf(terms.rows_at_most, "row")}.`);
  }
  if (terms.largest_drop_percent !== null) {
    lines.push(`No more than ${formatNumber(terms.largest_drop_percent)}% fewer rows than the data before.`);
  }
  if (terms.new_data_every_hours !== null) {
    lines.push(`New data at least every ${hoursWords(terms.new_data_every_hours)}.`);
  }
  lines.push(
    terms.other_columns === "not_allowed"
      ? "Only the promised columns; a new column breaks it."
      : "New columns may appear without breaking it.",
  );
  return lines;
}

export function hoursWords(hours: number): string {
  if (hours >= 24 && hours % 24 === 0) return countOf(hours / 24, "day");
  return Number.isInteger(hours) ? countOf(hours, "hour") : `${formatNumber(hours)} hours`;
}

const SOURCE_WORDS: Record<NonNullable<ContractProblem["source_type"]>, string> = {
  recipe: "The recipe",
  import: "The import",
  stream: "The stream",
  rollback: "Rolling back",
  erasure: "Erasing a person's data",
  check: "Checking by hand",
};

/** What happened, in one sentence: "The recipe Clean orders was stopped." */
export function problemHeadline(problem: ContractProblem): string {
  if (problem.kind === "overdue") return "New data is overdue.";
  const source = problem.source_type ? SOURCE_WORDS[problem.source_type] : "New data";
  const named =
    problem.source_name && ["recipe", "import", "stream"].includes(problem.source_type ?? "")
      ? `${source} ${problem.source_name}`
      : source;
  if (problem.outcome === "stopped") return `${named} made data that breaks it, so the data was not saved.`;
  if (problem.source_type === "check") return "The current data breaks it.";
  return `${named} made data that breaks it. It was saved, because the contract is set to warn.`;
}

const CONSUMER_WORDS: Record<ContractConsumer["kind"], [string, string]> = {
  recipe: ["Recipe", "Recipes"],
  check: ["Check", "Checks"],
  chart: ["Chart", "Charts"],
  dashboard: ["Dashboard", "Dashboards"],
  metric: ["Metric", "Metrics"],
  delivery: ["Scheduled delivery", "Scheduled deliveries"],
  workflow: ["Workflow", "Workflows"],
};

export function consumerKind(kind: ContractConsumer["kind"], count = 1): string {
  return CONSUMER_WORDS[kind][count === 1 ? 0 : 1];
}

/** Where a consumer opens, or null when it has no page of its own. */
export function consumerHref(projectId: string, consumer: ContractConsumer): string | null {
  const base = `/projects/${projectId}`;
  switch (consumer.kind) {
    case "recipe":
      return `${base}/pipelines/${consumer.id}`;
    case "check":
      return `${base}/checks`;
    case "chart":
      return `${base}/charts`;
    case "dashboard":
      return `${base}/dashboards/${consumer.id}`;
    case "metric":
      return `${base}/metrics`;
    case "delivery":
      return `${base}/schedules`;
    case "workflow":
      return `${base}/workflows/${consumer.id}`;
  }
}

/** Promised columns the given columns do not have, for the Studio's notice. */
export function missingPromised(terms: ContractTerms, columns: string[]): string[] {
  const present = new Set(columns);
  return terms.columns.map((column) => column.name).filter((name) => !present.has(name));
}

/** An empty column promise, as the editor adds one. */
export function blankColumn(name = ""): ContractColumn {
  return {
    name,
    kind: "any",
    always_filled: false,
    no_repeats: false,
    allowed_values: null,
    lowest: null,
    highest: null,
  };
}
