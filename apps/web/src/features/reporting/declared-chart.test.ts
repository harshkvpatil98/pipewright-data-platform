import { describe, expect, it } from "vitest";

import type { ChartData, DeclaredChart } from "@platform/shared-types";

import { declaredGeometry } from "./declared-chart";

const data = (values: (number | null)[][], labels: (string | number)[] = ["North", "South", "East"]): ChartData => ({
  chart_type: "acme_lollipop",
  labels,
  series: values.map((items, index) => ({ name: `m${index}`, values: items })),
  row_count: labels.length,
  truncated: false,
  warnings: [],
});

const lollipop: DeclaredChart = {
  marks: [
    { kind: "rule", series: "all", size: 4 },
    { kind: "point", series: "all", size: 5 },
  ],
  x_scale: "band",
  y_scale: "linear",
  stacked: false,
};

describe("a plugin's chart type", () => {
  it("draws a stem and a dot for each value, and skips an empty one", () => {
    const geometry = declaredGeometry(data([[10, null, 30]]), lollipop);
    expect(geometry.shapes.filter((shape) => shape.kind === "line")).toHaveLength(2);
    const dots = geometry.shapes.filter((shape) => shape.kind === "circle");
    expect(dots).toHaveLength(2);
    // The larger value sits higher (a smaller y).
    expect((dots[1] as { cy: number }).cy).toBeLessThan((dots[0] as { cy: number }).cy);
    expect(geometry.labels.map((label) => label.text)).toEqual(["North", "South", "East"]);
  });

  it("stacks bars on the series before them", () => {
    const stacked: DeclaredChart = { ...lollipop, marks: [{ kind: "bar", series: "all", size: 4 }], stacked: true };
    const geometry = declaredGeometry(data([[10, 20, 30], [5, 5, 5]]), stacked);
    const bars = geometry.shapes.filter((shape) => shape.kind === "rect") as { y: number; height: number; series: number; x: number }[];
    expect(bars).toHaveLength(6);
    const first = bars.filter((bar) => bar.x === bars[0].x);
    // The second series' bar starts where the first's ends.
    expect(Math.round(first[1].y + first[1].height)).toBe(Math.round(first[0].y));
  });

  it("draws one series when a mark names it, a line through the values, and labels them", () => {
    const declared: DeclaredChart = {
      ...lollipop,
      marks: [
        { kind: "line", series: 1, size: 2 },
        { kind: "text", series: 0, size: 2 },
      ],
    };
    const geometry = declaredGeometry(data([[1, 2, 3], [4, 5, 6]]), declared);
    expect(geometry.shapes.filter((shape) => shape.kind === "path")).toHaveLength(1);
    expect(geometry.shapes.filter((shape) => shape.kind === "text").map((shape) => (shape as { text: string }).text)).toEqual(["1", "2", "3"]);
  });

  it("places numeric labels by their value on a linear axis, and leaves out what a log axis cannot show", () => {
    const linear: DeclaredChart = { ...lollipop, x_scale: "linear", y_scale: "log" };
    const geometry = declaredGeometry(data([[10, 0, 1000]], [1, 2, 10]), linear);
    const [first, second, third] = geometry.labels.map((label) => label.x);
    expect(third - second).toBeGreaterThan(second - first);
    expect(geometry.shapes.filter((shape) => shape.kind === "circle")).toHaveLength(2);
    expect(geometry.ticks.map((tick) => tick.label)).toEqual(["10", "100", "1.0k"]);
  });
});
