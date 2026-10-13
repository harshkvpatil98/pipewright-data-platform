import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const ROOTS = [
  fileURLToPath(new URL("..", import.meta.url)),
  fileURLToPath(new URL("../../../../packages/shared-ui/src", import.meta.url)),
];

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.tsx?$/.test(entry) && !entry.includes(".test.") ? [path] : [];
  });
}

function scan(pattern: RegExp, keep: (match: RegExpMatchArray) => boolean = () => true): string[] {
  const found: string[] = [];
  for (const root of ROOTS) {
    for (const file of sourceFiles(root)) {
      readFileSync(file, "utf8")
        .split("\n")
        .forEach((line, index) => {
          for (const match of line.matchAll(pattern)) {
            if (keep(match)) found.push(`${file.split("/src/").pop()}:${index + 1}: ${match[0]}`);
          }
        });
    }
  }
  return found;
}

// A5 (adoption-readiness): one type scale everyone can read. Nothing below
// 12px, in classes, on the grid's canvas or in SVG labels; sentence case
// rather than uppercase; no tracked-out letter-spacing.
describe("type scale", () => {
  it("never sets text below 12px", () => {
    const small = [
      ...scan(/text-\[(\d+(?:\.\d+)?)px\]/g, (m) => Number(m[1]) < 12),
      ...scan(/\b(\d+(?:\.\d+)?)px ui-(?:sans|mono)/g, (m) => Number(m[1]) < 12),
      ...scan(/fontSize[=:]\s*\{?\s*(\d+(?:\.\d+)?)/g, (m) => Number(m[1]) < 12),
    ];
    expect(small).toEqual([]);
  });

  it("writes in sentence case, not uppercase, without tracked-out letters", () => {
    expect(scan(/(?<![\w-])uppercase(?![\w-])/g)).toEqual([]);
    expect(scan(/(?<![\w-])tracking-(?:\[[\d.]+em\]|wide|wider|widest)(?![\w-])/g)).toEqual([]);
  });
});
