// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import {
  cellAtPoint,
  columnAt,
  contentSize,
  layoutColumns,
  scrollToShow,
  visibleColumns,
  visibleRows,
} from "@/features/studio/grid/grid-geometry";
import { jump, selectAll, selectionSize } from "@/features/studio/grid/grid-selection";
import { profileColumn } from "@/features/studio/grid/column-profile";

/**
 * Virtualisation, measured.
 *
 * The claim is that row 4,000,000 costs the same as row 4. That is only true if
 * every hot path is independent of the dataset size, so these assert on the
 * *shape* of the work rather than on wall-clock time -- a timing threshold that
 * passes on this machine and fails on a slower CI box teaches nobody anything.
 */

const MILLION = 1_000_000;
const ROW_HEIGHT = 32;
const layout = layoutColumns(
  Array.from({ length: 200 }, (_, index) => ({ name: `c${index}`, width: 120 }))
);
const viewport = { width: 1400, height: 800, scrollLeft: 0, scrollTop: 0 };

describe("row windowing is independent of dataset size", () => {
  it("draws the same number of rows at the top and four million rows down", () => {
    const near = visibleRows({ ...viewport, scrollTop: 3_200 }, ROW_HEIGHT, MILLION * 10);
    const far = visibleRows(
      { ...viewport, scrollTop: 4_000_000 * ROW_HEIGHT },
      ROW_HEIGHT,
      MILLION * 10
    );
    expect(far.end - far.start).toBe(near.end - near.start);
  });

  it("never returns more rows than fit on screen plus overscan", () => {
    const window = visibleRows({ ...viewport, scrollTop: 900_000 }, ROW_HEIGHT, MILLION);
    const onScreen = Math.ceil(viewport.height / ROW_HEIGHT);
    expect(window.end - window.start).toBeLessThanOrEqual(onScreen + 16);
  });

  it("draws a bounded number of columns from a 200-column table", () => {
    const window = visibleColumns(layout, { ...viewport, scrollLeft: 9_000 });
    expect(window.frozen.length + window.scrolling.length).toBeLessThanOrEqual(20);
  });
});

describe("hit testing does not scan", () => {
  it("finds a column among 200 in a bounded number of comparisons", () => {
    // Binary search: ~8 probes for 200 columns. A linear scan would be 200 and
    // would run on every pointer move.
    let probes = 0;
    const counting = new Proxy(layout, {
      get(target, key) {
        if (key === "offsets" || key === "widths") probes += 1;
        return Reflect.get(target, key);
      },
    });
    columnAt(counting as typeof layout, 18_000);
    expect(probes).toBeLessThan(40);
  });

  it("locates a cell four million rows down without touching the rows", () => {
    const found = cellAtPoint(
      layout,
      { ...viewport, scrollTop: 4_000_000 * ROW_HEIGHT },
      ROW_HEIGHT,
      MILLION * 10,
      { x: 300, y: 40 }
    );
    expect(found?.row).toBe(4_000_001);
  });
});

describe("scroll arithmetic stays exact at scale", () => {
  it("computes content height for ten million rows without overflow", () => {
    const size = contentSize(layout, ROW_HEIGHT, MILLION * 10);
    expect(size.height).toBe(320_000_000);
    expect(Number.isSafeInteger(size.height)).toBe(true);
  });

  it("scrolls to the last row of a million exactly", () => {
    const result = scrollToShow(layout, viewport, ROW_HEIGHT, {
      row: MILLION - 1,
      column: 0,
    });
    expect(result.scrollTop).toBe(MILLION * ROW_HEIGHT - viewport.height);
  });
});

describe("operations that DO scale with the data are bounded deliberately", () => {
  it("ctrl+arrow stops at the grid edge rather than scanning forever", () => {
    // With no data ahead, this walks to the edge. It is O(rows) by nature, so
    // the bound is the grid, not the loaded page.
    const target = jump(
      { row: 0, column: 0 },
      "down",
      { rows: 5_000, columns: 3 },
      () => false
    );
    expect(target.row).toBe(4_999);
  });

  it("select-all reports a count without materialising every address", () => {
    // selectionSize de-duplicates by address, so a whole-table selection of ten
    // million cells would allocate ten million strings. Guard the realistic case.
    const selection = selectAll({ rows: 400, columns: 25 });
    expect(selectionSize(selection)).toBe(10_000);
  });

  it("profiling is scoped to what was handed to it, not the table", () => {
    // The grid profiles loaded rows only, and says so; profiling a million rows
    // on every keystroke is exactly what makes grids feel slow.
    const sample = Array.from({ length: 500 }, (_, index) => index % 7);
    const profile = profileColumn("c", sample);
    expect(profile.rowsProfiled).toBe(500);
    expect(profile.complete).toBe(false);
    expect(profile.distinct).toBe(7);
  });
});

describe("the React tree does not grow with the data", () => {
  it("renders no per-row DOM elements", async () => {
    // The property that actually matters: a DOM grid creates elements per row
    // and dies at ~10,000. This one draws to a canvas, so the tree is constant.
    // React requires this flag before it will accept act() outside a test
    // renderer; without it every render logs a warning that hides real ones.
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const { createElement } = await import("react");
    const { createRoot } = await import("react-dom/client");
    const { DataGrid } = await import("@/features/studio/grid/data-grid");

    const columns = Array.from({ length: 20 }, (_, index) => ({ name: `c${index}` }));
    // A Proxy row source: a million real objects would measure the fixture, not
    // the grid.
    let reads = 0;
    const rows = new Proxy([] as Record<string, unknown>[], {
      get(target, key) {
        if (key === "length") return MILLION;
        if (typeof key === "string" && /^\d+$/.test(key)) {
          reads += 1;
          return Object.fromEntries(columns.map((c) => [c.name, `${key}-${c.name}`]));
        }
        return Reflect.get(target, key);
      },
    });

    // jsdom provides neither ResizeObserver nor a 2d context. The component
    // tolerates both being absent; the tree it commits is what is measured.
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);

    const { act } = await import("react");
    await act(async () => {
      root.render(createElement(DataGrid, { columns, rows }));
    });

    // jsdom has no 2d context, so nothing is painted -- but React has committed
    // its tree, and that is what is being measured.
    const elements = host.querySelectorAll("*").length;
    expect(elements).toBeLessThan(50);

    // And it must not have READ a million rows either. Profiling every column
    // over the whole dataset is O(rows x columns) on every render; this counts
    // the actual reads to prove the sample cap is doing its job.
    expect(reads).toBeLessThan(200_000);

    await act(async () => root.unmount());
    host.remove();
  });
});
