const dateFormatter = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "numeric",
  year: "numeric",
});

const numberFormatter = new Intl.NumberFormat("en");

export function formatDate(value: string) {
  return dateFormatter.format(new Date(value));
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
