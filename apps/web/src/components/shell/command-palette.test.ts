import { describe, expect, it } from "vitest";

import { scoreCommand, type Command } from "./command-palette";

function command(overrides: Partial<Command> & Pick<Command, "id" | "label">): Command {
  return { group: "Navigation", icon: "grid", ...overrides };
}

const DATA_QUALITY = command({ id: "dq", label: "Data quality" });
const TITLE_CASE = command({
  id: "t",
  label: "Title Case",
  group: "Text",
  keywords: "text title case proper case initcap capitalise each word",
});
const TRIM = command({ id: "x", label: "Trim whitespace", group: "Text", keywords: "strip" });

describe("scoreCommand", () => {
  it("matches a subsequence of the label", () => {
    expect(scoreCommand("dq", DATA_QUALITY)).toBeGreaterThan(0);
  });

  it("finds a command by a word nobody would guess from the label", () => {
    // "initcap" appears nowhere in "Title Case".
    expect(scoreCommand("initcap", TITLE_CASE)).toBeGreaterThan(0);
    expect(scoreCommand("initcap", TRIM)).toBe(0);
  });

  it("still ranks an exact label above a synonym match", () => {
    const byLabel = scoreCommand("trim whitespace", TRIM);
    const bySynonym = scoreCommand("strip", TRIM);
    expect(byLabel).toBeGreaterThan(bySynonym);
  });

  it("ranks a synonym above a group that merely contains the query", () => {
    expect(scoreCommand("strip", TRIM)).toBeGreaterThan(scoreCommand("text", TRIM));
  });

  it("returns everything for an empty query", () => {
    expect(scoreCommand("", TRIM)).toBeGreaterThan(0);
  });

  it("scores nothing for a query that matches nowhere", () => {
    expect(scoreCommand("zzqq", TRIM)).toBe(0);
  });
});
