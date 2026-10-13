import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const ROOTS = [
  fileURLToPath(new URL("..", import.meta.url)),
  fileURLToPath(new URL("../../../../packages/shared-ui/src", import.meta.url)),
];

function sourceFiles(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) found.push(...sourceFiles(path));
    else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) found.push(path);
  }
  return found;
}

// A dash between words, or at the start or end of a wrapped line of text. A
// lone "—" standing for an empty value in a table cell is fine.
const PROSE_DASH = /[\w.,)”'"’] —(\s|$)|^\s*— \w/;

describe("on-screen wording", () => {
  it("writes sentences without em-dashes", () => {
    const offenders: string[] = [];
    for (const root of ROOTS) {
      for (const file of sourceFiles(root)) {
        readFileSync(file, "utf8")
          .split("\n")
          .forEach((line, index) => {
            const trimmed = line.trim();
            if (trimmed.startsWith("//") || trimmed.startsWith("*") || trimmed.startsWith("/*")) return;
            if (PROSE_DASH.test(line)) offenders.push(`${file.split("/src/").pop()}:${index + 1}`);
          });
      }
    }
    expect(offenders).toEqual([]);
  });
});
