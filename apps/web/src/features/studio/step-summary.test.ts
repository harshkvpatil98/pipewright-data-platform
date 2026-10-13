import { describe, expect, it } from "vitest";

import { describeStep } from "@/features/studio/step-summary";

describe("describeStep", () => {
  it("names the columns a step works on, briefly", () => {
    expect(describeStep("trim_strings", { columns: ["email"] })).toBe("email");
    expect(describeStep("trim_strings", { columns: ["a", "b", "c", "d"] })).toBe("a, b and 2 more");
  });

  it("puts a filter's first condition in words", () => {
    expect(
      describeStep("filter_rows", {
        conditions: [
          { column: "amount", operator: "greater_than", value: "0" },
          { column: "region", operator: "in", value: ["North", "South"] },
        ],
      }),
    ).toBe("amount is more than 0 and 1 more");
  });

  it("says which way a sort goes", () => {
    expect(describeStep("sort_rows", { columns: ["signup_date"], ascending: false })).toBe(
      "signup_date, Z to A",
    );
    expect(describeStep("sort_rows", { columns: ["name"] })).toBe("name, A to Z");
  });

  it("describes renames and type changes", () => {
    expect(describeStep("rename_columns", { mappings: { cust: "customer" } })).toBe("cust → customer");
    expect(describeStep("cast_column_types", { mappings: { amount: "float", qty: "int" } })).toBe(
      "amount → decimal number and 1 more",
    );
  });

  it("names the other dataset of a join or append", () => {
    const names = new Map([["d2", "customers"]]);
    expect(describeStep("join_datasets", { right_dataset_id: "d2" }, names)).toBe("customers");
    expect(describeStep("union_datasets", { other_dataset_id: "missing" }, names)).toBe("");
  });

  it("returns nothing for a step that is not set up yet", () => {
    expect(describeStep("trim_strings", { columns: [] })).toBe("");
    expect(describeStep("filter_rows", { conditions: [] })).toBe("");
    expect(describeStep("derive_column", { target_column: "" })).toBe("");
    expect(describeStep("something_new", { anything: 1 })).toBe("");
  });

  it("describes dedupe and empty-row removal in words", () => {
    expect(describeStep("remove_duplicates", {})).toBe("whole rows");
    expect(describeStep("remove_duplicates", { subset: ["email"] })).toBe("matching on email");
    expect(describeStep("drop_null_rows", { how: "any", columns: ["email"] })).toBe("empty in email");
    expect(describeStep("drop_null_rows", { how: "any" })).toBe("rows with any empty cell");
    expect(describeStep("drop_null_rows", { how: "all" })).toBe("rows with every cell empty");
  });
});
