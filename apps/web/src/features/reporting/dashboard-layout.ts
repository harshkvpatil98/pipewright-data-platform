/**
 * Pure helpers for arranging a dashboard: reorder, resize, filter labels,
 * refresh cadence. Kept out of the component so the rules can be tested
 * without rendering anything.
 */

import type { ChartFilter, DashboardRefreshSeconds, DashboardTile, DashboardTileInput } from "@platform/shared-types";

export const TILE_WIDTHS = [3, 4, 6, 8, 12] as const;
export const TILE_MIN_WIDTH = 2;
export const TILE_MAX_WIDTH = 12;
export const TILE_MIN_HEIGHT = 1;
export const TILE_MAX_HEIGHT = 4;

/** A tile as the editor holds it: a stable local key plus the API fields. */
export type DraftTile = DashboardTileInput & { key: string };

export function draftFromTiles(tiles: DashboardTile[]): DraftTile[] {
  return [...tiles]
    .sort((a, b) => a.position - b.position)
    .map((tile) => ({
      key: tile.id,
      kind: tile.kind,
      chart_id: tile.chart_id,
      title: tile.title,
      body: tile.body,
      width: tile.width,
      height: tile.height,
    }));
}

/** What gets sent: positions follow list order, never stale stored values. */
export function toTilePayload(drafts: DraftTile[]): DashboardTileInput[] {
  return drafts.map((draft, index) => ({
    kind: draft.kind,
    chart_id: draft.kind === "chart" ? draft.chart_id : null,
    title: draft.kind === "text" ? draft.title ?? null : null,
    body: draft.kind === "text" ? draft.body ?? null : null,
    position: index,
    width: clampWidth(draft.width),
    height: clampHeight(draft.height),
  }));
}

export function moveTile<T>(items: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= items.length || to >= items.length) {
    return items;
  }
  const next = [...items];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

export function clampWidth(width: number): number {
  if (!Number.isFinite(width)) return 6;
  return Math.min(TILE_MAX_WIDTH, Math.max(TILE_MIN_WIDTH, Math.round(width)));
}

export function clampHeight(height: number): number {
  if (!Number.isFinite(height)) return 1;
  return Math.min(TILE_MAX_HEIGHT, Math.max(TILE_MIN_HEIGHT, Math.round(height)));
}

/** Pixel height for a tile row count -- one row is the chart's natural height. */
export function tileMinHeightPx(height: number): number {
  return 300 * clampHeight(height);
}

const OPERATOR_WORDS: Record<string, string> = {
  equals: "is",
  not_equals: "is not",
  greater_than: ">",
  greater_or_equal: "≥",
  less_than: "<",
  less_or_equal: "≤",
  contains: "contains",
  in: "is one of",
  is_null: "is empty",
  not_null: "is not empty",
};

/** "region is north" -- a filter chip a reader can parse without a legend. */
export function describeFilter(filter: ChartFilter): string {
  const word = OPERATOR_WORDS[filter.operator] ?? filter.operator.replace(/_/g, " ");
  if (filter.operator === "is_null" || filter.operator === "not_null") {
    return `${filter.column} ${word}`;
  }
  const value = Array.isArray(filter.value)
    ? filter.value.map(String).join(", ")
    : filter.value === null || filter.value === undefined
      ? "—"
      : String(filter.value);
  return `${filter.column} ${word} ${value}`;
}

/** Turn the text a person typed into the value a filter carries: numbers stay
 * numbers, `a, b, c` becomes a list for `in`, everything else is text. */
export function parseFilterValue(operator: string, raw: string): unknown {
  const text = raw.trim();
  if (operator === "is_null" || operator === "not_null") return null;
  if (operator === "in") {
    return text
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean)
      .map(coerceScalar);
  }
  return coerceScalar(text);
}

function coerceScalar(text: string): string | number | boolean {
  if (text === "true") return true;
  if (text === "false") return false;
  // A leading zero ("007", "01234") is an identifier that happens to be
  // digits, not a number -- the same rule ingestion applies.
  if (/^-?(0|[1-9]\d*)(\.\d+)?$/.test(text)) {
    return Number(text);
  }
  return text;
}

export const REFRESH_LABELS: Record<DashboardRefreshSeconds, string> = {
  30: "every 30 seconds",
  60: "every minute",
  300: "every 5 minutes",
  900: "every 15 minutes",
  1800: "every 30 minutes",
  3600: "every hour",
};

export function describeRefresh(seconds: DashboardRefreshSeconds | null): string {
  return seconds === null ? "manual refresh only" : REFRESH_LABELS[seconds];
}

/** "3 minutes ago" for the last computed stamp; never negative, never fake precision. */
export function describeAge(computedAt: string, now: Date = new Date()): string {
  const seconds = Math.max(0, Math.round((now.getTime() - new Date(computedAt).getTime()) / 1000));
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds} seconds ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  return `${hours} hour${hours === 1 ? "" : "s"} ago`;
}

/** Percent change for a KPI delta, as text: "+12.5%" / "−3.0%" / null when
 * there is nothing to compare against. */
export function formatDeltaPct(pct: number | null): string | null {
  if (pct === null || !Number.isFinite(pct)) return null;
  const sign = pct > 0 ? "+" : pct < 0 ? "−" : "";
  return `${sign}${Math.abs(pct * 100).toFixed(1)}%`;
}
