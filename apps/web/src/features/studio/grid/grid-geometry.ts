/**
 * Grid maths, kept free of React so it can be tested directly.
 *
 * The grid draws cells onto a canvas. Nothing here knows that: it turns scroll
 * offsets and a column list into "which cells are visible and where", and turns
 * a pointer position back into a cell. Both directions have to agree exactly or
 * clicks land on the wrong cell, which is why this is pure and tested rather
 * than tangled into a render loop.
 *
 * **Variable column widths, uniform row height.** Columns are resizable, so
 * their offsets are precomputed cumulatively and hit-tested by binary search --
 * a linear scan is fine at 20 columns and not at 500. Rows are a fixed height
 * (from the density token), so their maths is arithmetic.
 */

export const MIN_COLUMN_WIDTH = 48;
export const DEFAULT_COLUMN_WIDTH = 148;
export const ROW_HEADER_WIDTH = 56;

/** How many rows and columns to draw beyond the viewport. */
export const OVERSCAN_ROWS = 6;
export const OVERSCAN_COLUMNS = 2;

export type LayoutColumn = {
  name: string;
  width: number;
  /** Frozen columns stay put horizontally, like Excel's freeze panes. */
  frozen?: boolean;
};

export type Viewport = {
  width: number;
  height: number;
  scrollLeft: number;
  scrollTop: number;
};

export type CellAddress = { row: number; column: number };

export type ColumnLayout = {
  /** Left edge of each column, in content coordinates. */
  offsets: number[];
  widths: number[];
  totalWidth: number;
  /** Number of leading frozen columns; they always render. */
  frozenCount: number;
  /** Combined width of the frozen columns. */
  frozenWidth: number;
};

/**
 * Precompute column offsets once per layout change.
 *
 * Frozen columns must be leading: a frozen column in the middle would need two
 * scroll origins, and no spreadsheet works that way.
 */
export function layoutColumns(columns: LayoutColumn[]): ColumnLayout {
  const offsets: number[] = [];
  const widths: number[] = [];
  let running = 0;
  let frozenCount = 0;
  let frozenWidth = 0;
  let seenUnfrozen = false;

  for (const column of columns) {
    const width = Math.max(MIN_COLUMN_WIDTH, Math.round(column.width));
    offsets.push(running);
    widths.push(width);
    running += width;

    if (column.frozen && !seenUnfrozen) {
      frozenCount += 1;
      frozenWidth += width;
    } else if (!column.frozen) {
      seenUnfrozen = true;
    }
  }

  return { offsets, widths, totalWidth: running, frozenCount, frozenWidth };
}

export type RowWindow = { start: number; end: number };

/**
 * Which rows to draw. `end` is exclusive.
 *
 * Overscan exists so a fast scroll does not reveal blank rows before the next
 * frame; it costs a few extra rows of drawing and removes the flicker.
 */
export function visibleRows(
  viewport: Viewport,
  rowHeight: number,
  rowCount: number,
  overscan: number = OVERSCAN_ROWS
): RowWindow {
  if (rowCount <= 0 || rowHeight <= 0) return { start: 0, end: 0 };
  const first = Math.floor(viewport.scrollTop / rowHeight);
  const visible = Math.ceil(viewport.height / rowHeight);
  return {
    start: Math.max(0, first - overscan),
    end: Math.min(rowCount, first + visible + overscan),
  };
}

export type ColumnWindow = {
  /** Frozen columns, always drawn. */
  frozen: number[];
  /** Scrolling columns currently in view. */
  scrolling: number[];
};

/**
 * Which columns to draw.
 *
 * Frozen columns are returned separately because they are drawn in a different
 * coordinate space -- pinned to the left edge rather than offset by scrollLeft.
 */
export function visibleColumns(
  layout: ColumnLayout,
  viewport: Viewport,
  overscan: number = OVERSCAN_COLUMNS
): ColumnWindow {
  const frozen = Array.from({ length: layout.frozenCount }, (_, index) => index);
  const count = layout.widths.length;
  if (count === layout.frozenCount) return { frozen, scrolling: [] };

  // The scrolling region begins after the frozen columns, so a column is in
  // view when its right edge is past the scroll origin plus the frozen gutter.
  const viewLeft = viewport.scrollLeft + layout.frozenWidth;
  const viewRight = viewport.scrollLeft + viewport.width;

  let first = columnAt(layout, viewLeft);
  if (first < layout.frozenCount) first = layout.frozenCount;
  let last = columnAt(layout, viewRight);
  if (last < 0) last = count - 1;

  const start = Math.max(layout.frozenCount, first - overscan);
  const end = Math.min(count - 1, last + overscan);

  const scrolling: number[] = [];
  for (let index = start; index <= end; index += 1) scrolling.push(index);
  return { frozen, scrolling };
}

