const dateFormatter = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "numeric",
  year: "numeric",
});

const numberFormatter = new Intl.NumberFormat("en");

export function formatDate(value: string) {
  return dateFormatter.format(new Date(value));
}

const dateTimeFormatter = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
});

/** A technical instant -- a publication time, a frozen evaluation instant --
 * shown to the minute in UTC, which is the zone every such value is recorded
 * in. A date alone cannot tell two versions published the same day apart. */
export function formatDateTime(value: string) {
  return `${dateTimeFormatter.format(new Date(value))} UTC`;
}

/** Milliseconds for a person: a sub-millisecond answer is not "0 ms". */
export function formatDurationMs(value: number) {
  if (value < 1) return "< 1 ms";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}

export function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return "--";
  }
  return numberFormatter.format(value);
}

export function titleCase(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}
