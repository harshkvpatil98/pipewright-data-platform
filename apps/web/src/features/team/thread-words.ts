import type { CellAnchor } from "@platform/shared-types";

/**
 * Naming the cell a thread is about (C2). A row is named by its identifier
 * column's value when the dataset has one, which survives new versions;
 * otherwise by its number in one version, which says so.
 */
export function anchorWords(anchor: CellAnchor): string {
  if (anchor.row_key_column && anchor.row_key_value !== null) {
    return `On ${anchor.column}, the row with ${anchor.row_key_column} ${anchor.row_key_value}`;
  }
  if (anchor.row_number !== null) {
    return `On ${anchor.column}, row ${anchor.row_number} of version ${anchor.version ?? "?"}`;
  }
  return `On ${anchor.column}`;
}

const text = (value: unknown) => (value === null || value === undefined ? "" : String(value));

/** The anchor for a cell of the rows a page shows. */
export function anchorFor(options: {
  column: string;
  row: Record<string, unknown>;
  /** Its place among the rows shown, from 0. */
  index: number;
  identifier: string | null;
  version: number | null;
}): CellAnchor {
  const { column, row, index, identifier, version } = options;
  if (identifier && row[identifier] !== null && row[identifier] !== undefined) {
    return { column, row_key_column: identifier, row_key_value: text(row[identifier]), row_number: null, version: null };
  }
  return { column, row_key_column: null, row_key_value: null, row_number: index + 1, version };
}

/** Whether a thread is about this cell of the rows shown. */
export function anchorMatches(
  anchor: CellAnchor,
  cell: { column: string; row: Record<string, unknown>; index: number; version: number | null },
): boolean {
  if (anchor.column !== cell.column) return false;
  if (anchor.row_key_column) return text(cell.row[anchor.row_key_column]) === anchor.row_key_value;
  return anchor.row_number === cell.index + 1 && anchor.version === cell.version;
}
