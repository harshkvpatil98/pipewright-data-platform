import { describe, expect, it } from "vitest";

import {
  addRange,
  clamp,
  extendTo,
  fillTarget,
  fillValues,
  isSelected,
  jump,
  normaliseRange,
  page,
  rangeSize,
  selectAll,
  selectCell,
  selectColumn,
  selectRow,
  selectionSize,
  step,
  tabTarget,
  type Bounds,
  type CellRange,
} from "@/features/studio/grid/grid-selection";

const BOUNDS: Bounds = { rows: 100, columns: 10 };
const cell = (row: number, column: number) => ({ row, column });

describe("ranges", () => {
  it("normalises whichever way a drag went", () => {
    // Dragging up-and-left must produce the same rectangle as down-and-right.
    expect(normaliseRange(cell(5, 5), cell(2, 1))).toEqual({
      top: 2,
      left: 1,
      bottom: 5,
      right: 5,
    });
  });

  it("counts the cells in a rectangle", () => {
    expect(rangeSize({ top: 0, left: 0, bottom: 2, right: 3 })).toBe(12);
  });

  it("does not double-count cells in overlapping rectangles", () => {
    // Otherwise the status bar's "n cells selected" is simply wrong.
    let selection = selectCell(cell(0, 0));
    selection = extendTo(selection, cell(2, 2));
    selection = addRange(selection, cell(1, 1));
    selection = extendTo(selection, cell(3, 3));
    expect(selectionSize(selection)).toBe(9 + 9 - 4);
  });
});

describe("building a selection", () => {
  it("selects a single cell", () => {
    const selection = selectCell(cell(3, 4));
    expect(selection.ranges).toHaveLength(1);
    expect(selection.focus).toEqual(cell(3, 4));
  });

  it("keeps the anchor fixed while extending", () => {
    let selection = selectCell(cell(5, 5));
    selection = extendTo(selection, cell(7, 8));
    selection = extendTo(selection, cell(2, 1));
    expect(selection.anchor).toEqual(cell(5, 5));
    expect(selection.ranges).toHaveLength(1);
    expect(selection.ranges[0]).toEqual({ top: 2, left: 1, bottom: 5, right: 5 });
  });

  it("adds a rectangle without discarding the previous ones", () => {
    let selection = selectCell(cell(0, 0));
    selection = addRange(selection, cell(5, 5));
    expect(selection.ranges).toHaveLength(2);
    expect(isSelected(selection, cell(0, 0))).toBe(true);
    expect(isSelected(selection, cell(5, 5))).toBe(true);
  });

  it("selects a whole row across every column", () => {
    const selection = selectRow(3, BOUNDS);
    expect(selection.ranges[0]).toEqual({ top: 3, bottom: 3, left: 0, right: 9 });
  });

  it("selects a whole column down every row", () => {
    const selection = selectColumn(2, BOUNDS);
    expect(selection.ranges[0]).toEqual({ top: 0, bottom: 99, left: 2, right: 2 });
  });

  it("selects everything", () => {
    expect(selectionSize(selectAll(BOUNDS))).toBe(1000);
  });

  it("survives an empty grid", () => {
    const empty = { rows: 0, columns: 0 };
    expect(() => selectAll(empty)).not.toThrow();
    expect(() => selectRow(0, empty)).not.toThrow();
  });
});

describe("movement", () => {
  it.each([
    ["up", cell(4, 5)],
    ["down", cell(6, 5)],
    ["left", cell(5, 4)],
    ["right", cell(5, 6)],
  ] as const)("steps %s", (direction, expected) => {
    expect(step(cell(5, 5), direction, BOUNDS)).toEqual(expected);
  });

  it("stops at the edges rather than wrapping", () => {
    expect(step(cell(0, 0), "up", BOUNDS)).toEqual(cell(0, 0));
    expect(step(cell(0, 9), "right", BOUNDS)).toEqual(cell(0, 9));
  });

  it("clamps an out-of-range address", () => {
    expect(clamp(cell(999, 999), BOUNDS)).toEqual(cell(99, 9));
    expect(clamp(cell(-5, -5), BOUNDS)).toEqual(cell(0, 0));
  });

  it("pages by a viewport of rows", () => {
    expect(page(cell(50, 2), "down", 20, BOUNDS)).toEqual(cell(70, 2));
    expect(page(cell(5, 2), "up", 20, BOUNDS)).toEqual(cell(0, 2));
  });
});

