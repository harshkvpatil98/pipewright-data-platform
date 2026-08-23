import { describe, expect, it } from "vitest";

import {
  cycleSort,
  moveColumn,
  orderColumns,
  sortFromSteps,
  sortStepConfig,
  toggleFreeze,
} from "@/features/studio/grid/column-state";

const columns = ["a", "b", "c", "d"].map((name) => ({ name }));

describe("column order", () => {
  it("leaves columns alone when no order is saved", () => {
    expect(orderColumns(columns, [])).toEqual(columns);
  });

  it("applies a saved order", () => {
    expect(orderColumns(columns, ["c", "a"]).map((c) => c.name)).toEqual(["c", "a", "b", "d"]);
  });

  it("keeps columns the saved order does not mention", () => {
    // A step that adds a column must not make it invisible until somebody
    // updates the saved order.
    expect(orderColumns(columns, ["d"]).map((c) => c.name)).toEqual(["d", "a", "b", "c"]);
  });

  it("ignores a saved name that no longer exists", () => {
    expect(orderColumns(columns, ["gone", "b"]).map((c) => c.name)).toEqual([
      "b",
      "a",
      "c",
      "d",
    ]);
  });
});

describe("moving a column", () => {
  const names = ["a", "b", "c", "d"];

  it("moves right", () => {
    expect(moveColumn([], names, "a", 2)).toEqual(["b", "c", "a", "d"]);
  });

  it("moves left", () => {
    expect(moveColumn([], names, "d", 0)).toEqual(["d", "a", "b", "c"]);
  });

  it("clamps past the ends rather than dropping the column", () => {
    expect(moveColumn([], names, "a", 99)).toEqual(["b", "c", "d", "a"]);
    expect(moveColumn([], names, "d", -5)).toEqual(["d", "a", "b", "c"]);
  });

  it("does nothing for a column that is not there", () => {
    expect(moveColumn([], names, "zzz", 0)).toEqual(names);
  });

  it("keeps every column", () => {
    // The bug this guards: splice indices shift after the removal, and an
    // off-by-one loses a column entirely.
    const result = moveColumn([], names, "b", 3);
    expect([...result].sort()).toEqual([...names].sort());
  });
});

describe("sort cycling", () => {
  it("goes ascending, descending, then off", () => {
    // The third state matters: without it there is no way back to the data's
    // own order except by deleting a step by hand.
    let sort = cycleSort(null, "a");
    expect(sort).toEqual({ column: "a", direction: "asc" });
    sort = cycleSort(sort, "a");
    expect(sort).toEqual({ column: "a", direction: "desc" });
    expect(cycleSort(sort, "a")).toBeNull();
  });

  it("starts fresh on a different column", () => {
    const sort = cycleSort({ column: "a", direction: "desc" }, "b");
    expect(sort).toEqual({ column: "b", direction: "asc" });
  });
});

describe("freezing", () => {
  it("freezes up to and including the clicked column", () => {
    expect(toggleFreeze(0, 1)).toBe(2);
  });

  it("unfreezes when clicking the current boundary", () => {
    expect(toggleFreeze(2, 1)).toBe(0);
  });

  it("moves the boundary when clicking elsewhere", () => {
    expect(toggleFreeze(2, 0)).toBe(1);
  });
});

describe("sorting as a step", () => {
  it("produces a sort_rows step the engine understands", () => {
    // A view sort would order the loaded page and present it as the order of
    // the table. A step sorts the whole dataset.
    expect(sortStepConfig({ column: "amount", direction: "desc" })).toEqual({
      step_type: "sort_rows",
      config: { columns: ["amount"], ascending: [false], na_position: "last" },
    });
  });

  it("reads the sort back out of saved steps", () => {
    const steps = [
      { step_type: "filter_rows", config: {} },
      { step_type: "sort_rows", config: { columns: ["amount"], ascending: [false] } },
    ];
    expect(sortFromSteps(steps)).toEqual({ column: "amount", direction: "desc" });
  });

  it("uses the last sort when there are several", () => {
    const steps = [
      { step_type: "sort_rows", config: { columns: ["a"], ascending: [true] } },
      { step_type: "sort_rows", config: { columns: ["b"], ascending: [false] } },
    ];
    expect(sortFromSteps(steps)?.column).toBe("b");
  });

  it("reads a boolean ascending as well as an array", () => {
    const steps = [{ step_type: "sort_rows", config: { columns: ["a"], ascending: false } }];
    expect(sortFromSteps(steps)?.direction).toBe("desc");
  });

  it("reports no sort when there is none", () => {
    expect(sortFromSteps([{ step_type: "limit_rows", config: {} }])).toBeNull();
    expect(sortFromSteps([])).toBeNull();
  });

  it("ignores a malformed sort step rather than crashing", () => {
    expect(sortFromSteps([{ step_type: "sort_rows", config: {} }])).toBeNull();
  });
});