/**
 * The column containing a content-space x, by binary search.
 *
 * Returns -1 past the last column. A linear scan is fine at 20 columns and
 * visibly not fine at 500, and this runs on every pointer move.
 */
export function columnAt(layout: ColumnLayout, x: number): number {
  const { offsets, widths } = layout;
  if (offsets.length === 0 || x < 0) return -1;
  if (x >= layout.totalWidth) return -1;

  let low = 0;
  let high = offsets.length - 1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    const start = offsets[mid];
    const end = start + widths[mid];
    if (x < start) high = mid - 1;
    else if (x >= end) low = mid + 1;
    else return mid;
  }
  return -1;
}

/** The row containing a content-space y, or -1 past the end. */
export function rowAt(y: number, rowHeight: number, rowCount: number): number {
  if (y < 0 || rowHeight <= 0) return -1;
  const index = Math.floor(y / rowHeight);
  return index < rowCount ? index : -1;
}

export type CellRect = { x: number; y: number; width: number; height: number };

/**
 * Where a cell is drawn, in viewport coordinates.
 *
 * A frozen column ignores horizontal scroll -- that is what makes it frozen.
 */
export function cellRect(
  layout: ColumnLayout,
  viewport: Viewport,
  rowHeight: number,
  address: CellAddress
): CellRect {
  const isFrozen = address.column < layout.frozenCount;
  const left = layout.offsets[address.column] ?? 0;
  return {
    x: isFrozen ? left : left - viewport.scrollLeft,
    y: address.row * rowHeight - viewport.scrollTop,
    width: layout.widths[address.column] ?? 0,
    height: rowHeight,
  };
}

/**
 * Which cell is under a pointer, or null over empty space.
 *
 * Frozen columns are tested first and in viewport space, because they sit on
 * top of the scrolling ones: testing scroll-space first would report whatever
 * has scrolled underneath them.
 */
export function cellAtPoint(
  layout: ColumnLayout,
  viewport: Viewport,
  rowHeight: number,
  rowCount: number,
  point: { x: number; y: number }
): CellAddress | null {
  const row = rowAt(point.y + viewport.scrollTop, rowHeight, rowCount);
  if (row < 0) return null;

  if (point.x < layout.frozenWidth && layout.frozenCount > 0) {
    const column = columnAt(layout, point.x);
    if (column >= 0 && column < layout.frozenCount) return { row, column };
    return null;
  }

  const column = columnAt(layout, point.x + viewport.scrollLeft);
  if (column < 0 || column < layout.frozenCount) return null;
  return { row, column };
}

/**
 * The scroll offsets needed to bring a cell fully into view.
 *
 * Returns the offsets unchanged when the cell is already visible, so arrowing
 * around inside the viewport does not jitter the scroll position.
 */
export function scrollToShow(
  layout: ColumnLayout,
  viewport: Viewport,
  rowHeight: number,
  address: CellAddress
): { scrollLeft: number; scrollTop: number } {
  let { scrollLeft, scrollTop } = viewport;

  const top = address.row * rowHeight;
  const bottom = top + rowHeight;
  if (top < scrollTop) scrollTop = top;
  else if (bottom > scrollTop + viewport.height) scrollTop = bottom - viewport.height;

  // A frozen column is always visible, so scrolling to reach one is wrong.
  if (address.column >= layout.frozenCount) {
    const left = layout.offsets[address.column] ?? 0;
    const right = left + (layout.widths[address.column] ?? 0);
    const gutter = layout.frozenWidth;
    if (left < scrollLeft + gutter) scrollLeft = left - gutter;
    else if (right > scrollLeft + viewport.width) scrollLeft = right - viewport.width;
  }

  return {
    scrollLeft: Math.max(0, Math.round(scrollLeft)),
    scrollTop: Math.max(0, Math.round(scrollTop)),
  };
}

/** Total scrollable content size, for the scrollbar spacer element. */
export function contentSize(
  layout: ColumnLayout,
  rowHeight: number,
  rowCount: number
): { width: number; height: number } {
  return { width: layout.totalWidth, height: rowHeight * rowCount };
}

/**
 * Column width that fits the widest of a sample of values.
 *
 * Measured from a sample rather than every row: autofit on ten million rows
 * would freeze the tab, and the widest of the first few hundred is what a
 * person is looking at anyway.
 */
export function autofitWidth(
  header: string,
  values: readonly string[],
  measure: (text: string) => number,
  padding = 24
): number {
  let widest = measure(header);
  for (const value of values) {
    const width = measure(value);
    if (width > widest) widest = width;
  }
  return Math.max(MIN_COLUMN_WIDTH, Math.ceil(widest + padding));
}

/**
 * Where a resize drag puts a column edge.
 *
 * Clamped so a column cannot be dragged to nothing and become unfindable.
 */
export function resizedWidth(startWidth: number, deltaX: number): number {
  return Math.max(MIN_COLUMN_WIDTH, Math.round(startWidth + deltaX));
}
