import { describe, expect, it } from "vitest";

import {
  CHART_HEIGHT,
  PADDING,
  bandPositions,
  formatTick,
  linePath,
  niceScale,
  pieSlices,
  slicePath,
  yPosition,
} from "@/features/reporting/chart-geometry";

describe("niceScale", () => {
  it("ends on a round number rather than the data's maximum", () => {
    const scale = niceScale([0, 8347]);
    expect(scale.max % 1000).toBe(0);
    expect(scale.max).toBeGreaterThanOrEqual(8347);
  });

  it("includes zero so a bar chart does not exaggerate differences", () => {
    expect(niceScale([100, 110, 120]).min).toBe(0);
  });

  it("can leave zero out when the caller wants a zoomed axis", () => {
    expect(niceScale([100, 110], { includeZero: false }).min).toBeGreaterThan(0);
  });

  it("gives a flat series an axis with height instead of drawing on the floor", () => {
    const scale = niceScale([5, 5, 5]);
    expect(scale.max).toBeGreaterThan(scale.min);
  });

  it("handles an all-zero series", () => {
    const scale = niceScale([0, 0]);
    expect(scale.max).toBeGreaterThan(0);
  });

  it("survives an empty series rather than producing NaN", () => {
    expect(niceScale([])).toEqual({ min: 0, max: 1, ticks: [0, 1] });
  });

  it("ignores non-finite values", () => {
    const scale = niceScale([1, Number.NaN, Number.POSITIVE_INFINITY, 10]);
    expect(Number.isFinite(scale.max)).toBe(true);
  });

  it("produces ticks free of floating point noise", () => {
    for (const tick of niceScale([0, 1]).ticks) {
      expect(String(tick)).not.toMatch(/0000000|9999999/);
    }
  });

  it("handles negative values by extending below zero", () => {
    const scale = niceScale([-40, 100]);
    expect(scale.min).toBeLessThan(0);
    expect(scale.max).toBeGreaterThanOrEqual(100);
  });
});

describe("yPosition", () => {
  it("puts the maximum at the top of the plot area", () => {
    const scale = niceScale([0, 100]);
    expect(yPosition(scale.max, scale)).toBeCloseTo(PADDING.top, 1);
  });

  it("puts the minimum at the bottom", () => {
    const scale = niceScale([0, 100]);
    expect(yPosition(scale.min, scale)).toBeCloseTo(CHART_HEIGHT - PADDING.bottom, 1);
  });
});

describe("bandPositions", () => {
  it("spreads bands evenly and centres them", () => {
    const bands = bandPositions(4);
    expect(bands).toHaveLength(4);
    const gaps = bands.slice(1).map((band, index) => band.centre - bands[index].centre);
    expect(new Set(gaps.map((gap) => Math.round(gap)))).toHaveProperty("size", 1);
  });

  it("returns nothing for no data", () => {
    expect(bandPositions(0)).toEqual([]);
  });
});

describe("linePath", () => {
  it("draws through every point", () => {
    const scale = niceScale([0, 10]);
    const path = linePath([1, 5, 10], scale);
    expect(path.startsWith("M")).toBe(true);
    expect(path.match(/L/g)).toHaveLength(2);
  });

  it("skips gaps rather than drawing to zero", () => {
    const scale = niceScale([0, 10]);
    const path = linePath([1, null, 10], scale);
    expect(path.match(/L/g)).toHaveLength(1);
  });

  it("returns nothing when there is nothing to draw", () => {
    expect(linePath([null, null], niceScale([0, 1]))).toBe("");
  });
});

describe("pieSlices", () => {
  it("splits the circle in proportion", () => {
    const slices = pieSlices([25, 25, 50]);
    expect(slices.map((slice) => Math.round(slice.fraction * 100))).toEqual([25, 25, 50]);
    expect(slices[slices.length - 1].end).toBeCloseTo(1, 5);
  });

  it("ignores negatives rather than drawing them backwards", () => {
    const slices = pieSlices([10, -5, 10]);
    expect(slices[1].fraction).toBe(0);
  });

  it("returns nothing when everything is zero", () => {
    expect(pieSlices([0, 0])).toEqual([]);
  });
});

describe("slicePath", () => {
  it("draws a full circle as two arcs rather than collapsing to a point", () => {
    const path = slicePath(0, 1, 50, 50, 40);
    expect(path.match(/a /g)).toHaveLength(2);
  });

  it("sets the large-arc flag past a half turn", () => {
    expect(slicePath(0, 0.75, 50, 50, 40)).toContain(" 1 1 ");
    expect(slicePath(0, 0.25, 50, 50, 40)).toContain(" 0 1 ");
  });

  it("starts at twelve o'clock", () => {
    const path = slicePath(0, 0.25, 100, 100, 50);
    expect(path).toContain("L 100 50");
  });
});

describe("formatTick", () => {
  it("abbreviates large numbers", () => {
    expect(formatTick(1500)).toBe("1.5k");
    expect(formatTick(25000)).toBe("25k");
    expect(formatTick(2_500_000)).toBe("2.5M");
  });

  it("leaves small numbers alone", () => {
    expect(formatTick(42)).toBe("42");
    expect(formatTick(1.5)).toBe("1.50");
  });
});
