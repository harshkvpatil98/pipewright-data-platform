/**
 * The staged changes behind the table editor.
 *
 * Editing a live table feels like a spreadsheet and is not one: every keystroke
 * has to become a statement somebody can read before it runs. This module is
 * the translation layer, and it is pure so the rules can be tested without a
 * grid, a network, or a database.
 *
 * Two rules do most of the work here:
 *
 *  - `previous` is always the value that came out of the database, never the
 *    value that was on screen a moment ago. It is what the server compares
 *    against to notice somebody else changed the row, so overwriting it with an
 *    intermediate edit would quietly disable that check.
 *  - Typing a value back to what it was removes the edit. A change set that
 *    says "set region to eu" for a row already reading `eu` is a statement that
 *    will run, touch a row, and mean nothing.
 */

export type CellValue = string | number | boolean | null;

export type RowKey = Record<string, CellValue>;

export type StagedCell = {
  kind: "set_cell";
  /** Stable id built from the key columns; see `rowId`. */
  rowId: string;
  key: RowKey;
  column: string;
  value: CellValue;
  /** As read from the database. Absent when the row was never loaded. */
  previous: CellValue;
  hasPrevious: boolean;
};

export type StagedDelete = {
  kind: "delete_row";
  rowId: string;
  key: RowKey;
};

export type StagedInsert = {
  kind: "insert_row";
  /** Local only -- the row has no database identity until it is committed. */
  rowId: string;
  values: Record<string, CellValue>;
};

export type StagedColumn =
  | { kind: "add_column"; column: string; columnType: string }
  | { kind: "drop_column"; column: string }
  | { kind: "rename_column"; column: string; newName: string };

export type Tray = {
  cells: StagedCell[];
  deletes: StagedDelete[];
  inserts: StagedInsert[];
  columns: StagedColumn[];
};

export const emptyTray = (): Tray => ({ cells: [], deletes: [], inserts: [], columns: [] });

export const isEmpty = (tray: Tray): boolean =>
  tray.cells.length === 0 &&
  tray.deletes.length === 0 &&
  tray.inserts.length === 0 &&
  tray.columns.length === 0;

export const trayCount = (tray: Tray): number =>
  tray.cells.length + tray.deletes.length + tray.inserts.length + tray.columns.length;

/** A stable identity for a row, from the columns the server addresses it by. */
export function rowId(key: RowKey): string {
  const names = Object.keys(key).sort();
  return JSON.stringify(names.map((name) => [name, key[name]]));
}

export function keyOf(row: Record<string, unknown>, keyColumns: string[]): RowKey {
  const key: RowKey = {};
  for (const name of keyColumns) key[name] = row[name] as CellValue;
  return key;
}

/** Local ids for rows that do not exist yet. Prefixed so they cannot collide. */
let insertCounter = 0;
export const nextInsertId = (): string => `new:${++insertCounter}`;
export const isInsertId = (id: string): boolean => id.startsWith("new:");

/**
 * Turn what the editor produced into the value the column should receive.
 *
 * The grid hands back a string because a text box does. Sending "10" to an
 * integer column works on some databases and fails on others, and sending it to
 * a numeric column that then feeds a SUM is worse than either.
 */
export function coerceValue(raw: string, columnType: string | undefined): CellValue {
  const trimmed = raw.trim();
  if (trimmed === "") return null;

  const type = (columnType ?? "").toLowerCase();
  if (/(int|serial|numeric|decimal|real|double|float|money)/.test(type)) {
    const parsed = Number(trimmed.replace(/,/g, ""));
    return Number.isFinite(parsed) ? parsed : trimmed;
  }
  if (/bool/.test(type)) {
    if (/^(true|t|yes|y|1)$/i.test(trimmed)) return true;
    if (/^(false|f|no|n|0)$/i.test(trimmed)) return false;
    return trimmed;
  }
  return raw;
}

