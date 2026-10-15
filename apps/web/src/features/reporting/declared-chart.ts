/**
 * A plugin's chart type, drawn from its marks (X1).
 *
 * A plugin declares a chart as marks over the chart's series (bars, lines,
 * points, areas, stems from zero, value labels) and two scales; no plugin
 * code runs in the browser. This turns chart data and a declaration into
 * shapes, as pure arithmetic, so it is tested and draws the same everywhere.
 */

import type { ChartData, DeclaredChart } from "@platform/shared-types";

import { CHART_HEIGHT, CHART_WIDTH, PADDING, bandPositions, formatTick, niceScale, yPosition, type Scale } from "./chart-geometry";

export type Shape =
  | { kind: "rect"; x: number; y: number; width: number; height: number; series: number }
  | { kind: "path"; d: string; fill: boolean; series: number }
  | { kind: "circle"; cx: number; cy: number; r: number; series: number }
  | { kind: "line"; x1: number; y1: number; x2: number; y2: number; series: number }
  | { kind: "text"; x: number; y: number; text: string; series: number };

export type DeclaredGeometry = {
  shapes: Shape[];
  ticks: { y: number; label: string }[];
  labels: { x: number; text: string }[];
};

const plotLeft = PADDING.left;
const plotRight = CHART_WIDTH - PADDING.right;

/** Where each label sits along the bottom: in bands, or by its value when every label is a number. */
function xPositions(labels: ChartData["labels"], scale: DeclaredChart["x_scale"]): number[] {
  const numbers = labels.map((label) => (typeof label === "number" ? label : Number(label)));
  if (scale === "linear" && labels.length > 1 && numbers.every((value) => Number.isFinite(value))) {
    const low = Math.min(...numbers);
    const high = Math.max(...numbers);
    const span = high - low || 1;
    return numbers.map((value) => plotLeft + ((value - low) / span) * (plotRight - plotLeft));
  }
  return bandPositions(labels.length).map((band) => band.centre);
}

function powersOfTen(exponents: number[]): Scale {
  if (exponents.length === 0) return { min: 0, max: 1, ticks: [0, 1] };
  const low = Math.floor(Math.min(...exponents));
  const high = Math.max(Math.ceil(Math.max(...exponents)), low + 1);
  return { min: low, max: high, ticks: Array.from({ length: high - low + 1 }, (_, index) => low + index) };
}

export function declaredGeometry(data: ChartData, declared: DeclaredChart): DeclaredGeometry {
  const log = declared.y_scale === "log";
  const series = data.series.map((item) =>
    item.values.map((value) => (typeof value === "number" && Number.isFinite(value) && (!log || value > 0) ? value : null)),
  );
  // Stacked: each series sits on the ones before it.
  const bases = series.map((_, index) =>
    data.labels.map((_label, position) =>
      declared.stacked
        ? series.slice(0, index).reduce((total, other) => total + (other[position] ?? 0), 0)
        : 0,
    ),
  );
  const tops = series.map((values, index) => values.map((value, position) => (value === null ? null : value + bases[index][position])));
  const transform = (value: number) => (log ? Math.log10(value) : value);
  const all = tops.flat().filter((value): value is number => value !== null).map(transform);
  // A log axis ticks at whole powers of ten (10, 100, 1,000), not at 10^1.5.
  const scale: Scale = log ? powersOfTen(all) : niceScale(all);
  const y = (value: number) => yPosition(transform(value), scale);
  const zero = log ? CHART_HEIGHT - PADDING.bottom : yPosition(Math.max(scale.min, 0), scale);
  const xs = xPositions(data.labels, declared.x_scale);
  const band = bandPositions(Math.max(data.labels.length, 1))[0]?.width ?? 0;
  const groups = declared.stacked ? 1 : Math.max(series.length, 1);
  const barWidth = (band * 0.7) / groups;

  const chosen = (mark: DeclaredChart["marks"][number]) =>
    mark.series === "all" ? series.map((_, index) => index) : series[mark.series] ? [mark.series] : [];
  // Several series side by side in a band, unless stacked.
  const offset = (index: number) => (declared.stacked || groups === 1 ? 0 : -band * 0.35 + barWidth * (index + 0.5));

  const shapes: Shape[] = [];
  for (const mark of declared.marks) {
    for (const index of chosen(mark)) {
      const values = tops[index];
      if (mark.kind === "line" || mark.kind === "area") {
        const points = values.map((value, position) => (value === null ? null : `${xs[position]} ${y(value)}`));
        const runs: string[] = [];
        let open = false;
        points.forEach((point) => {
          if (point === null) {
            open = false;
            return;
          }
          runs.push(`${open ? "L" : "M"} ${point}`);
          open = true;
        });
        const d = runs.join(" ");
        if (!d) continue;
        if (mark.kind === "area") {
          const present = values.map((value, position) => (value === null ? null : xs[position])).filter((x): x is number => x !== null);
          shapes.push({ kind: "path", d: `${d} L ${present[present.length - 1]} ${zero} L ${present[0]} ${zero} Z`, fill: true, series: index });
        } else {
          shapes.push({ kind: "path", d, fill: false, series: index });
        }
        continue;
      }
      values.forEach((value, position) => {
        if (value === null) return;
        const x = xs[position] + offset(index);
        const base = declared.stacked ? (bases[index][position] ? y(bases[index][position]) : zero) : zero;
        if (mark.kind === "bar") {
          const top = y(value);
          shapes.push({ kind: "rect", x: x - Math.max(barWidth - 2, 1) / 2, y: Math.min(top, base), width: Math.max(barWidth - 2, 1), height: Math.max(Math.abs(base - top), 1), series: index });
        } else if (mark.kind === "point") {
          shapes.push({ kind: "circle", cx: x, cy: y(value), r: Math.max(1, Math.min(mark.size, 12)), series: index });
        } else if (mark.kind === "rule") {
          shapes.push({ kind: "line", x1: x, y1: base, x2: x, y2: y(value), series: index });
        } else if (mark.kind === "text") {
          shapes.push({ kind: "text", x, y: y(value) - 6, text: formatTick(series[index][position] ?? value), series: index });
        }
      });
    }
  }

  return {
    shapes,
    ticks: scale.ticks.map((tick) => ({ y: yPosition(tick, scale), label: formatTick(log ? 10 ** tick : tick) })),
    labels: data.labels.map((label, index) => ({ x: xs[index], text: String(label ?? "") })),
  };
}
