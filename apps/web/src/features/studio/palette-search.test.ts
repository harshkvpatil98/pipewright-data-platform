import { describe, expect, it } from "vitest";

import { scoreCommand, type Command } from "@/components/shell/command-palette";

import { STEP_COMMANDS, firstMatch, stepsLead } from "./palette-search";
import catalogue from "./tools/search-catalogue.json";
import { rankTools, type Tool } from "./tools/tool-catalogue";

// The real catalogue, as the server's registry has it (regenerated with the
// tool reference, and checked against the registry by a server test).
const TOOLS: Tool[] = catalogue.map((item) => ({
  ...item,
  accepts: "any",
  column_scoped: false,
  params: [],
  example: { rows: [], params: {}, column: null, output: null, expect: [], note: "" },
}));

const first = (query: string) => {
  const found = firstMatch(query, TOOLS);
  return found === null ? null : found.kind === "step" ? `step:${found.step.type}` : found.tool.name;
};

/* The everyday searches measured before E1 (26 of 29 found nothing). */
describe("an everyday search in the Studio", () => {
  it.each([
    ["running total", "window.cumulative_sum"],
    ["moving average", "window.moving_average"],
    ["previous row", "window.lag"],
    ["anti join", "step:join_datasets"],
    ["semi join", "step:join_datasets"],
    ["fuzzy join", "join.fuzzy"],
    ["random sample", "sample.random"],
    ["train/test split", "sample.train_test"],
    ["distance", "geo.distance"],
    ["point in polygon", "geo.point_in_polygon"],
    ["cluster", "match.cluster"],
    ["one-hot", "ml.one_hot"],
    ["holiday", "date.is_holiday"],
    ["lookup", "lookup.from_dataset"],
    ["fill forward", "null.fill_forward"],
    ["interpolate", "null.interpolate_linear"],
    ["assert unique", "assert.unique"],
    ["golden record", "match.golden_record"],
    ["geocode", "geo.geocode"],
    ["unit convert", "numeric.convert_units"],
    ["transpose", "reshape.transpose"],
    ["SQL", "code.sql"],
    ["UUID", "key.uuid"],
    ["rank", "window.rank"],
    ["t test", "stats.t_test"],
    // A percentile and a correlation of a group are the summarise step's.
    ["percentile", "step:aggregate"],
    ["correlation", "step:aggregate"],
    ["group by", "step:aggregate"],
    ["pivot", "step:pivot"],
    ["split column", "step:split_column"],
  ])("finds what %s means first", (query, expected) => {
    expect(first(query)).toBe(expected);
  });

  it("finds a forecast first for a forecast", () => {
    expect(first("forecast")).toMatch(/^ml\.forecast_/);
  });

  it("leads with tools when a tool is the better match", () => {
    expect(stepsLead("lookup", TOOLS)).toBe(false);
    expect(stepsLead("anti join", TOOLS)).toBe(true);
  });

  it("ranks the tools the way the server does", () => {
    // Mirrors `test_tool_search.py` on the same catalogue.
    expect(rankTools(TOOLS, "t test")[0].name).toBe("stats.t_test");
    expect(rankTools(TOOLS, "zip code")[0].name).toBe("clean.postal_code");
    expect(rankTools(TOOLS, "remove duplicates")[0].name).toBe("rows.deduplicate");
  });
});

describe("turning a step off", () => {
  it("is found as a command", () => {
    const commands: Command[] = [
      ...STEP_COMMANDS.map((command) => ({ ...command, group: "Studio" })),
      ...TOOLS.map((tool) => ({
        id: `tool:${tool.name}`,
        label: tool.title,
        group: tool.category,
        icon: "sparkles" as const,
        keywords: [tool.name.replace(/[._]/g, " "), ...tool.synonyms].join(" "),
      })),
    ];
    const best = [...commands].sort((left, right) => scoreCommand("disable a step", right) - scoreCommand("disable a step", left))[0];
    expect(best.id).toBe("studio:turn");
  });
});
