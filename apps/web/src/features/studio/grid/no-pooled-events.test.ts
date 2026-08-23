import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * A React state updater must not read from a synthetic event.
 *
 * `setState(current => ({ ...current, x: event.currentTarget.x }))` looks
 * correct and works most of the time. The updater runs later, during React's
 * reducer phase, and by then the synthetic event has been nullified -- so
 * `event.currentTarget` is null and the component throws mid-render.
 *
 * It only surfaces when React defers the update, which means it hides until the
 * component is under load. This exact bug unmounted the grid while scrolling a
 * 41-column table and left a 5-column one working, which is the worst possible
 * way to find it.
 *
 * Capture what you need from the event first, then call setState.
 */

const ROOTS = [
  fileURLToPath(new URL("../", import.meta.url)),
  fileURLToPath(new URL("../../../components/", import.meta.url)),
];

/** `setThing((current) => ... )`, capturing the updater body. */
const UPDATER = /set[A-Z]\w*\(\s*\(\s*(?:\w+)?\s*\)\s*=>\s*(\{[\s\S]*?\n\s*\}|\([\s\S]*?\)|[^;\n]+)/g;
const READS_EVENT = /\bevent\.[a-zA-Z]|\be\.(?:currentTarget|target|clientX|clientY|shiftKey|ctrlKey|metaKey|altKey|key)\b/;

function sourceFiles(dir: string): string[] {
  const found: string[] = [];
  const walk = (path: string) => {
    for (const entry of readdirSync(path)) {
      if (entry === "node_modules" || entry.startsWith(".")) continue;
      const full = join(path, entry);
      if (statSync(full).isDirectory()) walk(full);
      else if (/\.tsx$/.test(entry)) found.push(full);
    }
  };
  walk(dir);
  return found;
}

const FILES = ROOTS.flatMap(sourceFiles);

describe("no synthetic event reads inside state updaters", () => {
  it("scans a meaningful number of components", () => {
    // A regex that matches nothing passes vacuously.
    expect(FILES.length).toBeGreaterThan(5);
  });

  it("finds the pattern when it is present", () => {
    // Guard the guard: if this stops matching, the test below passes for the
    // wrong reason.
    const sample = `setViewport((current) => ({ ...current, x: event.currentTarget.scrollLeft }))`;
    const matches = [...sample.matchAll(new RegExp(UPDATER.source, "g"))];
    expect(matches.length).toBeGreaterThan(0);
    expect(READS_EVENT.test(matches[0][1])).toBe(true);
  });

  it("no component reads an event inside a state updater", () => {
    const offenders: string[] = [];
    for (const path of FILES) {
      const source = readFileSync(path, "utf8");
      for (const match of source.matchAll(new RegExp(UPDATER.source, "g"))) {
        if (READS_EVENT.test(match[1])) {
          offenders.push(
            `${path.split("/").slice(-2).join("/")}: ${match[0].replace(/\s+/g, " ").slice(0, 90)}`
          );
        }
      }
    }
    expect(
      offenders,
      "capture the value from the event BEFORE calling setState:\n" + offenders.join("\n")
    ).toEqual([]);
  });
});
