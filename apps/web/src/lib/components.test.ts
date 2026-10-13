import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const APP = fileURLToPath(new URL("..", import.meta.url));

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.tsx$/.test(entry) && !entry.includes(".test.") ? [path] : [];
  });
}

function find(pattern: RegExp): string[] {
  const found: string[] = [];
  for (const file of sourceFiles(APP)) {
    const source = readFileSync(file, "utf8");
    for (const match of source.matchAll(pattern)) {
      const line = source.slice(0, match.index).split("\n").length;
      found.push(`${file.slice(APP.length)}:${line}: ${match[0].slice(0, 80)}`);
    }
  }
  return found;
}

// A5 (adoption-readiness): one component per job, all in packages/shared-ui,
// so a table, a badge or a dialog looks and behaves the same on every page.
describe("shared components", () => {
  it("draws every table with the shared Table", () => {
    expect(find(/<(table|thead|tbody|tr|th|td)[\s>]/g)).toEqual([]);
  });

  it("opens every dialog, drawer and palette through the shared Overlay", () => {
    expect(find(/role="(dialog|alertdialog|tablist)"/g)).toEqual([]);
  });

  it("does not define its own Button, Modal, Badge, Table, page header, empty state, stat tile, tabs or toast", () => {
    expect(
      find(/function (Button|Modal|Badge|Table|PageHeader|EmptyState|StatTile|StatCard|Tabs|Toast|ToastProvider)\b/g),
    ).toEqual([]);
  });

  it("shows short labels with Badge rather than a hand-made pill", () => {
    const pills = find(/<span\s[^>]*?className="([^"]*)"/g).filter((hit) => {
      const classes = hit.split('className="')[1] ?? "";
      return (
        /\brounded(-full|-md)?\b/.test(classes) &&
        /\bpx-(1\.5|2|2\.5)\b/.test(classes) &&
        /\bpy-(0|0\.5)\b/.test(classes) &&
        /\b(bg-|border\b)/.test(classes)
      );
    });
    expect(pills).toEqual([]);
  });
});
