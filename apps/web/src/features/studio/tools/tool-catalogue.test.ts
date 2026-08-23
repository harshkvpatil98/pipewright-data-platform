import { describe, expect, it } from "vitest";

import {
  acceptsType,
  defaultValues,
  exampleLine,
  groupByCategory,
  queryWords,
  rankTools,
  toConfig,
  toolsForColumn,
  type Tool,
} from "./tool-catalogue";

function tool(overrides: Partial<Tool> & Pick<Tool, "name" | "title">): Tool {
  return {
    category: "Text",
    summary: "Does a thing.",
    synonyms: [],
    accepts: "textual",
    column_scoped: true,
    params: [],
    example: { rows: [], params: {}, column: null, output: null, expect: [], note: "" },
    ...overrides,
  };
}

const TRIM = tool({
  name: "text.trim",
  title: "Trim whitespace",
  synonyms: ["strip", "whitespace"],
  example: {
    rows: [{ value: "  a  " }],
    params: {},
    column: "value",
    output: null,
    expect: ["a"],
    note: "",
  },
});
const YEAR = tool({
  name: "date.year",
  title: "Year",
  category: "Date & time",
  accepts: "temporal",
  synonyms: ["yyyy"],
});
const ROUND = tool({
  name: "numeric.round",
  title: "Round",
  category: "Numeric",
  accepts: "numeric",
});
const SORT = tool({
  name: "rows.sort",
  title: "Sort rows",
  category: "Rows",
  accepts: "any",
  column_scoped: false,
});
const PHONE = tool({
  name: "clean.phone",
  title: "Standardise a phone number",
  category: "Cleansing",
  synonyms: ["e164", "telephone"],
});
const SOUNDEX = tool({
  name: "text.soundex",
  title: "Soundex code",
  summary: "A phonetic code for matching names.",
  synonyms: ["phonetic"],
});

const ALL = [TRIM, YEAR, ROUND, SORT, PHONE, SOUNDEX];

describe("queryWords", () => {
  it("drops filler words", () => {
    expect(queryWords("extract year from date")).toEqual(["extract", "year", "date"]);
  });

  it("splits on punctuation so a tool name works as a query", () => {
    expect(queryWords("text.trim")).toEqual(["text", "trim"]);
  });

  it("is empty for an empty query", () => {
    expect(queryWords("   ")).toEqual([]);
  });
});

describe("rankTools", () => {
  it("returns everything for an empty query", () => {
    expect(rankTools(ALL, "")).toHaveLength(ALL.length);
  });

  it("finds a tool by a synonym", () => {
    expect(rankTools(ALL, "e164")[0]).toBe(PHONE);
    expect(rankTools(ALL, "yyyy")[0]).toBe(YEAR);
  });

  it("requires every word to match", () => {
    // With an any-word rule, adding detail would make results worse.
    expect(rankTools(ALL, "trim whitespace")[0]).toBe(TRIM);
    expect(rankTools(ALL, "trim banana")).toEqual([]);
  });

  it("prefers a word boundary over a substring", () => {
    // "phonetic" contains "phone"; the phone tool should still win.
    expect(rankTools(ALL, "phone")[0]).toBe(PHONE);
  });

  it("ranks an exact title above a partial one", () => {
    expect(rankTools(ALL, "round")[0]).toBe(ROUND);
  });

  it("is stable for equal scores", () => {
    const first = rankTools(ALL, "text").map((entry) => entry.name);
    const second = rankTools([...ALL].reverse(), "text").map((entry) => entry.name);
    expect(first).toEqual(second);
  });
});

describe("acceptsType", () => {
  it("keeps date tools off numbers and number tools off text", () => {
    expect(acceptsType(YEAR, "float64")).toBe(false);
    expect(acceptsType(YEAR, "timestamp")).toBe(true);
    expect(acceptsType(ROUND, "string")).toBe(false);
    expect(acceptsType(ROUND, "int64")).toBe(true);
  });

  it("offers everything on a column whose type is not known", () => {
    expect(acceptsType(YEAR, undefined)).toBe(true);
    expect(acceptsType(YEAR, "unknown")).toBe(true);
    expect(acceptsType(ROUND, "unknown")).toBe(true);
  });

  it("lets an any-tool through regardless", () => {
    expect(acceptsType(SORT, "timestamp")).toBe(true);
  });
});

