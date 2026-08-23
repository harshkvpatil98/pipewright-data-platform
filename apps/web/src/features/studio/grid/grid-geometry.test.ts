import { describe, expect, it } from "vitest";

import {
  DEFAULT_COLUMN_WIDTH,
  MIN_COLUMN_WIDTH,
  autofitWidth,
  cellAtPoint,
  cellRect,
  columnAt,
  contentSize,
  layoutColumns,
  resizedWidth,
  rowAt,
  scrollToShow,
  visibleColumns,
  visibleRows,
  type LayoutColumn,
  type Viewport,
} from "@/features/studio/grid/grid-geometry";

const ROW_HEIGHT = 32;

function columns(count: number, width = 100, frozen = 0): LayoutColumn[] {
  return Array.from({ length: count }, (_, index) => ({
    name: `c${index}`,
    width,
    frozen: index < frozen,
  }));
}

const viewport = (over: Partial<Viewport> = {}): Viewport => ({
  width: 800,
  height: 320,
  scrollLeft: 0,
  scrollTop: 0,
  ...over,
});

describe("column layout", () => {
  it("accumulates offsets across variable widths", () => {
    const layout = layoutColumns([
      { name: "a", width: 100 },
      { name: "b", width: 50 },
      { name: "c", width: 200 },
    ]);
    expect(layout.offsets).toEqual([0, 100, 150]);
    expect(layout.totalWidth).toBe(350);
  });

  it("clamps a column to a findable minimum", () => {
    // A column dragged to zero width cannot be dragged back.
    const layout = layoutColumns([{ name: "a", width: 2 }]);
    expect(layout.widths[0]).toBe(MIN_COLUMN_WIDTH);
  });

  it("counts leading frozen columns and their combined width", () => {
    const layout = layoutColumns(columns(5, 100, 2));
    expect(layout.frozenCount).toBe(2);
    expect(layout.frozenWidth).toBe(200);
  });

  it("stops counting frozen columns after the first unfrozen one", () => {
    // A frozen column in the middle would need two scroll origins, and no
    // spreadsheet works that way.
    const layout = layoutColumns([
      { name: "a", width: 100, frozen: true },
      { name: "b", width: 100 },
      { name: "c", width: 100, frozen: true },
    ]);
    expect(layout.frozenCount).toBe(1);
  });

  it("handles an empty grid", () => {
    const layout = layoutColumns([]);
    expect(layout.totalWidth).toBe(0);
    expect(layout.offsets).toEqual([]);
  });
});

describe("row windowing", () => {
  it("returns only the rows near the viewport", () => {
    const window = visibleRows(viewport({ scrollTop: 320 }), ROW_HEIGHT, 10_000, 0);
    expect(window.start).toBe(10);
    expect(window.end).toBe(20);
  });

  it("adds overscan so a fast scroll does not reveal blank rows", () => {
    const window = visibleRows(viewport({ scrollTop: 320 }), ROW_HEIGHT, 10_000, 3);
    expect(window.start).toBe(7);
    expect(window.end).toBe(23);
  });

  it("never runs past the end of the data", () => {
    const window = visibleRows(viewport({ scrollTop: 0 }), ROW_HEIGHT, 4);
    expect(window.end).toBe(4);
  });

  it("never runs before the start", () => {
    expect(visibleRows(viewport(), ROW_HEIGHT, 100).start).toBe(0);
  });

  it("returns nothing for an empty dataset", () => {
    expect(visibleRows(viewport(), ROW_HEIGHT, 0)).toEqual({ start: 0, end: 0 });
  });

  it("draws a constant number of rows however far down we scroll", () => {
    // The whole point of virtualisation: row 4,000,000 costs the same as row 4.
    // Compared away from the top edge, where the clamp to zero legitimately
    // trims the leading overscan.
    const near = visibleRows(viewport({ scrollTop: 3_200 }), ROW_HEIGHT, 10_000_000);
    const far = visibleRows(viewport({ scrollTop: 128_000_000 }), ROW_HEIGHT, 10_000_000);
    expect(far.end - far.start).toBe(near.end - near.start);
  });

  it("still draws only a handful of rows at the very top", () => {
    const window = visibleRows(viewport({ scrollTop: 0 }), ROW_HEIGHT, 10_000_000);
    expect(window.end - window.start).toBeLessThan(30);
  });
});

