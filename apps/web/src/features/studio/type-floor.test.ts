import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const STUDIO = fileURLToPath(new URL(".", import.meta.url));

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return files(path);
    return /\.tsx?$/.test(entry) && !entry.includes(".test.") ? [path] : [];
  });
}

describe("Studio type sizes", () => {
  it("never sets text below 12px, in classes or on the grid's canvas", () => {
    const small: string[] = [];
    for (const file of files(STUDIO)) {
      const source = readFileSync(file, "utf8");
      for (const match of source.matchAll(/text-\[(\d+(?:\.\d+)?)px\]|\b(\d+(?:\.\d+)?)px ui-sans-serif/g)) {
        const size = Number(match[1] ?? match[2]);
        if (size < 12) small.push(`${file.slice(STUDIO.length)}: ${match[0]}`);
      }
    }
    expect(small).toEqual([]);
  });
});
