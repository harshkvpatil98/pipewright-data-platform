/**
 * What is selected, and where the keyboard moves next.
 *
 * Kept pure so the rules can be tested without a DOM. The rules themselves are
 * Excel's, deliberately: people arrive with these in muscle memory, and a grid
 * that gets Ctrl+Down subtly wrong is more annoying than one that omits it.
 */

import type { CellAddress } from "@/features/studio/grid/grid-geometry";

/** A rectangle of cells. Bounds are inclusive, and always normalised. */
export type CellRange = {
  top: number;
  left: number;
  bottom: number;
  right: number;
};

export type Selection = {
  /** All selected rectangles. The last is the active one. */
  ranges: CellRange[];
  /** Where the current range started -- the fixed corner while extending. */
  anchor: CellAddress;
  /** The moving corner, and the cell that receives typing. */
  focus: CellAddress;
};

export type Bounds = { rows: number; columns: number };

export function normaliseRange(a: CellAddress, b: CellAddress): CellRange {
  return {
    top: Math.min(a.row, b.row),
    bottom: Math.max(a.row, b.row),
    left: Math.min(a.column, b.column),
    right: Math.max(a.column, b.column),
  };
}

export function selectCell(address: CellAddress): Selection {
  return { ranges: [normaliseRange(address, address)], anchor: address, focus: address };
}

/** Extend the active range to `focus`, keeping the anchor fixed. */
export function extendTo(selection: Selection, focus: CellAddress): Selection {
  const ranges = selection.ranges.slice(0, -1);
  ranges.push(normaliseRange(selection.anchor, focus));
  return { ranges, anchor: selection.anchor, focus };
}

/** Start a new rectangle without discarding the existing ones (Ctrl+click). */
export function addRange(selection: Selection, address: CellAddress): Selection {
  return {
    ranges: [...selection.ranges, normaliseRange(address, address)],
    anchor: address,
    focus: address,
  };
}

export function selectRow(row: number, bounds: Bounds): Selection {
  const range = { top: row, bottom: row, left: 0, right: Math.max(0, bounds.columns - 1) };
  return { ranges: [range], anchor: { row, column: 0 }, focus: { row, column: 0 } };
}

export function selectColumn(column: number, bounds: Bounds): Selection {
  const range = { top: 0, bottom: Math.max(0, bounds.rows - 1), left: column, right: column };
  return { ranges: [range], anchor: { row: 0, column }, focus: { row: 0, column } };
}

export function selectAll(bounds: Bounds): Selection {
  const range = {
    top: 0,
    left: 0,
    bottom: Math.max(0, bounds.rows - 1),
    right: Math.max(0, bounds.columns - 1),
  };
  return { ranges: [range], anchor: { row: 0, column: 0 }, focus: { row: 0, column: 0 } };
}

export function isSelected(selection: Selection, address: CellAddress): boolean {
  return selection.ranges.some(
    (range) =>
      address.row >= range.top &&
      address.row <= range.bottom &&
      address.column >= range.left &&
      address.column <= range.right
  );
}

export function rangeSize(range: CellRange): number {
  return (range.bottom - range.top + 1) * (range.right - range.left + 1);
}

export function selectionSize(selection: Selection): number {
  // Overlapping rectangles would be double-counted; de-duplicating by address
  // is what makes the status bar's "n cells" honest.
  const seen = new Set<string>();
  for (const range of selection.ranges) {
    for (let row = range.top; row <= range.bottom; row += 1) {
      for (let column = range.left; column <= range.right; column += 1) {
        seen.add(`${row}:${column}`);
      }
    }
  }
  return seen.size;
}

export function clamp(address: CellAddress, bounds: Bounds): CellAddress {
  return {
    row: Math.min(Math.max(0, address.row), Math.max(0, bounds.rows - 1)),
    column: Math.min(Math.max(0, address.column), Math.max(0, bounds.columns - 1)),
  };
}

export type Direction = "up" | "down" | "left" | "right";

const STEP: Record<Direction, CellAddress> = {
  up: { row: -1, column: 0 },
  down: { row: 1, column: 0 },
  left: { row: 0, column: -1 },
  right: { row: 0, column: 1 },
};

export function step(address: CellAddress, direction: Direction, bounds: Bounds): CellAddress {
  const delta = STEP[direction];
  return clamp({ row: address.row + delta.row, column: address.column + delta.column }, bounds);
}

/**
 * Ctrl+arrow: jump to the edge of the current block of data.
 *
 * Excel's actual rule, which is less obvious than it looks:
 *
 * - standing on a filled cell whose neighbour is filled → run to the LAST
 *   filled cell of that block;
 * - standing on a filled cell whose neighbour is empty → skip the gap and land
 *   on the NEXT filled cell;
 * - standing on an empty cell → land on the next filled cell.
 *
 * In every case, running out of data lands on the grid edge rather than
 * refusing to move.
 */
