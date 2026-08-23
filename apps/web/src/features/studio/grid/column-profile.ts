/**
 * What a column actually contains, computed from the rows on screen.
 *
 * The point of putting this next to the header rather than on a separate page
 * is that data problems are found by noticing them, not by going looking. A
 * column that is 40% null should say so where somebody is already looking.
 *
 * **Everything here is scoped to the loaded rows and says so.** Profiling the
 * whole table means a round trip; profiling what is on screen is instant and
 * usually enough to spot the problem. Reporting a sample as if it were the
 * whole is the dishonest option, so `rowsProfiled` travels with the result.
 */

export type ValueClass = "value" | "empty" | "null";

export type ColumnProfile = {
  column: string;
  rowsProfiled: number;
  /** Whether `rowsProfiled` is every row, or only those loaded. */
  complete: boolean;
  nulls: number;
  empties: number;
  values: number;
  distinct: number;
  /** Present only when every non-null value parses as a number. */
  numeric: { min: number; max: number; mean: number; median: number } | null;
  /** Longest and shortest rendered length, for sizing and for spotting outliers. */
  shortest: number;
  longest: number;
  /** Most frequent values, descending. Capped: a legend of 900 is not a legend. */
  top: { value: string; count: number; share: number }[];
};

export function classify(value: unknown): ValueClass {
  if (value === null || value === undefined) return "null";
  if (typeof value === "string" && value.trim() === "") return "empty";
  return "value";
}

const TOP_VALUES = 8;

export function profileColumn(
  column: string,
  values: readonly unknown[],
  options: { complete?: boolean } = {}
): ColumnProfile {
  let nulls = 0;
  let empties = 0;
  const counts = new Map<string, number>();
  const numbers: number[] = [];
  let allNumeric = true;
  let shortest = Number.POSITIVE_INFINITY;
  let longest = 0;

  for (const value of values) {
    const kind = classify(value);
    if (kind === "null") {
      nulls += 1;
      continue;
    }
    if (kind === "empty") empties += 1;

    const text = typeof value === "string" ? value : String(value);
    counts.set(text, (counts.get(text) ?? 0) + 1);
    shortest = Math.min(shortest, text.length);
    longest = Math.max(longest, text.length);

    if (allNumeric) {
      const asNumber = typeof value === "number" ? value : Number(text);
      if (Number.isFinite(asNumber) && text.trim() !== "") numbers.push(asNumber);
      else allNumeric = false;
    }
  }

  const present = values.length - nulls;
  const top = [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, TOP_VALUES)
    .map(([value, count]) => ({
      value,
      count,
      share: present === 0 ? 0 : count / present,
    }));

  return {
    column,
    rowsProfiled: values.length,
    complete: options.complete ?? false,
    nulls,
    empties,
    values: present - empties,
    distinct: counts.size,
    numeric: allNumeric && numbers.length > 0 ? summarise(numbers) : null,
    shortest: Number.isFinite(shortest) ? shortest : 0,
    longest,
    top,
  };
}

function summarise(numbers: number[]): { min: number; max: number; mean: number; median: number } {
  const sorted = [...numbers].sort((a, b) => a - b);
  const total = numbers.reduce((sum, value) => sum + value, 0);
  const middle = Math.floor(sorted.length / 2);
  return {
    min: sorted[0],
    max: sorted[sorted.length - 1],
    mean: total / numbers.length,
    // Even counts average the two middle values, matching every stats package.
    median:
      sorted.length % 2 === 0 ? (sorted[middle - 1] + sorted[middle]) / 2 : sorted[middle],
  };
}

export type QualityBand = { kind: ValueClass; share: number };

/**
 * The three proportions the header bar draws.
 *
 * Empty and null are kept apart: they are different facts, and a column that is
 * half empty strings behaves very differently from one that is half nulls.
 */
export function qualityBands(profile: ColumnProfile): QualityBand[] {
  const total = profile.rowsProfiled;
  if (total === 0) return [];
  const bands: QualityBand[] = [
    { kind: "value", share: profile.values / total },
    { kind: "empty", share: profile.empties / total },
    { kind: "null", share: profile.nulls / total },
  ];
  return bands.filter((band) => band.share > 0);
}

/** A short phrase for the header tooltip. */
export function describeProfile(profile: ColumnProfile): string {
  const parts: string[] = [];
  const percent = (n: number) => `${Math.round((n / profile.rowsProfiled) * 100)}%`;
  if (profile.nulls > 0) parts.push(`${percent(profile.nulls)} null`);
  if (profile.empties > 0) parts.push(`${percent(profile.empties)} empty`);
  parts.push(`${profile.distinct.toLocaleString()} distinct`);
  const scope = profile.complete
    ? `${profile.rowsProfiled.toLocaleString()} rows`
    : `first ${profile.rowsProfiled.toLocaleString()} rows`;
  return `${parts.join(" · ")} — ${scope}`;
}
