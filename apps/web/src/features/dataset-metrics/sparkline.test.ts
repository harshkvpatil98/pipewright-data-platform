import { describe, expect, it } from "vitest";

import {
  CHART_HEIGHT,
  CHART_WIDTH,
  buildSparkline,
  formatMetric,
} from "@/features/dataset-metrics/sparkline";

describe("buildSparkline", () => {
  it("spreads points evenly across the width", () => {
    const shape = buildSparkline([0, 5, 10]);
    expect(shape.line).toBe(`M 0 ${CHART_HEIGHT} L 50 14 L ${CHART_WIDTH} 0`);
  });

  it("puts the newest point at the right edge", () => {
    expect(buildSparkline([1, 2, 3]).last).toEqual({ x: CHART_WIDTH, y: 0 });
  });

  it("centres a series that never moved instead of dividing by zero", () => {
    const shape = buildSparkline([7, 7, 7]);
    expect(shape.flat).toBe(true);
    expect(shape.line).toContain(`M 0 ${CHART_HEIGHT / 2}`);
    expect(shape.line).not.toContain("NaN");
  });

  it("handles a single point without collapsing the path", () => {
    const shape = buildSparkline([42]);
    expect(shape.last).toEqual({ x: CHART_WIDTH, y: CHART_HEIGHT / 2 });
  });

  it("returns an empty shape for no data", () => {
    expect(buildSparkline([]).line).toBe("");
    expect(buildSparkline([]).last).toBeNull();
  });

  it("ignores non-finite values rather than drawing them", () => {
    const shape = buildSparkline([1, Number.NaN, 3, Number.POSITIVE_INFINITY]);
    expect(shape.line).not.toContain("NaN");
    expect(shape.max).toBe(3);
  });

  it("closes the area path back to the baseline", () => {
    expect(buildSparkline([1, 2]).area.endsWith("Z")).toBe(true);
  });
});

describe("formatMetric", () => {
  it("writes percentages with one decimal", () => {
    expect(formatMetric(98.25, "%")).toBe("98.3%");
  });

  it("groups large counts", () => {
    expect(formatMetric(1200, null)).toBe("1,200");
  });

  it("shows a dash rather than a broken number", () => {
    expect(formatMetric(null, null)).toBe("—");
    expect(formatMetric(Number.NaN, null)).toBe("—");
  });
});
