/**
 * Design tokens, read for the canvas.
 *
 * A canvas cannot use CSS classes, so the grid has to resolve the theme's
 * colours itself. Reading them from the same custom properties everything else
 * uses -- rather than hardcoding a palette here -- is what keeps the grid in
 * step with light, dark and system, and with any future change to the tokens.
 */

export type GridPalette = {
  canvas: string;
  surface: string;
  surfaceAlt: string;
  header: string;
  ink: string;
  inkMuted: string;
  line: string;
  lineStrong: string;
  accent: string;
  accentSoft: string;
  accentInk: string;
  danger: string;
  selectionFill: string;
  /* Row states, for surfaces that stage changes before writing them. */
  editedFill: string;
  deletedFill: string;
  newFill: string;
};

/**
 * The tokens the canvas needs. Every one must resolve.
 *
 * There are deliberately no fallback colours. A plausible-looking default --
 * white surface, near-black ink -- would render a light grid on a dark page and
 * look enough like a design choice that nobody investigates. Returning null and
 * refusing to draw makes a missing token impossible to miss.
 */
const TOKENS = {
  canvas: "--canvas",
  surface: "--surface",
  surfaceAlt: "--surface-2",
  header: "--sunken",
  ink: "--ink",
  inkMuted: "--muted",
  line: "--line",
  lineStrong: "--line-strong",
  accent: "--accent",
  accentSoft: "--accent-soft",
  accentInk: "--accent-ink",
  danger: "--danger",
  selectionFill: "--accent-faint",
  editedFill: "--warning-soft",
  deletedFill: "--danger-soft",
  newFill: "--success-soft",
} as const satisfies Record<keyof GridPalette, string>;

/** The resolved palette, or null when the design tokens are not available. */
export function readPalette(element: HTMLElement): GridPalette | null {
  const styles = getComputedStyle(element);
  const resolved: Partial<Record<keyof GridPalette, string>> = {};
  const missing: string[] = [];

  for (const [key, token] of Object.entries(TOKENS) as [keyof GridPalette, string][]) {
    const value = styles.getPropertyValue(token).trim();
    if (value === "") missing.push(token);
    else resolved[key] = value;
  }

  if (missing.length > 0) {
    console.warn(`Grid palette could not resolve: ${missing.join(", ")}`);
    return null;
  }
  return resolved as GridPalette;
}

/** How a value is drawn: numbers right-aligned, nulls shown as absent. */
export type CellStyle = { text: string; align: "left" | "right"; muted: boolean };

export function formatCell(value: unknown): CellStyle {
  if (value === null || value === undefined) {
    // An empty cell and a null are different facts, and a grid that renders
    // both as blank hides the one that matters.
    return { text: "null", align: "left", muted: true };
  }
  if (typeof value === "number") {
    return { text: formatNumber(value), align: "right", muted: false };
  }
  if (typeof value === "boolean") {
    return { text: value ? "true" : "false", align: "left", muted: false };
  }
  const text = String(value);
  if (text === "") return { text: "", align: "left", muted: false };
  return { text, align: "left", muted: false };
}

function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return String(value);
  // Deliberately NOT grouped. Thousands separators make an order_id of 1001
  // read as "1,001", which is wrong for every identifier column -- and
  // identifiers are the commonest integer column there is. Excel does not group
  // by default either; grouping is a formatting choice, and it belongs with the
  // rest of the column formatting tools rather than being imposed here.
  if (Number.isInteger(value)) return String(value);
  // Rounded so the cell reads 0.3 rather than 0.30000000000000004.
  return String(Number(value.toFixed(6)));
}

/** Truncate to fit, with an ellipsis, measuring against the canvas context. */
export function fitText(
  context: CanvasRenderingContext2D,
  text: string,
  maxWidth: number
): string {
  if (maxWidth <= 0) return "";
  if (context.measureText(text).width <= maxWidth) return text;

  const ellipsis = "…";
  let low = 0;
  let high = text.length;
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    const candidate = text.slice(0, mid) + ellipsis;
    if (context.measureText(candidate).width <= maxWidth) low = mid;
    else high = mid - 1;
  }
  return low === 0 ? "" : text.slice(0, low) + ellipsis;
}

/**
 * A short glyph naming a column's type, shown in the header.
 *
 * Reads the canonical type where the API supplies one (Phase 08) and falls back
 * to the legacy vocabulary, so a column typed `decimal(18,2)` reads as exact
 * rather than as "float".
 */
export function typeGlyph(type: string | undefined | null): string {
  if (!type) return "";
  const lowered = type.toLowerCase();

  // Canonical types first: they carry more than the legacy names do.
  if (lowered.startsWith("decimal")) return "1.2₀";
  if (lowered.startsWith("timestamp")) return lowered.includes("tz") ? "CAL·TZ" : "CAL";
  if (lowered.startsWith("array") || lowered.startsWith("struct") || lowered.startsWith("map")) {
    return "{ }";
  }
  if (lowered.startsWith("string")) return "ABC";
  if (lowered.startsWith("int") || lowered.startsWith("uint")) return "123";
  if (lowered.startsWith("float")) return "1.2";

  return (
    {
      int: "123",
      integer: "123",
      float: "1.2",
      double: "1.2",
      string: "ABC",
      text: "ABC",
      boolean: "T/F",
      bool: "T/F",
      datetime: "CAL",
      date: "CAL",
      time: "CAL",
      uuid: "ID",
      bytes: "BIN",
      json: "{ }",
      dict: "{ }",
      list: "[ ]",
      decimal: "1.2\u2080",
      empty: "\u2014",
      mixed: "MIX",
      unknown: "?",
    }[lowered] ?? ""
  );
}

/** Numeric columns are right-aligned so digits line up down the column. */
export function isNumericType(type: string | undefined | null): boolean {
  if (!type) return false;
  const lowered = type.toLowerCase();
  return (
    lowered.startsWith("int") ||
    lowered.startsWith("uint") ||
    lowered.startsWith("float") ||
    lowered.startsWith("decimal") ||
    lowered === "double"
  );
}