describe("column windowing", () => {
  it("returns only the columns near the viewport", () => {
    const layout = layoutColumns(columns(200));
    const window = visibleColumns(layout, viewport({ scrollLeft: 1000 }), 0);
    expect(window.scrolling[0]).toBe(10);
    expect(window.scrolling.at(-1)).toBe(18);
  });

  it("always returns the frozen columns whatever the scroll", () => {
    const layout = layoutColumns(columns(200, 100, 2));
    const window = visibleColumns(layout, viewport({ scrollLeft: 9000 }), 0);
    expect(window.frozen).toEqual([0, 1]);
  });

  it("never returns a frozen column in the scrolling set", () => {
    // Drawing it twice would double-paint it as the grid scrolls under it.
    const layout = layoutColumns(columns(50, 100, 3));
    const window = visibleColumns(layout, viewport({ scrollLeft: 0 }));
    expect(window.scrolling.every((index) => index >= 3)).toBe(true);
  });

  it("handles a grid narrower than the viewport", () => {
    const layout = layoutColumns(columns(3));
    const window = visibleColumns(layout, viewport(), 0);
    expect(window.scrolling).toEqual([0, 1, 2]);
  });

  it("handles a grid that is entirely frozen", () => {
    const layout = layoutColumns(columns(2, 100, 2));
    const window = visibleColumns(layout, viewport());
    expect(window.frozen).toEqual([0, 1]);
    expect(window.scrolling).toEqual([]);
  });
});

describe("hit testing", () => {
  const layout = layoutColumns([
    { name: "a", width: 100 },
    { name: "b", width: 50 },
    { name: "c", width: 200 },
  ]);

  it.each([
    [0, 0],
    [99, 0],
    [100, 1],
    [149, 1],
    [150, 2],
    [349, 2],
  ])("maps x=%i to column %i", (x, expected) => {
    expect(columnAt(layout, x)).toBe(expected);
  });

  it("returns -1 past the last column", () => {
    expect(columnAt(layout, 350)).toBe(-1);
    expect(columnAt(layout, -1)).toBe(-1);
  });

  it("finds the right column among many, by binary search", () => {
    // Width must clear MIN_COLUMN_WIDTH or the layout clamps it and the
    // arithmetic below no longer describes the columns that exist.
    const width = 64;
    const wide = layoutColumns(columns(500, width));
    for (const index of [0, 1, 250, 498, 499]) {
      expect(columnAt(wide, index * width + 1)).toBe(index);
    }
  });

  it.each([
    [0, 0],
    [31, 0],
    [32, 1],
    [320, 10],
  ])("maps y=%i to row %i", (y, expected) => {
    expect(rowAt(y, ROW_HEIGHT, 1000)).toBe(expected);
  });

  it("returns -1 below the last row", () => {
    expect(rowAt(1000, ROW_HEIGHT, 4)).toBe(-1);
  });
});

describe("cell placement and pointer round-trip", () => {
  const layout = layoutColumns(columns(20, 100, 1));

  it("places a scrolling cell relative to the scroll offset", () => {
    const rect = cellRect(layout, viewport({ scrollLeft: 250, scrollTop: 64 }), ROW_HEIGHT, {
      row: 5,
      column: 4,
    });
    expect(rect.x).toBe(400 - 250);
    expect(rect.y).toBe(5 * ROW_HEIGHT - 64);
  });

  it("pins a frozen cell regardless of scroll", () => {
    const rect = cellRect(layout, viewport({ scrollLeft: 900 }), ROW_HEIGHT, {
      row: 0,
      column: 0,
    });
    expect(rect.x).toBe(0);
  });

  it("round-trips: the cell drawn at a point is the cell found at that point", () => {
    // If these two disagree, clicks land on the wrong cell -- the single most
    // confusing thing a grid can do.
    const view = viewport({ scrollLeft: 320, scrollTop: 96 });
    for (const address of [
      { row: 3, column: 5 },
      { row: 12, column: 9 },
      { row: 0, column: 0 },
    ]) {
      const rect = cellRect(layout, view, ROW_HEIGHT, address);
      const found = cellAtPoint(layout, view, ROW_HEIGHT, 1000, {
        x: rect.x + rect.width / 2,
        y: rect.y + rect.height / 2,
      });
      expect(found).toEqual(address);
    }
  });

  it("reports the frozen column over a point where a scrolled column sits underneath", () => {
    // Frozen columns are drawn on top; testing scroll-space first would report
    // whatever has slid beneath them.
    const view = viewport({ scrollLeft: 900 });
    const found = cellAtPoint(layout, view, ROW_HEIGHT, 1000, { x: 50, y: 10 });
    expect(found).toEqual({ row: 0, column: 0 });
  });

  it("returns null over empty space below the data", () => {
    expect(cellAtPoint(layout, viewport(), ROW_HEIGHT, 3, { x: 10, y: 999 })).toBeNull();
  });
});

