/**
 * Turning a metric series into an SVG path.
 *
 * A chart library would be several hundred kilobytes to draw a line through
 * twelve points. This does the arithmetic instead, in a viewBox of fixed size
 * so the caller can scale it with CSS.
 */

export const CHART_WIDTH = 100;
export const CHART_HEIGHT = 28;

export type SparklineShape = {
  line: string;
  area: string;
  /** Position of the newest point, for the dot that marks it. */
  last: { x: number; y: number } | null;
  min: number;
  max: number;
  flat: boolean;
};

export function buildSparkline(
  values: number[],
  { width = CHART_WIDTH, height = CHART_HEIGHT } = {},
): SparklineShape {
  const usable = values.filter((value) => Number.isFinite(value));
  if (usable.length === 0) {
    return { line: "", area: "", last: null, min: 0, max: 0, flat: true };
  }

  const min = Math.min(...usable);
  const max = Math.max(...usable);
  const flat = max === min;
  // A flat series drawn against its own range would be a division by zero;
  // centring it says "this never moved" more honestly than a full-height line.
  const span = flat ? 1 : max - min;

  const points = usable.map((value, index) => {
    const x = usable.length === 1 ? width : (index / (usable.length - 1)) * width;
    const y = flat ? height / 2 : height - ((value - min) / span) * height;
    return { x: round(x), y: round(y) };
  });

  const line = points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
    .join(" ");
  const area = `${line} L ${round(points[points.length - 1].x)} ${height} L ${round(points[0].x)} ${height} Z`;

  return { line, area, last: points[points.length - 1], min, max, flat };
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

/** A compact number, the way it would be written in a sentence. */
export function formatMetric(value: number | null, unit: string | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  if (unit === "%") return `${value.toFixed(1)}%`;
  if (Math.abs(value) >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(2);
}