describe("toolsForColumn", () => {
  it("excludes tools that reshape the frame", () => {
    const offered = toolsForColumn(ALL, "string").map((entry) => entry.name);
    expect(offered).toContain("text.trim");
    expect(offered).not.toContain("rows.sort");
  });

  it("narrows by the column's type", () => {
    expect(toolsForColumn(ALL, "timestamp").map((t) => t.name)).toContain("date.year");
    expect(toolsForColumn(ALL, "timestamp").map((t) => t.name)).not.toContain("numeric.round");
  });
});

describe("groupByCategory", () => {
  it("keeps the order tools arrived in", () => {
    const groups = groupByCategory(ALL);
    expect(groups.map((group) => group.category)).toEqual([
      "Text",
      "Date & time",
      "Numeric",
      "Rows",
      "Cleansing",
    ]);
    expect(groups[0].tools.map((t) => t.name)).toEqual(["text.trim", "text.soundex"]);
  });
});

describe("defaultValues", () => {
  it("uses each parameter's declared default", () => {
    const withParams = tool({
      name: "x.y",
      title: "X",
      params: [
        { key: "n", label: "N", kind: "integer", required: true, default: 5, options: [], help: "", placeholder: "", minimum: null, maximum: null },
        { key: "flag", label: "Flag", kind: "boolean", required: false, default: null, options: [], help: "", placeholder: "", minimum: null, maximum: null },
        { key: "s", label: "S", kind: "text", required: false, default: null, options: [], help: "", placeholder: "", minimum: null, maximum: null },
      ],
    });
    expect(defaultValues(withParams)).toEqual({ n: 5, flag: false, s: "" });
  });
});

describe("toConfig", () => {
  const withParams = tool({
    name: "text.pad_left",
    title: "Pad left",
    params: [
      { key: "length", label: "Length", kind: "integer", required: true, default: 10, options: [], help: "", placeholder: "", minimum: null, maximum: null },
      { key: "fill", label: "Fill", kind: "text", required: false, default: "0", options: [], help: "", placeholder: "", minimum: null, maximum: null },
    ],
  });

  it("names the tool and the column", () => {
    expect(toConfig(withParams, "sku", null, { length: 5, fill: "0" })).toEqual({
      tool: "text.pad_left",
      column: "sku",
      length: 5,
      fill: "0",
    });
  });

  it("adds a destination only when one was given", () => {
    expect(toConfig(withParams, "sku", "  ", { length: 5 })).not.toHaveProperty("into");
    expect(toConfig(withParams, "sku", " padded ", { length: 5 }).into).toBe("padded");
  });

  it("omits an empty optional rather than sending a blank", () => {
    // Sending "" would turn "use the default" into "use nothing".
    const config = toConfig(withParams, "sku", null, { length: 5, fill: "" });
    expect(config).not.toHaveProperty("fill");
  });

  it("does not send a column for a tool that reshapes the frame", () => {
    expect(toConfig(SORT, "sku", null, {})).not.toHaveProperty("column");
  });
});

describe("exampleLine", () => {
  it("reads as this in, that out", () => {
    expect(exampleLine(TRIM)).toBe("  a   → a");
  });

  it("is absent when a tool documents shape rather than a value", () => {
    expect(exampleLine(YEAR)).toBeNull();
  });

  it("names empty and blank rather than showing nothing", () => {
    const withNulls = tool({
      name: "n.x",
      title: "N",
      example: { rows: [{ v: null }], params: {}, column: "v", output: null, expect: [""], note: "" },
    });
    expect(exampleLine(withNulls)).toBe("empty → blank");
  });
});
