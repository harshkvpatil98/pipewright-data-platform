import { describe, expect, it } from "vitest";

import { commonShares, densityBars, histogramRange } from "@/features/datasets/column-values";

describe("column values", () => {
  it("draws equal-count buckets by how crowded each is", () => {
    const bars = densityBars({ bounds: [0, 10, 12, 400], rows: [100, 100, 100] });
    expect(bars.map((bar) => bar.x)).toEqual([0, 0.025, 0.03]);
    expect(bars[1].height).toBe(1); // 100 rows across 2 is the most crowded
    expect(bars[0].height).toBeCloseTo(0.2);
    expect(bars[2].height).toBe(0.06); // thin, but never gone
  });

  it("draws nothing it cannot", () => {
    expect(densityBars(null)).toEqual([]);
    expect(densityBars({ bounds: [5, 5], rows: [10] })).toEqual([]);
    expect(densityBars({ bounds: [1, 2], rows: [1, 2] })).toEqual([]);
  });

  it("writes the range as numbers or dates", () => {
    expect(histogramRange({ bounds: [3, 1200], rows: [9] })).toBe("3 – 1,200");
    expect(histogramRange({ bounds: [Date.UTC(2026, 0, 1), Date.UTC(2026, 9, 15)], rows: [9], unit: "epoch_ms" })).toBe(
      "1 Jan 2026 – 15 Oct 2026",
    );
  });

  it("names the commonest values with their shares", () => {
    const common = [
      { value: "eu", rows: 500 },
      { value: "us", rows: 300 },
      { value: "", rows: 150 },
      { value: "latam", rows: 4 },
    ];
    expect(commonShares(common, 1000)).toBe("eu 50% · us 30% · (blank) 15%");
    expect(commonShares([{ value: "x", rows: 2 }], 1000)).toBe("x <1%");
    expect(commonShares([], 10)).toBeNull();
  });
});
