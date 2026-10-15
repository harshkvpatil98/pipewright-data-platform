/**
 * How a column's values are spread, from its profile (D2): the shape of a
 * number or date column, the commonest values of the rest. The same figures
 * the planner estimates row counts from, so what a person sees here is what
 * the plan was built on.
 */

import { formatDateUtc, formatNumber } from "@/lib/format";

export type ProfileHistogram = { bounds: number[]; rows: number[]; unit?: string };
export type CommonValue = { value: string; rows: number };

export type Bar = { x: number; width: number; height: number };

/**
 * Each bucket as a bar, everything 0 to 1: where it starts, how wide it is,
 * and how tall. The buckets hold about equal rows each, so the height is
 * rows per unit of value: a narrow bucket means the values crowd there.
 */
export function densityBars(histogram: ProfileHistogram | null | undefined): Bar[] {
  if (!histogram || histogram.bounds.length !== histogram.rows.length + 1) return [];
  const low = histogram.bounds[0];
  const span = histogram.bounds[histogram.bounds.length - 1] - low;
  if (!(span > 0)) return [];
  const densities = histogram.rows.map((rows, index) => {
    const width = histogram.bounds[index + 1] - histogram.bounds[index];
    return width > 0 ? rows / width : 0;
  });
  const top = Math.max(...densities) || 1;
  return histogram.rows.map((rows, index) => ({
    x: (histogram.bounds[index] - low) / span,
    width: (histogram.bounds[index + 1] - histogram.bounds[index]) / span,
    // A bucket with rows in it never disappears.
    height: rows > 0 ? Math.max(0.06, densities[index] / top) : 0,
  }));
}

/** The lowest and highest value, written as what they are: "3 – 1,200", or dates. */
export function histogramRange(histogram: ProfileHistogram): string {
  const write = (value: number) => (histogram.unit === "epoch_ms" ? formatDateUtc(value) : formatNumber(value));
  return `${write(histogram.bounds[0])} – ${write(histogram.bounds[histogram.bounds.length - 1])}`;
}

/** The three commonest values with their share of the rows: "eu 50% · us 30% · apac 15%". */
export function commonShares(common: CommonValue[] | null | undefined, rows: number): string | null {
  if (!common || common.length === 0 || rows <= 0) return null;
  return common
    .slice(0, 3)
    .map((entry) => {
      const share = (entry.rows / rows) * 100;
      return `${entry.value || "(blank)"} ${share >= 1 ? Math.round(share) : "<1"}%`;
    })
    .join(" · ");
}
