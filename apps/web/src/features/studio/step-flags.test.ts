import { describe, expect, it } from "vitest";

import { filterBySelection, shownValue } from "./cell-filter-menu";
import { usedParameters } from "./recipe-actions";
import {
  ENABLED,
  GROUP,
  NOTE,
  groupRuns,
  grouped,
  isOff,
  keepFlags,
  noted,
  noteOf,
  turned,
  withoutRemarks,
} from "./step-flags";
import { schemaWord } from "./tools/regex-tester";

describe("step flags", () => {
  it("turns a step off and on, writing nothing for on", () => {
    const off = turned({ count: 5 }, false);
    expect(off).toEqual({ count: 5, [ENABLED]: false });
    expect(isOff(off)).toBe(true);
    expect(turned(off, true)).toEqual({ count: 5 });
  });

  it("keeps a note, and an empty one is removed", () => {
    const withNote = noted({ count: 5 }, "Only the first five for the report");
    expect(noteOf(withNote)).toBe("Only the first five for the report");
    expect(noted(withNote, "  ")).toEqual({ count: 5 });
  });

  it("carries the flags over when a settings form writes its own settings", () => {
    const before = { count: 5, [ENABLED]: false, [NOTE]: "why" };
    expect(keepFlags(before, { count: 6 })).toEqual({ count: 6, [ENABLED]: false, [NOTE]: "why" });
    // A form that sets a flag itself wins.
    expect(keepFlags(before, { count: 6, [NOTE]: "new" })[NOTE]).toBe("new");
  });

  it("leaves the note and the group out of what decides the preview", () => {
    expect(withoutRemarks({ count: 5, [NOTE]: "why", [GROUP]: "Tidy" })).toEqual({ count: 5 });
    const plain = { count: 5 };
    expect(withoutRemarks(plain)).toBe(plain);
  });

  it("finds the groups of steps next to each other", () => {
    const steps = [
      { uid: "a", config: grouped({}, "Tidy") },
      { uid: "b", config: grouped({}, "Tidy") },
      { uid: "c", config: {} },
      { uid: "d", config: grouped({}, "Tidy") },
      { uid: "e", config: grouped({}, "Totals") },
    ];
    const runs = groupRuns(steps);
    expect([...runs.keys()]).toEqual(["a", "d", "e"]);
    expect(runs.get("a")).toEqual({ name: "Tidy", uids: ["a", "b"] });
    expect(grouped({ [GROUP]: "Tidy", count: 1 }, " ")).toEqual({ count: 1 });
    expect(keepFlags({ [GROUP]: "Tidy" }, { count: 2 })).toEqual({ count: 2, [GROUP]: "Tidy" });
  });
});

describe("recipe parameters", () => {
  it("finds every {{name}} in any setting, once", () => {
    const steps = [
      { step_type: "filter_rows", config: { conditions: [{ column: "amount", value: "{{least}}" }] } },
      { step_type: "tool", config: { tool: "text.prefix", params: { text: "orders_{{ region }}_{{least}}" } } },
      { step_type: "limit_rows", config: { count: 5 } },
    ];
    expect(usedParameters(steps).sort()).toEqual(["least", "region"]);
  });

  it("ignores text that only looks like a parameter", () => {
    expect(usedParameters([{ step_type: "tool", config: { text: "{{1st}} {single}" } }])).toEqual([]);
  });
});

describe("schema words", () => {
  it("names a column's type the way a schema check takes it", () => {
    expect(schemaWord("integer")).toBe("number");
    expect(schemaWord("float")).toBe("number");
    expect(schemaWord("datetime")).toBe("date");
    expect(schemaWord("boolean")).toBe("true or false");
    expect(schemaWord("string")).toBe("text");
    expect(schemaWord(undefined)).toBe("text");
    expect(schemaWord("int64")).toBe("number");
    expect(schemaWord("point")).toBe("text");
    expect(schemaWord("timestamp with time zone")).toBe("date");
    expect(schemaWord("interval")).toBe("date");
    expect(schemaWord("decimal(18,2)")).toBe("number");
  });
});

describe("filtering by a selected cell", () => {
  it("keeps or drops rows with the value, typed as the column is on the server", () => {
    expect(filterBySelection({ column: "region", value: "eu" }, "keep")).toEqual({
      tool: "rows.filter",
      column: "region",
      operator: "equals",
      value: "eu",
      mode: "keep",
    });
    expect(filterBySelection({ column: "amount", value: 1.5 }, "exclude")).toMatchObject({ value: "1.5", mode: "exclude" });
    expect(filterBySelection({ column: "paid", value: false }, "keep")).toMatchObject({ value: "false" });
  });

  it("filters on emptiness for an empty cell, and refuses lists and objects", () => {
    expect(filterBySelection({ column: "region", value: null }, "keep")).toMatchObject({ operator: "is empty", value: "" });
    expect(filterBySelection({ column: "region", value: "" }, "exclude")).toMatchObject({ operator: "is empty" });
    expect(filterBySelection({ column: "tags", value: ["a"] }, "keep")).toBeNull();
    expect(filterBySelection({ column: "meta", value: { a: 1 } }, "keep")).toBeNull();
  });

  it("shows a long value short", () => {
    expect(shownValue(null)).toBe("empty");
    expect(shownValue("x".repeat(40))).toHaveLength(32);
  });
});
