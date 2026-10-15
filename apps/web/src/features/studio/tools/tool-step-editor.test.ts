import { describe, expect, it } from "vitest";

import type { Tool, ToolParam } from "./tool-catalogue";
import { describeToolStep } from "./tool-step-editor";

const param = (key: string, kind: ToolParam["kind"], extra: Partial<ToolParam> = {}): ToolParam => ({
  key,
  label: key,
  kind,
  required: true,
  default: null,
  options: [],
  help: "",
  placeholder: "",
  minimum: null,
  maximum: null,
  ...extra,
});

const tool = (name: string, title: string, params: ToolParam[], column_scoped = false): Tool => ({
  name,
  title,
  category: "Test",
  summary: "",
  synonyms: [],
  accepts: "any",
  column_scoped,
  params,
  example: { rows: [], params: {}, column: null, output: null, expect: [], note: "" },
});

const TOOLS = [
  tool("assert.not_empty", "Check nothing is empty", [param("columns", "columns"), param("on_failure", "select", { default: "stop the run" })]),
  tool("lookup.from_dataset", "Look up values", [param("right_dataset_id", "dataset"), param("on", "columns"), param("bring", "dataset_columns")]),
  tool("text.upper", "UPPERCASE", [], true),
  tool("rows.reverse", "Reverse the rows", []),
];

describe("a tool step's line in the steps", () => {
  it("says what a tool that works on no one column was given", () => {
    expect(describeToolStep({ tool: "assert.not_empty", columns: ["manager"] }, TOOLS)).toEqual({
      label: "Check nothing is empty",
      detail: "manager",
      incomplete: false,
    });
    const lookup = describeToolStep(
      { tool: "lookup.from_dataset", right_dataset_id: "d1", on: ["region"], bring: ["manager", "phone"] },
      TOOLS,
      new Map([["d1", "Regions"]]),
    );
    expect(lookup.detail).toBe("Regions · region · manager, phone");
  });

  it("is not set up while a required setting is empty, or a column tool has no column", () => {
    expect(describeToolStep({ tool: "assert.not_empty" }, TOOLS).incomplete).toBe(true);
    expect(describeToolStep({ tool: "text.upper" }, TOOLS).incomplete).toBe(true);
    expect(describeToolStep({ tool: "text.upper", column: "name", into: "loud" }, TOOLS)).toMatchObject({
      detail: "name → loud",
      incomplete: false,
    });
  });

  it("is set up when there is nothing to set", () => {
    expect(describeToolStep({ tool: "rows.reverse" }, TOOLS)).toEqual({ label: "Reverse the rows", detail: "", incomplete: false });
  });
});