export function jump(
  address: CellAddress,
  direction: Direction,
  bounds: Bounds,
  hasValue: (address: CellAddress) => boolean
): CellAddress {
  const delta = STEP[direction];
  const limit = direction === "up" || direction === "down" ? bounds.rows : bounds.columns;
  if (limit <= 0) return address;

  const next = { row: address.row + delta.row, column: address.column + delta.column };
  if (!inBounds(next, bounds)) return address;

  const startFilled = hasValue(address);
  const nextFilled = hasValue(next);

  let current = next;
  if (startFilled && nextFilled) {
    // Run to the end of this contiguous block.
    while (true) {
      const ahead = { row: current.row + delta.row, column: current.column + delta.column };
      if (!inBounds(ahead, bounds) || !hasValue(ahead)) break;
      current = ahead;
    }
    return current;
  }

  // Skip any gap and land on the next filled cell; stop at the edge if none.
  while (!hasValue(current)) {
    const ahead = { row: current.row + delta.row, column: current.column + delta.column };
    if (!inBounds(ahead, bounds)) return current;
    current = ahead;
  }
  return current;
}

function inBounds(address: CellAddress, bounds: Bounds): boolean {
  return (
    address.row >= 0 &&
    address.column >= 0 &&
    address.row < bounds.rows &&
    address.column < bounds.columns
  );
}

/** Page up/down move by a viewport of rows, like every other grid. */
export function page(
  address: CellAddress,
  direction: "up" | "down",
  rowsPerPage: number,
  bounds: Bounds
): CellAddress {
  const delta = direction === "down" ? rowsPerPage : -rowsPerPage;
  return clamp({ row: address.row + delta, column: address.column }, bounds);
}

/**
 * Where Tab goes: across, then wrapping to the next row.
 *
 * Within a multi-cell selection Tab stays inside it, which is how people fill a
 * block without leaving it -- otherwise Tab walks off the right edge and the
 * selection is lost.
 */
export function tabTarget(
  selection: Selection,
  reverse: boolean,
  bounds: Bounds
): CellAddress {
  const active = selection.ranges.at(-1);
  const inBlock = active !== undefined && rangeSize(active) > 1;
  const { row, column } = selection.focus;

  if (inBlock && active) {
    const width = active.right - active.left + 1;
    const height = active.bottom - active.top + 1;
    const offset = (row - active.top) * width + (column - active.left);
    const next = (offset + (reverse ? -1 : 1) + width * height) % (width * height);
    return {
      row: active.top + Math.floor(next / width),
      column: active.left + (next % width),
    };
  }

  const nextColumn = column + (reverse ? -1 : 1);
  if (nextColumn < 0) {
    return row > 0 ? { row: row - 1, column: Math.max(0, bounds.columns - 1) } : { row, column: 0 };
  }
  if (nextColumn >= bounds.columns) {
    return row < bounds.rows - 1 ? { row: row + 1, column: 0 } : { row, column };
  }
  return { row, column: nextColumn };
}

/**
 * The range a fill-handle drag covers.
 *
 * Constrained to one axis: dragging diagonally in a spreadsheet fills the
 * dominant direction, and filling both at once has no defined meaning.
 */
export function fillTarget(source: CellRange, pointer: CellAddress): CellRange {
  const belowOrAbove =
    pointer.row > source.bottom
      ? pointer.row - source.bottom
      : pointer.row < source.top
        ? source.top - pointer.row
        : 0;
  const rightOrLeft =
    pointer.column > source.right
      ? pointer.column - source.right
      : pointer.column < source.left
        ? source.left - pointer.column
        : 0;

  if (belowOrAbove === 0 && rightOrLeft === 0) return source;

  if (belowOrAbove >= rightOrLeft) {
    return {
      ...source,
      top: Math.min(source.top, pointer.row),
      bottom: Math.max(source.bottom, pointer.row),
    };
  }
  return {
    ...source,
    left: Math.min(source.left, pointer.column),
    right: Math.max(source.right, pointer.column),
  };
}

/**
 * The values a fill produces.
 *
 * Detects a linear numeric run and continues it; anything else repeats. That
 * matches what people expect: 1,2 fills 3,4,5 while "north","south" repeats.
 */
export function fillValues(source: readonly unknown[], count: number): unknown[] {
  if (source.length === 0) return [];

  const numbers = source.map((value) =>
    typeof value === "number" ? value : Number(String(value ?? "").trim())
  );
  const allNumeric =
    numbers.every((value) => Number.isFinite(value)) &&
    source.every((value) => value !== null && value !== "" && value !== undefined);

  if (allNumeric && source.length >= 2) {
    const stride = numbers[1] - numbers[0];
    const constant = numbers.every(
      (value, index) => index === 0 || Math.abs(value - numbers[index - 1] - stride) < 1e-9
    );
    if (constant && stride !== 0) {
      const last = numbers[numbers.length - 1];
      return Array.from({ length: count }, (_, index) => last + stride * (index + 1));
    }
  }

  return Array.from({ length: count }, (_, index) => source[index % source.length]);
}