describe("ctrl+arrow jumps", () => {
  // Column 0 filled in rows 0-4 and 10-12; everything else empty.
  const filled = new Set([0, 1, 2, 3, 4, 10, 11, 12]);
  const hasValue = (address: { row: number; column: number }) =>
    address.column === 0 && filled.has(address.row);
  const bounds: Bounds = { rows: 20, columns: 3 };

  it("runs to the end of a contiguous block", () => {
    expect(jump(cell(0, 0), "down", bounds, hasValue)).toEqual(cell(4, 0));
  });

  it("skips a gap and lands on the next filled cell", () => {
    // Standing on the last filled cell of a block, the next is empty.
    expect(jump(cell(4, 0), "down", bounds, hasValue)).toEqual(cell(10, 0));
  });

  it("from an empty cell, lands on the next filled cell", () => {
    expect(jump(cell(7, 0), "down", bounds, hasValue)).toEqual(cell(10, 0));
  });

  it("runs to the grid edge when no more data lies ahead", () => {
    expect(jump(cell(12, 0), "down", bounds, hasValue)).toEqual(cell(19, 0));
  });

  it("runs backwards the same way", () => {
    expect(jump(cell(12, 0), "up", bounds, hasValue)).toEqual(cell(10, 0));
    expect(jump(cell(10, 0), "up", bounds, hasValue)).toEqual(cell(4, 0));
  });

  it("does not move at the edge", () => {
    expect(jump(cell(0, 0), "up", bounds, hasValue)).toEqual(cell(0, 0));
  });

  it("works across columns too", () => {
    const rowFilled = (address: { row: number; column: number }) =>
      address.row === 0 && address.column <= 1;
    expect(jump(cell(0, 0), "right", bounds, rowFilled)).toEqual(cell(0, 1));
  });
});

describe("tab", () => {
  it("moves across, then wraps to the next row", () => {
    const selection = selectCell(cell(0, 9));
    expect(tabTarget(selection, false, BOUNDS)).toEqual(cell(1, 0));
  });

  it("moves backwards, wrapping to the previous row", () => {
    const selection = selectCell(cell(1, 0));
    expect(tabTarget(selection, true, BOUNDS)).toEqual(cell(0, 9));
  });

  it("stays put at the very end", () => {
    const selection = selectCell(cell(99, 9));
    expect(tabTarget(selection, false, BOUNDS)).toEqual(cell(99, 9));
  });

  it("stays inside a multi-cell selection", () => {
    // Otherwise Tab walks off the right edge and the block being filled is lost.
    let selection = selectCell(cell(2, 2));
    selection = extendTo(selection, cell(3, 4));
    expect(tabTarget({ ...selection, focus: cell(2, 4) }, false, BOUNDS)).toEqual(cell(3, 2));
  });

  it("wraps around the end of a block back to its start", () => {
    let selection = selectCell(cell(2, 2));
    selection = extendTo(selection, cell(3, 4));
    expect(tabTarget({ ...selection, focus: cell(3, 4) }, false, BOUNDS)).toEqual(cell(2, 2));
  });
});

describe("fill handle", () => {
  const source: CellRange = { top: 2, left: 1, bottom: 2, right: 1 };

  it("fills downward", () => {
    expect(fillTarget(source, cell(6, 1))).toEqual({ top: 2, left: 1, bottom: 6, right: 1 });
  });

  it("fills upward", () => {
    expect(fillTarget(source, cell(0, 1))).toEqual({ top: 0, left: 1, bottom: 2, right: 1 });
  });

  it("fills sideways", () => {
    expect(fillTarget(source, cell(2, 5))).toEqual({ top: 2, left: 1, bottom: 2, right: 5 });
  });

  it("picks the dominant axis on a diagonal drag", () => {
    // Filling both axes at once has no defined meaning in a spreadsheet.
    const result = fillTarget(source, cell(8, 3));
    expect(result.bottom).toBe(8);
    expect(result.right).toBe(1);
  });

  it("returns the source when the pointer has not left it", () => {
    expect(fillTarget(source, cell(2, 1))).toEqual(source);
  });
});

describe("fill values", () => {
  it("continues a numeric run", () => {
    expect(fillValues([1, 2], 3)).toEqual([3, 4, 5]);
  });

  it("continues a run with a stride", () => {
    expect(fillValues([10, 20], 2)).toEqual([30, 40]);
  });

  it("continues a descending run", () => {
    expect(fillValues([5, 4], 2)).toEqual([3, 2]);
  });

  it("repeats a single value rather than inventing a sequence", () => {
    // One number carries no stride; guessing 1,2,3 from a lone 1 is wrong.
    expect(fillValues([7], 3)).toEqual([7, 7, 7]);
  });

  it("repeats text", () => {
    expect(fillValues(["north", "south"], 4)).toEqual(["north", "south", "north", "south"]);
  });

  it("repeats numbers that are not an arithmetic run", () => {
    expect(fillValues([1, 5, 2], 3)).toEqual([1, 5, 2]);
  });

  it("repeats when the stride is zero", () => {
    expect(fillValues([3, 3], 2)).toEqual([3, 3]);
  });

  it("does not treat blanks as numbers", () => {
    // Number("") is 0, which would turn two blanks into a run of zeroes.
    expect(fillValues(["", ""], 2)).toEqual(["", ""]);
  });

  it("returns nothing from an empty source", () => {
    expect(fillValues([], 5)).toEqual([]);
  });
});
