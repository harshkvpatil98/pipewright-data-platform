/**
 * Every date and number a person reads, written in one place (A8, Y7).
 *
 * The locale comes from the message catalogue (`LOCALE`, en-GB), so the
 * product writes "15 Oct 2026" and "1,200" the same way on every page, and
 * a second language would change them all at once. Nothing else in the app
 * builds an `Intl` formatter or calls `toLocaleString`; `format.test.ts`
 * holds it to that.
 */

import { LOCALE } from "@/lib/i18n";

const integerFormatter = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 });
const numberFormatter = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 6 });
const dateFormatter = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", year: "numeric" });
const shortDateFormatter = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short" });
const dayFormatter = new Intl.DateTimeFormat(LOCALE, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
const timeFormatter = new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit" });
const localDateTimeFormatter = new Intl.DateTimeFormat(LOCALE, { dateStyle: "medium", timeStyle: "short" });
const utcDateTimeFormatter = new Intl.DateTimeFormat(LOCALE, { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" });
const utcTimeFormatter = new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
const utcDateFormatter = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

const collator = new Intl.Collator(LOCALE, { numeric: true, sensitivity: "base" });

type When = string | number | Date;
const asDate = (value: When) => (value instanceof Date ? value : new Date(value));

/** "15 Oct 2026", in the viewer's time zone. */
export function formatDate(value: When) {
  return dateFormatter.format(asDate(value));
}

/** "15 Oct", for a date in a list where the year goes without saying. */
export function formatShortDate(value: When) {
  return shortDateFormatter.format(asDate(value));
}

/** "Thursday, 15 October 2026", for a heading over a day's items. */
export function formatDay(value: When) {
  return dayFormatter.format(asDate(value));
}

/** "09:35", in the viewer's time zone. */
export function formatTime(value: When) {
  return timeFormatter.format(asDate(value));
}

/** "15 Oct 2026, 09:35", in the viewer's time zone. */
export function formatLocalDateTime(value: When) {
  return localDateTimeFormatter.format(asDate(value));
}

/** A technical instant -- a publication time, a frozen evaluation instant --
 * shown to the minute in UTC, which is the zone every such value is recorded
 * in. A date alone cannot tell two versions published the same day apart. */
export function formatDateTime(value: When) {
  return `${utcDateTimeFormatter.format(asDate(value))} UTC`;
}

/** The time of a technical instant, "13:37 UTC", beside others written in UTC. */
export function formatTimeUtc(value: When) {
  return `${utcTimeFormatter.format(asDate(value))} UTC`;
}

/** The UTC date of a technical instant, "15 Oct 2026", to go with `formatTimeUtc`. */
export function formatDateUtc(value: When) {
  return utcDateFormatter.format(asDate(value));
}

/** The viewer's own time zone ("Europe/London"), for schedules they set. */
export function viewerTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

/** Milliseconds for a person: a sub-millisecond answer is not "0 ms". */
export function formatDurationMs(value: number) {
  if (value < 1) return "< 1 ms";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}

/** A number as written in prose: "1,200", "3.75". Missing reads "--". */
export function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return "--";
  }
  return numberFormatter.format(value);
}

/** A whole number: "1,200". */
export function formatCount(value: number) {
  return integerFormatter.format(value);
}

/** A change in a count, with its sign: "+12", "−1,200". */
export function formatSignedCount(value: number) {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${integerFormatter.format(Math.abs(value))}`;
}

/** Text in the order a person expects: "item 2" before "item 10", case ignored. */
export function compareText(a: string, b: string): number {
  return collator.compare(a, b);
}

/** "1 row", "3 rows", "1,200 rows": a count with its noun, never "row(s)". */
export function countOf(count: number | null | undefined, noun: string, pluralNoun = `${noun}s`): string {
  const value = Number(count ?? 0);
  return `${integerFormatter.format(value)} ${value === 1 ? noun : pluralNoun}`;
}
