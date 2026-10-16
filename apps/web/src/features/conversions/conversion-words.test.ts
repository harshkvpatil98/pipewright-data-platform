import { describe, expect, it } from "vitest";

import {
  countsWords,
  madeHref,
  madeWords,
  reportMarkdown,
  visibleSections,
  type ConversionPreview,
} from "@/features/conversions/conversion-words";

const preview: ConversionPreview = {
  format: "dbt",
  title: "the dbt project shop",
  needs: [],
  seeds: [{ key: "seed:a", name: "a", what: "the dbt seed a", file_name: "a.csv" }],
  recipes: [
    { key: "model:a", name: "a", steps: 2, complete: true, reads: "seed:a", parameters: [] },
    { key: "model:b", name: "b", steps: 1, complete: false, reads: "model:a", parameters: [] },
  ],
  checks: [{ key: "check:a", name: "a: id has no empty values", rule_type: "not_null", reads: "model:a" }],
  workflows: [{ key: "workflow:build", name: "dbt build: shop", tasks: 3, trigger_type: "manual", cron_expression: null }],
  sections: [
    { title: "models/a.sql", entries: [{ subject: "model a", status: "converted", became: ["The recipe “a”, step 1: Transform with SQL"], reason: null, notes: [] }] },
    { title: "macros/m.sql", entries: [{ subject: "macro m", status: "not converted", became: [], reason: "A macro is code.", notes: [] }] },
    { title: "empty", entries: [] },
  ],
  counts: { converted: 1, not_converted: 1, nothing_to_do: 0 },
  notes: ["The project is read, never run."],
  choices: [],
};

describe("conversion words", () => {
  it("says what a preview makes, drafts included", () => {
    expect(madeWords(preview)).toBe("2 recipes (1 draft), 1 check, 1 workflow and 1 dataset from its data");
    expect(madeWords({ ...preview, recipes: [], checks: [], workflows: [], seeds: [] })).toBe("Nothing to make");
  });

  it("counts the report's parts", () => {
    expect(countsWords(preview.counts)).toBe("1 part converted and 1 not");
    expect(countsWords({ converted: 3, not_converted: 0, nothing_to_do: 2 })).toBe(
      "3 parts converted and 2 with nothing to do",
    );
  });

  it("links what was made, and nothing that was skipped", () => {
    const made = { kind: "recipe" as const, key: "k", name: "a", status: "made" as const, id: "r1", detail: null };
    expect(madeHref("p1", made)).toBe("/projects/p1/studio?recipe=r1");
    expect(madeHref("p1", { ...made, kind: "workflow" })).toBe("/projects/p1/workflows/r1");
    expect(madeHref("p1", { ...made, status: "skipped" })).toBeNull();
  });

  it("shows only what did not convert when asked, and never an empty section", () => {
    expect(visibleSections(preview.sections, false).map((s) => s.title)).toEqual(["models/a.sql", "macros/m.sql"]);
    expect(visibleSections(preview.sections, true).map((s) => s.title)).toEqual(["macros/m.sql"]);
  });

  it("writes the report as Markdown", () => {
    const text = reportMarkdown(preview);
    expect(text).toContain("# Converting the dbt project shop");
    expect(text).toContain("- **macro m**: not converted. A macro is code.");
    expect(text).toContain("  - The recipe “a”, step 1: Transform with SQL");
    expect(text).not.toContain("## empty");
  });
});
