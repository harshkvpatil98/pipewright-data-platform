import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import en from "../../messages/en.json";
import { countOf, formatCount, formatDate, formatSignedCount } from "./format";
import { LOCALE, t, tList } from "./i18n";
import { AREAS, STANDALONE_PAGES } from "./navigation";

/*
 * The catalogue and the one place dates and numbers are written (A8, Y7).
 */

const SRC = fileURLToPath(new URL("..", import.meta.url));

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.tsx?$/.test(entry) && !entry.includes(".test.") ? [path] : [];
  });
}

/** Every dotted key in the catalogue that holds words. */
function keys(node: unknown, prefix = ""): string[] {
  if (typeof node === "string" || Array.isArray(node)) return [prefix];
  return Object.entries(node as Record<string, unknown>).flatMap(([key, value]) =>
    key.startsWith("$") || key === "locale" ? [] : keys(value, prefix ? `${prefix}.${key}` : key),
  );
}

describe("the message catalogue", () => {
  it("reads messages and fills their places", () => {
    expect(LOCALE).toBe("en-GB");
    expect(t("shell.topBar.signOut")).toBe("Sign out");
    expect(t("shell.projectSwitcher.current", { name: "Regional sales" })).toBe("Project: Regional sales. Switch project");
    expect(tList("nav.tabs.overview.activity.help").length).toBeGreaterThan(1);
  });

  it("holds every word of the navigation", () => {
    for (const area of AREAS) {
      expect(area.label).not.toMatch(/^nav\./);
      for (const tab of area.tabs) {
        expect(tab.label).not.toMatch(/^nav\./);
        expect(tab.help.length).toBeGreaterThan(0);
      }
    }
    expect(STANDALONE_PAGES.map((page) => page.label)).toEqual(["Help", "Notifications", "Your settings"]);
  });

  it("has no message nothing reads", () => {
    const code = sourceFiles(SRC).map((file) => readFileSync(file, "utf8")).join("\n");
    // Navigation keys are built from each area and tab id, so they are read
    // whenever the area or tab exists.
    const unused = keys(en).filter((key) => !key.startsWith("nav.") && !code.includes(`"${key}"`));
    expect(unused).toEqual([]);
  });

  it("keeps the same places in a message as its callers fill", () => {
    const places = keys(en).flatMap((key) => {
      const value = key.split(".").reduce<unknown>((node, part) => (node as Record<string, unknown>)[part], en);
      return typeof value === "string" ? [...value.matchAll(/\{(\w+)\}/g)].map((match) => `${key}:${match[1]}`) : [];
    });
    expect(places.sort()).toEqual(["shell.palette.recent:where", "shell.projectSwitcher.current:name", "shell.tabs.about:tab", "shell.tabs.pages:area"]);
  });
});

describe("dates and numbers", () => {
  it("are written in the catalogue's locale", () => {
    expect(formatDate("2026-11-14T10:00:00Z")).toBe("14 Nov 2026");
    expect(formatCount(1234567.6)).toBe("1,234,568");
    expect(formatSignedCount(-1200)).toBe("−1,200");
    expect(countOf(1, "row")).toBe("1 row");
    expect(countOf(1200, "row")).toBe("1,200 rows");
  });

  it("are written in one place", () => {
    const elsewhere = sourceFiles(SRC)
      .filter((file) => !file.endsWith("/lib/format.ts"))
      .flatMap((file) =>
        readFileSync(file, "utf8")
          .split("\n")
          .map((line, index) => ({ file: file.slice(SRC.length), line: index + 1, text: line }))
          .filter(({ text }) => /new Intl\.|Intl\.(DateTimeFormat|NumberFormat)\(|\.toLocale(String|DateString|TimeString)\(/.test(text)),
      )
      .map(({ file, line }) => `${file}:${line}`);
    expect(elsewhere).toEqual([]);
  });
});