/** True when two cell values are the same as far as the database is concerned. */
export function sameValue(left: CellValue, right: CellValue): boolean {
  if (left === null || right === null) return left === right;
  if (typeof left === "number" || typeof right === "number") {
    const a = Number(left);
    const b = Number(right);
    if (Number.isFinite(a) && Number.isFinite(b)) return a === b;
  }
  return String(left) === String(right);
}

export type StageCellInput = {
  key: RowKey;
  column: string;
  value: CellValue;
  /** The value the database returned for this cell, if the row was loaded. */
  original: CellValue;
  hasOriginal: boolean;
};

export function stageCell(tray: Tray, input: StageCellInput): Tray {
  const id = rowId(input.key);
  if (tray.deletes.some((entry) => entry.rowId === id)) {
    // The row is on its way out; editing it would produce an UPDATE the
    // following DELETE immediately erases.
    return tray;
  }

  const existing = tray.cells.find((cell) => cell.rowId === id && cell.column === input.column);
  const previous = existing ? existing.previous : input.original;
  const hasPrevious = existing ? existing.hasPrevious : input.hasOriginal;

  const rest = tray.cells.filter(
    (cell) => !(cell.rowId === id && cell.column === input.column),
  );

  // Back to where it started is not a change.
  if (hasPrevious && sameValue(previous, input.value)) {
    return { ...tray, cells: rest };
  }

  return {
    ...tray,
    cells: [
      ...rest,
      {
        kind: "set_cell",
        rowId: id,
        key: input.key,
        column: input.column,
        value: input.value,
        previous,
        hasPrevious,
      },
    ],
  };
}

export function stageInsertCell(
  tray: Tray,
  insertId: string,
  column: string,
  value: CellValue,
): Tray {
  return {
    ...tray,
    inserts: tray.inserts.map((entry) =>
      entry.rowId === insertId ? { ...entry, values: { ...entry.values, [column]: value } } : entry,
    ),
  };
}

export function addInsert(tray: Tray, values: Record<string, CellValue> = {}): Tray {
  return { ...tray, inserts: [...tray.inserts, { kind: "insert_row", rowId: nextInsertId(), values }] };
}

export function stageDelete(tray: Tray, key: RowKey): Tray {
  const id = rowId(key);
  if (tray.deletes.some((entry) => entry.rowId === id)) return tray;
  return {
    ...tray,
    // Pending edits to a deleted row are dropped, not kept as no-ops.
    cells: tray.cells.filter((cell) => cell.rowId !== id),
    deletes: [...tray.deletes, { kind: "delete_row", rowId: id, key }],
  };
}

export function discardRow(tray: Tray, id: string): Tray {
  if (isInsertId(id)) {
    return { ...tray, inserts: tray.inserts.filter((entry) => entry.rowId !== id) };
  }
  return {
    ...tray,
    cells: tray.cells.filter((cell) => cell.rowId !== id),
    deletes: tray.deletes.filter((entry) => entry.rowId !== id),
  };
}

export function discardCell(tray: Tray, id: string, column: string): Tray {
  return {
    ...tray,
    cells: tray.cells.filter((cell) => !(cell.rowId === id && cell.column === column)),
  };
}

export function stageColumn(tray: Tray, change: StagedColumn): Tray {
  return { ...tray, columns: [...tray.columns, change] };
}

export function discardColumn(tray: Tray, index: number): Tray {
  return { ...tray, columns: tray.columns.filter((_, at) => at !== index) };
}

/**
 * The rows to draw: what the database returned, with pending edits painted on
 * and staged inserts appended.
 *
 * Kept separate from the tray so the grid never mutates what was loaded -- a
 * refresh has to be able to show the true values again.
 */
