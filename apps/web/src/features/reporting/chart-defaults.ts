import type { AggregationName } from "@platform/shared-types";

const NUMERIC_TYPES = ["int", "float", "number", "integer", "double", "decimal"];

/** Columns named like keys: summing an id is never the question. */
function looksLikeIdentifier(column: string): boolean {
  return /(^|_)(id|uuid|key)$/i.test(column) || /Id$/.test(column);
}

/**
 * The first chart a user sees must draw. Pick a grouping that is not a number,
 * and a measure that can be summed and is not an identifier; when there is no
 * such column, count rows, which works on any column.
 */
export function chooseChartDefaults(
  columns: string[],
  columnTypes: Record<string, string>,
): { dimension: string; measure: string; aggregation: AggregationName } {
  const isNumeric = (column: string) =>
    NUMERIC_TYPES.includes((columnTypes[column] ?? "").toLowerCase());
  // A date has a value per day, so grouping by it draws dozens of thin bars;
  // a text column such as a region is the better first question.
  const isDate = (column: string) => /date|time/.test((columnTypes[column] ?? "").toLowerCase());
  const numeric = columns.filter(isNumeric);
  const measurable = numeric.filter((column) => !looksLikeIdentifier(column));
  const categorical = columns.filter(
    (column) => !isNumeric(column) && !looksLikeIdentifier(column),
  );
  const dimension =
    categorical.find((column) => !isDate(column)) ??
    categorical[0] ??
    columns.find((column) => !isNumeric(column)) ??
    columns[0];
  if (measurable.length > 0) {
    // The number people usually mean first: an amount, a total, revenue.
    const preferred = measurable.find((column) =>
      /amount|total|revenue|sales|value/i.test(column),
    );
    return { dimension, measure: preferred ?? measurable[0], aggregation: "sum" };
  }
  return { dimension, measure: columns[0], aggregation: "count" };
}

/** What each aggregation is called on screen. */
export const AGGREGATION_LABELS: Record<AggregationName, string> = {
  sum: "Total",
  avg: "Average",
  mean: "Average",
  median: "Median",
  min: "Lowest",
  max: "Highest",
  count: "Count rows",
  count_distinct: "Count different",
};

function words(column: string): string {
  return column.replace(/[_-]+/g, " ").trim();
}

/** A chart's name in words: "Amount by region", "Rows by status", "Average price". */
export function chartTitle(
  aggregation: AggregationName,
  measure: string,
  dimension: string | null,
): string {
  let measured: string;
  if (aggregation === "count") measured = "Rows";
  else if (aggregation === "count_distinct") measured = `Different ${words(measure)}`;
  else if (aggregation === "sum") {
    const named = words(measure);
    measured = named.charAt(0).toUpperCase() + named.slice(1);
  } else measured = `${AGGREGATION_LABELS[aggregation]} ${words(measure)}`;
  return dimension ? `${measured} by ${words(dimension)}` : measured;
}
