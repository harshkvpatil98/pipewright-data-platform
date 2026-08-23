/**
 * Drawing a chart without a chart library.
 *
 * A charting package is several hundred kilobytes to draw a bar chart, and it
 * brings its own opinions about theming that then have to be fought. These are
 * the four bits of arithmetic a chart actually needs, as pure functions -- so
 * they are unit tested, and so a chart renders identically on the server.
 */

export const CHART_WIDTH = 640;
export const CHART_HEIGHT = 260;
export const PADDING = { top: 16, right: 16, bottom: 34, left: 52 };

export type Scale = {
  min: number;
  max: number;
  ticks: number[];
};

/**
 * A y-axis that ends on a round number.
 *
 * An axis running to 8,347 tells you nothing; one running to 9,000 is read at a
 * glance. Zero is included by default because a bar chart whose baseline is not
 * zero exaggerates every difference on it.
 */
export function niceScale(values: number[], { includeZero = true } = {}): Scale {
  const finite = values.filter((value) => Number.isFinite(value));
  if (finite.length === 0) return { min: 0, max: 1, ticks: [0, 1] };

  let min = Math.min(...finite);
  let max = Math.max(...finite);
  if (includeZero) {
    min = Math.min(min, 0);
    max = Math.max(max, 0);
  }
  if (min === max) {
    // A flat series still needs an axis with height, or it draws on the floor.
    max = min === 0 ? 1 : min + Math.abs(min) * 0.5;
  }

  const step = niceStep((max - min) / 4);
  const niceMin = Math.floor(min / step) * step;
  const niceMax = Math.ceil(max / step) * step;

  const ticks: number[] = [];
  for (let tick = niceMin; tick <= niceMax + step / 2; tick += step) {
    // Floating point makes 0.30000000000000004; round to the step's precision.
    ticks.push(Number(tick.toPrecision(12)));
  }
  return { min: niceMin, max: niceMax, ticks };
}

function niceStep(rough: number): number {
  if (rough <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const normalised = rough / magnitude;
  const step = normalised <= 1 ? 1 : normalised <= 2 ? 2 : normalised <= 5 ? 5 : 10;
  return step * magnitude;
}

/** Where a value sits vertically, in SVG coordinates (y grows downward). */
export function yPosition(value: number, scale: Scale): number {
  const usable = CHART_HEIGHT - PADDING.top - PADDING.bottom;
  const span = scale.max - scale.min || 1;
  const ratio = (value - scale.min) / span;
  return PADDING.top + usable * (1 - ratio);
}

/** Evenly spaced band centres across the plot area. */
export function bandPositions(count: number): { centre: number; width: number }[] {
  const usable = CHART_WIDTH - PADDING.left - PADDING.right;
  if (count <= 0) return [];
  const width = usable / count;
  return Array.from({ length: count }, (_unused, index) => ({
    centre: PADDING.left + width * (index + 0.5),
    width,
  }));
}

/** A polyline through a series, for line and area charts. */
export function linePath(values: (number | null)[], scale: Scale): string {
  const bands = bandPositions(values.length);
  const points = values
    .map((value, index) =>
      value === null || !Number.isFinite(value)
        ? null
        : `${round(bands[index].centre)} ${round(yPosition(value, scale))}`,
    )
    .filter((point): point is string => point !== null);
  if (points.length === 0) return "";
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${point}`).join(" ");
}

/** Slice angles for a pie, as cumulative fractions of the whole. */
export function pieSlices(values: number[]): { start: number; end: number; fraction: number }[] {
  const positive = values.map((value) => (Number.isFinite(value) && value > 0 ? value : 0));
  const total = positive.reduce((sum, value) => sum + value, 0);
  if (total <= 0) return [];

  let cursor = 0;
  return positive.map((value) => {
    const fraction = value / total;
    const slice = { start: cursor, end: cursor + fraction, fraction };
    cursor += fraction;
    return slice;
  });
}

/** The SVG path for one pie slice. */
export function slicePath(
  start: number,
  end: number,
  cx: number,
  cy: number,
  radius: number,
): string {
  // A slice covering the whole circle cannot be drawn as an arc: start and end
  // land on the same point and the path collapses to nothing.
  if (end - start >= 0.999) {
    return `M ${cx - radius} ${cy} a ${radius} ${radius} 0 1 0 ${radius * 2} 0 a ${radius} ${radius} 0 1 0 ${-radius * 2} 0`;
  }
  const from = angle(start, cx, cy, radius);
  const to = angle(end, cx, cy, radius);
  const large = end - start > 0.5 ? 1 : 0;
  return `M ${cx} ${cy} L ${round(from.x)} ${round(from.y)} A ${radius} ${radius} 0 ${large} 1 ${round(to.x)} ${round(to.y)} Z`;
}

function angle(fraction: number, cx: number, cy: number, radius: number) {
  // Start at twelve o'clock, which is where people expect a pie to begin.
  const radians = fraction * Math.PI * 2 - Math.PI / 2;
  return { x: cx + Math.cos(radians) * radius, y: cy + Math.sin(radians) * radius };
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

/** A number as a person would write it on an axis. */
export function formatTick(value: number): string {
  const absolute = Math.abs(value);
  if (absolute >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (absolute >= 1_000) return `${(value / 1_000).toFixed(absolute >= 10_000 ? 0 : 1)}k`;
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(2);
}
