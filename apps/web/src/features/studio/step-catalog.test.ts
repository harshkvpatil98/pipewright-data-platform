import { describe, expect, it } from "vitest";

import {
  STEP_BY_TYPE,
  STEP_CATALOG,
  columnKind,
  prefillConfig,
  suggestedFor,
} from "@/features/studio/step-catalog";

const step = (type: string) => STEP_BY_TYPE.get(type)!;

describe("the step catalogue", () => {
  it("names every step in words and gives it something to search by", () => {
    for (const definition of STEP_CATALOG) {
      expect(definition.label, definition.type).toMatch(/^[A-Z][a-z]/);
      expect(definition.keywords, definition.type).toBeTruthy();
    }
  });

  it("labels every option of a select whose stored values are codes", () => {
    for (const definition of STEP_CATALOG) {
      for (const field of definition.fields) {
        if (field.kind !== "select") continue;
        for (const option of field.options ?? []) {
          expect(field.optionLabels?.[option], `${definition.type}.${field.key}.${option}`).toBeTruthy();
        }
      }
    }
  });
});

describe("prefillConfig", () => {
  it("chooses the column a step was started from", () => {
    expect(prefillConfig(step("trim_strings"), "email")).toEqual({ columns: ["email"] });
    expect(prefillConfig(step("replace_values"), "email")).toMatchObject({ column: "email" });
    expect(prefillConfig(step("filter_rows"), "amount")).toEqual({
      conditions: [{ column: "amount", operator: "equals", value: "" }],
    });
    expect(prefillConfig(step("rename_columns"), "cust")).toEqual({ mappings: { cust: "" } });
    expect(prefillConfig(step("remove_duplicates"), "email")).toEqual({ subset: ["email"] });
  });

  it("keeps the defaults when there is no column", () => {
    expect(prefillConfig(step("sort_rows"), null)).toEqual({ columns: [], ascending: true });
  });

  it("does not share the defaults object between steps", () => {
    const config = prefillConfig(step("trim_strings"), null);
    (config.columns as string[]).push("x");
    expect(step("trim_strings").defaults).toEqual({ columns: [] });
  });
});

describe("suggestions by column type", () => {
  it("reads the broad kind of a type", () => {
    expect(columnKind("Int64")).toBe("number");
    expect(columnKind("decimal(18,2)")).toBe("number");
    expect(columnKind("timestamp(6,tz)")).toBe("date");
    expect(columnKind("string")).toBe("text");
    expect(columnKind(undefined)).toBe("other");
  });

  it("offers text cleaning for text and filtering for numbers", () => {
    expect(suggestedFor("string")[0].type).toBe("trim_strings");
    expect(suggestedFor("Int64")[0].type).toBe("filter_rows");
    expect(suggestedFor("string").map((s) => s.type)).toContain("rename_columns");
  });
});
