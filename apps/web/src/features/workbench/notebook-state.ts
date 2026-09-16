/**
 * The rules a notebook follows, apart from how it is drawn.
 *
 * A notebook is a narrative: cells run in order, each reads what the ones
 * before it produced, and a failure stops the rest. All of that is logic worth
 * testing without a browser.
 */

export type CellKind = "sql" | "python" | "recipe" | "markdown";

export type Cell = {
  id: string;
  kind: CellKind;
  source: string;
  output_name: string | null;
  config: Record<string, unknown>;
};

export type CellResult = {
  position: number;
  kind: string;
  ok: boolean;
  duration_ms: number;
  output_name: string | null;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  stdout: string;
  error: string;
  skipped: boolean;
  bindings: Record<string, string>;
};

let counter = 0;
export const newCellId = (): string => `cell-${++counter}`;

export function emptyCell(kind: CellKind = "sql"): Cell {
  return { id: newCellId(), kind, source: "", output_name: null, config: {} };
}

export function moveCell(cells: Cell[], index: number, delta: number): Cell[] {
  const target = index + delta;
  if (index < 0 || index >= cells.length || target < 0 || target >= cells.length) return cells;
  const next = [...cells];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

export function insertAfter(cells: Cell[], index: number, cell: Cell): Cell[] {
  const next = [...cells];
  next.splice(index + 1, 0, cell);
  return next;
}

export function removeCell(cells: Cell[], id: string): Cell[] {
  return cells.filter((cell) => cell.id !== id);
}

export function updateCell(cells: Cell[], id: string, changes: Partial<Cell>): Cell[] {
  return cells.map((cell) => (cell.id === id ? { ...cell, ...changes } : cell));
}

/**
 * The names a cell can read: everything bound *before* it.
 *
 * Offering a later cell's output would let somebody write a notebook that
 * cannot run — and the error would come from the engine at run time rather
 * than from the editor while they were writing it.
 */
export function namesAvailableTo(cells: Cell[], index: number): string[] {
  const names: string[] = [];
  for (let position = 0; position < index; position += 1) {
    const name = cells[position]?.output_name;
    if (name && !names.includes(name)) names.push(name);
  }
  return names;
}

/** A name that is bound twice makes the second one silently win. */
export function duplicateNames(cells: Cell[]): string[] {
  const seen = new Map<string, number>();
  for (const cell of cells) {
    if (!cell.output_name) continue;
    seen.set(cell.output_name, (seen.get(cell.output_name) ?? 0) + 1);
  }
  return [...seen.entries()].filter(([, count]) => count > 1).map(([name]) => name);
}

/** Problems worth showing before anybody presses run. */
export function validate(cells: Cell[]): { cell: number; message: string }[] {
  const problems: { cell: number; message: string }[] = [];
  const duplicates = duplicateNames(cells);

  cells.forEach((cell, index) => {
    if (cell.output_name && !/^[a-z_][a-z0-9_]*$/i.test(cell.output_name)) {
      problems.push({
        cell: index,
        message: `“${cell.output_name}” cannot be a name. Use letters, numbers and underscores, starting with a letter.`,
      });
    }
    if (cell.output_name && duplicates.includes(cell.output_name)) {
      problems.push({
        cell: index,
        message: `Two cells are both called “${cell.output_name}”; the later one would win.`,
      });
    }
    if (cell.kind === "recipe") {
      const input = typeof cell.config.input === "string" ? cell.config.input : "";
      const available = namesAvailableTo(cells, index);
      if (!input) {
        problems.push({ cell: index, message: "This recipe does not say which result it transforms." });
      } else if (!available.includes(input)) {
        problems.push({
          cell: index,
          message: available.length
            ? `“${input}” is not produced before this cell. Available here: ${available.join(", ")}.`
            : `“${input}” is not produced before this cell, and nothing is yet.`,
        });
      }
    }
    if (cell.kind !== "markdown" && !cell.source.trim() && cell.kind !== "recipe") {
      problems.push({ cell: index, message: "This cell is empty." });
    }
  });

  return problems;
}

/** How a cell's result reads in one line. */
export function describeCell(result: CellResult): string {
  if (result.skipped) return "skipped";
  if (result.error) return "failed";
  const parts: string[] = [];
  if (result.columns.length) {
    parts.push(`${result.row_count.toLocaleString()} row${result.row_count === 1 ? "" : "s"}`);
  }
  if (result.output_name) parts.push(`→ ${result.output_name}`);
  parts.push(result.duration_ms < 1 ? "<1 ms" : `${Math.round(result.duration_ms)} ms`);
  return parts.join(" · ");
}

/** What the API takes. Ids are local and never sent. */
export function toPayload(cells: Cell[]): Record<string, unknown>[] {
  return cells.map((cell) => ({
    kind: cell.kind,
    source: cell.source,
    output_name: cell.output_name || null,
    config: cell.config,
  }));
}