export function overlayRows(
  rows: Record<string, unknown>[],
  keyColumns: string[],
  tray: Tray,
): { row: Record<string, unknown>; rowId: string; state: "clean" | "edited" | "deleted" | "new" }[] {
  const edits = new Map<string, StagedCell[]>();
  for (const cell of tray.cells) {
    const bucket = edits.get(cell.rowId);
    if (bucket) bucket.push(cell);
    else edits.set(cell.rowId, [cell]);
  }
  const deleted = new Set(tray.deletes.map((entry) => entry.rowId));

  const painted = rows.map((row) => {
    const id = rowId(keyOf(row, keyColumns));
    const pending = edits.get(id);
    const next = pending ? { ...row } : row;
    if (pending) for (const cell of pending) next[cell.column] = cell.value;
    return {
      row: next,
      rowId: id,
      state: deleted.has(id) ? ("deleted" as const) : pending ? ("edited" as const) : ("clean" as const),
    };
  });

  const added = tray.inserts.map((entry) => ({
    row: entry.values as Record<string, unknown>,
    rowId: entry.rowId,
    state: "new" as const,
  }));

  return [...painted, ...added];
}

/** True when this cell carries a staged value rather than a stored one. */
export function isCellEdited(tray: Tray, id: string, column: string): boolean {
  return tray.cells.some((cell) => cell.rowId === id && cell.column === column);
}

export type EditPayload = {
  kind: string;
  key?: RowKey;
  column?: string;
  value?: CellValue;
  previous?: CellValue;
  has_previous?: boolean;
  values?: Record<string, CellValue>;
  column_type?: string;
  new_name?: string;
};

/**
 * The request body, in the order the server will read it.
 *
 * Structure first so a column can be added and filled in one go; the server
 * re-orders for execution, but sending them in a sensible order keeps the
 * review list readable.
 */
export function toPayload(tray: Tray): EditPayload[] {
  const edits: EditPayload[] = [];

  for (const change of tray.columns) {
    if (change.kind === "add_column") {
      edits.push({ kind: "add_column", column: change.column, column_type: change.columnType });
    } else if (change.kind === "drop_column") {
      edits.push({ kind: "drop_column", column: change.column });
    } else {
      edits.push({ kind: "rename_column", column: change.column, new_name: change.newName });
    }
  }

  for (const entry of tray.inserts) {
    edits.push({ kind: "insert_row", values: entry.values });
  }

  for (const cell of tray.cells) {
    edits.push({
      kind: "set_cell",
      key: cell.key,
      column: cell.column,
      value: cell.value,
      ...(cell.hasPrevious ? { previous: cell.previous, has_previous: true } : {}),
    });
  }

  for (const entry of tray.deletes) {
    edits.push({ kind: "delete_row", key: entry.key });
  }

  return edits;
}

/** One line per staged change, for the tray list. */
export function describe(tray: Tray): { id: string; text: string; kind: string }[] {
  const lines: { id: string; text: string; kind: string }[] = [];
  tray.columns.forEach((change, index) => {
    const text =
      change.kind === "add_column"
        ? `Add column ${change.column} (${change.columnType})`
        : change.kind === "drop_column"
          ? `Drop column ${change.column}`
          : `Rename ${change.column} to ${change.newName}`;
    lines.push({ id: `column:${index}`, text, kind: change.kind });
  });
  tray.inserts.forEach((entry) => {
    const shown = Object.entries(entry.values)
      .filter(([, value]) => value !== null && value !== "")
      .map(([name, value]) => `${name}=${String(value)}`)
      .join(", ");
    lines.push({
      id: entry.rowId,
      text: shown ? `New row (${shown})` : "New row (empty)",
      kind: "insert_row",
    });
  });
  tray.cells.forEach((cell) => {
    lines.push({
      id: `${cell.rowId}:${cell.column}`,
      text: `${describeKey(cell.key)} · ${cell.column}: ${render(cell.previous)} → ${render(cell.value)}`,
      kind: "set_cell",
    });
  });
  tray.deletes.forEach((entry) => {
    lines.push({ id: entry.rowId, text: `Delete ${describeKey(entry.key)}`, kind: "delete_row" });
  });
  return lines;
}

function describeKey(key: RowKey): string {
  return Object.entries(key)
    .map(([name, value]) => `${name} ${render(value)}`)
    .join(", ");
}

function render(value: CellValue): string {
  if (value === null) return "empty";
  if (value === "") return "empty";
  return String(value);
}
