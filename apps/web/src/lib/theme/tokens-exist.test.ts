import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Every `var(--token)` in the source must name a token the stylesheet defines.
 *
 * A misspelled custom property is not an error anywhere: `var(--warn-line)`
 * when the token is `--warning-line` resolves to nothing, the border renders
 * transparent, and the page looks *almost* right -- a slightly flatter card
 * that nobody files a bug about. The compiler cannot see it, the linter cannot
 * see it, and a screenshot only shows it if you already know to look.
 *
 * This is the sibling of `no-raw-colours`: that one catches colours that bypass
 * the token layer, this one catches colours that reference it and miss.
 */

const SOURCE_ROOTS = [
  join(process.cwd(), "src"),
  join(process.cwd(), "..", "..", "packages", "shared-ui", "src"),
];
const STYLESHEET = join(process.cwd(), "src", "app", "globals.css");

/** Tokens Tailwind v4 defines for us, and the ones the browser supplies. */
const PROVIDED = new Set(["--tw-", "--radix-", "--spacing", "--default-"]);

function walk(directory: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(directory)) {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) {
      if (entry === "node_modules" || entry === ".next") continue;
      found.push(...walk(path));
    } else if (/\.(tsx?|css)$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
      found.push(path);
    }
  }
  return found;
}

function definedTokens(): Set<string> {
  const css = readFileSync(STYLESHEET, "utf8");
  const names = new Set<string>();
  for (const match of css.matchAll(/^\s*(--[a-z0-9-]+)\s*:/gim)) names.add(match[1]);
  return names;
}

describe("CSS custom properties", () => {
  const defined = definedTokens();

  it("defines the palette the tests below check against", () => {
    // A sanity check on the parser itself: if this stops finding tokens, the
    // suite would pass by finding nothing to complain about.
    expect(defined.size).toBeGreaterThan(50);
    expect(defined.has("--accent")).toBe(true);
  });

  it("has a definition for every token the source references", () => {
    const offenders: string[] = [];

    for (const root of SOURCE_ROOTS) {
      for (const file of walk(root)) {
        if (file === STYLESHEET) continue;
        const contents = readFileSync(file, "utf8");
        for (const match of contents.matchAll(/var\(\s*(--[a-z0-9-]+)(\$\{)?/gi)) {
          const token = match[1];
          const interpolated = match[2] !== undefined;
          if (interpolated) {
            // `var(--series-${n})` names a family. Check the family exists
            // rather than guessing which members the code will ask for.
            if ([...defined].some((name) => name.startsWith(token))) continue;
          } else if (defined.has(token)) {
            continue;
          }
          if ([...PROVIDED].some((prefix) => token.startsWith(prefix))) continue;
          offenders.push(`${file.replace(process.cwd(), ".")}: ${token}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });
});
