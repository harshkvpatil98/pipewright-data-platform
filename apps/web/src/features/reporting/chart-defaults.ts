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
  const numeric = columns.filter(isNumeric);
  const measurable = numeric.filter((column) => !looksLikeIdentifier(column));
  const categorical = columns.filter(
    (column) => !isNumeric(column) && !looksLikeIdentifier(column),
  );
  const dimension = categorical[0] ?? columns.find((column) => !isNumeric(column)) ?? columns[0];
  if (measurable.length > 0) {
    return { dimension, measure: measurable[0], aggregation: "sum" };
  }
  return { dimension, measure: columns[0], aggregation: "count" };
}
