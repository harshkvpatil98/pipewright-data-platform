import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * No component may name a colour directly.
 *
 * Tailwind's palette utilities and white/black alpha overlays are theme-blind:
 * `text-slate-400` is legible on a dark ground and washes out on a light one,
 * and `border-white/10` is invisible on light by construction. The app was
 * built dark-only, so it had ~2,800 of them.
 *
 * This scans every source root rather than just the web app. The migration
 * originally missed `packages/shared-ui` -- the Button and Input used on every
 * screen -- and the gap was only caught by looking at a screenshot.
 */

const ROOTS = [
  fileURLToPath(new URL("../../", import.meta.url)), // apps/web/src
  fileURLToPath(new URL("../../../../../packages/shared-ui/src", import.meta.url)),
];

const FAMILIES =
  "white|black|slate|zinc|gray|neutral|stone|blue|indigo|sky|cyan|emerald|green|" +
  "amber|yellow|red|rose|violet|purple|fuchsia|pink|teal|orange|lime";
const PROPERTIES = "bg|text|border|ring|divide|from|to|via|fill|stroke|shadow|outline";

const THEME_BLIND = new RegExp(
  `\\b(?:${PROPERTIES})-(?:${FAMILIES})(?:-[0-9]{2,3})?(?:/(?:\\[[0-9.]+\\]|[0-9]+))?\\b`,
  "g"
);
const HEX = /#[0-9a-fA-F]{6}\b/g;

/**
 * Raw colours hidden inside Tailwind arbitrary values.
 *
 * These survive a class-name migration because they are not class names:
 * `shadow-[0_12px_30px_rgba(79,70,229,0.14)]` kept the OLD indigo brand accent
 * alive as a violet halo under the primary button, long after every
 * `bg-indigo-500` had gone.
 */
const ARBITRARY_COLOUR =
  /(?:shadow|bg|text|border|ring|from|to|via|fill|stroke|outline)-\[[^\]]*(?:rgba?\(|#[0-9a-fA-F]{3,8})[^\]]*\]/g;

function sourceFiles(dir: string): string[] {
  const found: string[] = [];
  const walk = (path: string) => {
    for (const entry of readdirSync(path)) {
      if (entry === "node_modules" || entry.startsWith(".")) continue;
      const full = join(path, entry);
      if (statSync(full).isDirectory()) {
        walk(full);
      } else if (/\.tsx?$/.test(entry) && !full.includes("/lib/theme/")) {
        found.push(full);
      }
    }
  };
  walk(dir);
  return found;
}

const FILES = ROOTS.flatMap(sourceFiles);

describe("no theme-blind colours in components", () => {
  it("scans a meaningful number of files", () => {
    // A regex that matches nothing passes vacuously; this proves it looked.
    expect(FILES.length).toBeGreaterThan(100);
  });

  it("covers the shared component package, not only the web app", () => {
    expect(FILES.some((path) => path.includes("shared-ui"))).toBe(true);
  });

  it("uses no Tailwind palette or white/black alpha utilities", () => {
    const offenders: string[] = [];
    for (const path of FILES) {
      const matches = readFileSync(path, "utf8").match(THEME_BLIND);
      if (matches) {
        offenders.push(`${path.split("/").slice(-2).join("/")}: ${[...new Set(matches)].join(", ")}`);
      }
    }
    expect(offenders, `use semantic tokens instead:\n${offenders.join("\n")}`).toEqual([]);
  });

  it("names no colour with a literal hex value", () => {
    const offenders: string[] = [];
    for (const path of FILES) {
      const matches = readFileSync(path, "utf8").match(HEX);
      if (matches) {
        offenders.push(`${path.split("/").slice(-2).join("/")}: ${[...new Set(matches)].join(", ")}`);
      }
    }
    expect(offenders, `use a token instead:\n${offenders.join("\n")}`).toEqual([]);
  });

  it("hides no colour inside a Tailwind arbitrary value", () => {
    const offenders: string[] = [];
    for (const path of FILES) {
      const matches = readFileSync(path, "utf8").match(ARBITRARY_COLOUR);
      if (matches) {
        offenders.push(
          `${path.split("/").slice(-2).join("/")}: ${[...new Set(matches)].join(", ")}`
        );
      }
    }
    expect(
      offenders,
      `use an elevation or colour token instead:\n${offenders.join("\n")}`
    ).toEqual([]);
  });

  it("does not use --faint as a text colour", () => {
    // --faint is held to 3:1, not AA: it exists for placeholders and non-text
    // decoration. 70 usages had drifted into treating it as a fifth readable
    // level -- uppercase labels, empty-state copy, table headers -- and the
    // route sweep caught them at 3.08:1. Readable text uses --muted.
    const offenders: string[] = [];
    for (const path of FILES) {
      const matches = readFileSync(path, "utf8").match(/(?<![-\w:])text-faint\b/g);
      if (matches) offenders.push(path.split("/").slice(-2).join("/"));
    }
    expect(
      offenders,
      `use text-muted for readable text; text-faint is placeholder-only:\n${offenders.join("\n")}`
    ).toEqual([]);
  });
});