describe("scrolling a cell into view", () => {
  const layout = layoutColumns(columns(50, 100, 1));

  it("leaves the scroll alone when the cell is already visible", () => {
    // Otherwise arrowing around inside the viewport makes the grid jitter.
    const view = viewport({ scrollLeft: 200, scrollTop: 64 });
    expect(scrollToShow(layout, view, ROW_HEIGHT, { row: 3, column: 4 })).toEqual({
      scrollLeft: 200,
      scrollTop: 64,
    });
  });

  it("scrolls up to reach a row above the viewport", () => {
    const view = viewport({ scrollTop: 320 });
    expect(scrollToShow(layout, view, ROW_HEIGHT, { row: 2, column: 1 }).scrollTop).toBe(64);
  });

  it("scrolls down just enough to reveal a row below", () => {
    const view = viewport({ scrollTop: 0, height: 320 });
    expect(scrollToShow(layout, view, ROW_HEIGHT, { row: 12, column: 1 }).scrollTop).toBe(
      13 * ROW_HEIGHT - 320
    );
  });

  it("accounts for the frozen gutter when scrolling left", () => {
    // Without this the target lands underneath the frozen columns.
    const view = viewport({ scrollLeft: 1000 });
    const result = scrollToShow(layout, view, ROW_HEIGHT, { row: 0, column: 5 });
    expect(result.scrollLeft).toBe(500 - layout.frozenWidth);
  });

  it("never scrolls to reach a frozen column, which is always visible", () => {
    const view = viewport({ scrollLeft: 700 });
    expect(scrollToShow(layout, view, ROW_HEIGHT, { row: 0, column: 0 }).scrollLeft).toBe(700);
  });

  it("never produces a negative offset", () => {
    const view = viewport({ scrollLeft: 0, scrollTop: 0 });
    const result = scrollToShow(layout, view, ROW_HEIGHT, { row: 0, column: 1 });
    expect(result.scrollLeft).toBeGreaterThanOrEqual(0);
    expect(result.scrollTop).toBeGreaterThanOrEqual(0);
  });
});

describe("sizing", () => {
  it("reports content size for the scrollbar spacer", () => {
    const layout = layoutColumns(columns(10, 120));
    expect(contentSize(layout, ROW_HEIGHT, 1000)).toEqual({ width: 1200, height: 32_000 });
  });

  it("autofits to the widest sampled value, not the widest row in the table", () => {
    // Measuring ten million rows to size a column would freeze the tab.
    const measure = (text: string) => text.length * 8;
    // Values wide enough that the minimum does not dominate the answer.
    expect(autofitWidth("id", ["1", "22", "a".repeat(20)], measure, 0)).toBe(160);
  });

  it("autofit uses the header when it is the widest thing", () => {
    const measure = (text: string) => text.length * 8;
    expect(autofitWidth("a_very_long_column_name", ["1"], measure, 0)).toBe(184);
  });

  it("autofit still respects the minimum", () => {
    expect(autofitWidth("x", [], (t) => t.length, 0)).toBe(MIN_COLUMN_WIDTH);
  });

  it("clamps a resize so a column cannot vanish", () => {
    expect(resizedWidth(DEFAULT_COLUMN_WIDTH, -999)).toBe(MIN_COLUMN_WIDTH);
    expect(resizedWidth(100, 40)).toBe(140);
  });
});
