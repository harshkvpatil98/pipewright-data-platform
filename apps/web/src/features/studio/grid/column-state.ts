/**
 * Per-column view state: width, order, freezing and the sort indicator.
 *
 * Kept apart from the component because reordering and freezing interact in a
 * way that is easy to get subtly wrong -- dragging a column left across the
 * frozen boundary either freezes it or it does not, and "it depends where you
 * dropped it" is not an answer anyone can debug from a screenshot.
 */

export type SortDirection = "asc" | "desc";

export type ColumnState = {
  /** Explicit widths, keyed by column name. Absent means the default. */
  widths: Record<string, number>;
  /** Display order as column names. Absent names keep their natural position. */
  order: string[];
  /** How many leading columns are frozen. */
  frozenCount: number;
  /** The column the data is sorted by, if any. Only ever one. */
  sort: { column: string; direction: SortDirection } | null;
};

export const EMPTY_COLUMN_STATE: ColumnState = {
  widths: {},
  order: [],
  frozenCount: 0,
  sort: null,
};

/**
 * Apply a saved order to the live column list.
 *
 * Columns the order does not mention keep their natural position at the end,
 * so a step that adds a column does not have to be reflected in the saved order
 * before the column becomes visible.
 */
export function orderColumns<T extends { name: string }>(
  columns: T[],
  order: readonly string[]
): T[] {
  if (order.length === 0) return columns;
  const byName = new Map(columns.map((column) => [column.name, column]));
  const ordered: T[] = [];
  for (const name of order) {
    const column = byName.get(name);
    if (column) {
      ordered.push(column);
      byName.delete(name);
    }
  }
  return [...ordered, ...byName.values()];
}

/**
 * Move a column, by name, to a new index.
 *
 * Named rather than indexed because the indices shift as soon as the move
 * happens, and an off-by-one there moves the wrong column.
 */
export function moveColumn(
  order: readonly string[],
  names: readonly string[],
  column: string,
  toIndex: number
): string[] {
  const current = order.length > 0 ? [...order] : [...names];
  const from = current.indexOf(column);
  if (from === -1) return current;
  const clamped = Math.max(0, Math.min(current.length - 1, toIndex));
  current.splice(from, 1);
  current.splice(clamped, 0, column);
  return current;
}

/**
 * Cycle a column's sort: ascending, then descending, then off.
 *
 * The third state matters. Without it there is no way back to the data's own
 * order once you have sorted it, short of removing a step by hand.
 */
export function cycleSort(
  current: ColumnState["sort"],
  column: string
): ColumnState["sort"] {
  if (current === null || current.column !== column) {
    return { column, direction: "asc" };
  }
  if (current.direction === "asc") return { column, direction: "desc" };
  return null;
}

/** Freeze up to and including `index`, or unfreeze entirely if already there. */
export function toggleFreeze(frozenCount: number, index: number): number {
  const wanted = index + 1;
  return frozenCount === wanted ? 0 : wanted;
}

/**
 * The transformation step a header sort represents.
 *
 * Sorting is a step rather than a view operation on purpose: the grid holds a
 * page of rows, so sorting what is loaded would order a sample and present it
 * as the order of the table. Making it a step sorts the whole dataset.
 */
export function sortStepConfig(sort: NonNullable<ColumnState["sort"]>): {
  step_type: string;
  config: Record<string, unknown>;
} {
  return {
    step_type: "sort_rows",
    config: {
      columns: [sort.column],
      ascending: [sort.direction === "asc"],
      na_position: "last",
    },
  };
}

/** Read the sort back out of a saved step, so the header shows the right arrow. */
export function sortFromSteps(
  steps: readonly { step_type?: string; type?: string; config?: Record<string, unknown> }[]
): ColumnState["sort"] {
  for (let index = steps.length - 1; index >= 0; index -= 1) {
    const step = steps[index];
    if ((step.step_type ?? step.type) !== "sort_rows") continue;
    const columns = step.config?.columns;
    const ascending = step.config?.ascending;
    if (!Array.isArray(columns) || columns.length === 0) continue;
    const direction: SortDirection =
      Array.isArray(ascending) ? (ascending[0] === false ? "desc" : "asc")
      : ascending === false ? "desc"
      : "asc";
    return { column: String(columns[0]), direction };
  }
  return null;
}
