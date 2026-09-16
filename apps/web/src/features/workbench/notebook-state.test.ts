import { describe, expect, it } from "vitest";

import {
  type Cell,
  describeCell,
  duplicateNames,
  emptyCell,
  insertAfter,
  moveCell,
  namesAvailableTo,
  removeCell,
  toPayload,
  updateCell,
  validate,
} from "./notebook-state";

function cell(overrides: Partial<Cell> = {}): Cell {
  return { ...emptyCell(), source: "SELECT 1", ...overrides };
}

describe("moveCell", () => {
  it("swaps with the neighbour", () => {
    const cells = [cell({ source: "a" }), cell({ source: "b" })];
    expect(moveCell(cells, 0, 1).map((c) => c.source)).toEqual(["b", "a"]);
  });

  it("does nothing at the edges", () => {
    const cells = [cell({ source: "a" }), cell({ source: "b" })];
    expect(moveCell(cells, 0, -1)).toBe(cells);
    expect(moveCell(cells, 1, 1)).toBe(cells);
  });
});

describe("insertAfter / removeCell / updateCell", () => {
  it("inserts in place", () => {
    const cells = [cell({ source: "a" }), cell({ source: "c" })];
    const next = insertAfter(cells, 0, cell({ source: "b" }));
    expect(next.map((c) => c.source)).toEqual(["a", "b", "c"]);
  });

  it("removes by id", () => {
    const target = cell({ source: "gone" });
    expect(removeCell([cell(), target], target.id)).toHaveLength(1);
  });

  it("updates without touching the others", () => {
    const first = cell({ source: "a" });
    const second = cell({ source: "b" });
    const next = updateCell([first, second], second.id, { source: "changed" });
    expect(next[0].source).toBe("a");
    expect(next[1].source).toBe("changed");
  });
});

describe("namesAvailableTo", () => {
  it("offers only what earlier cells bound", () => {
    const cells = [
      cell({ output_name: "raw" }),
      cell({ output_name: "clean" }),
      cell({ output_name: "final" }),
    ];
    expect(namesAvailableTo(cells, 0)).toEqual([]);
    expect(namesAvailableTo(cells, 1)).toEqual(["raw"]);
    expect(namesAvailableTo(cells, 2)).toEqual(["raw", "clean"]);
  });

  it("ignores cells that bind nothing", () => {
    const cells = [cell({ output_name: null }), cell({ output_name: "x" })];
    expect(namesAvailableTo(cells, 1)).toEqual([]);
  });
});

describe("duplicateNames", () => {
  it("finds a name bound twice", () => {
    const cells = [cell({ output_name: "x" }), cell({ output_name: "x" }), cell({ output_name: "y" })];
    expect(duplicateNames(cells)).toEqual(["x"]);
  });
});

describe("validate", () => {
  it("passes a well-formed notebook", () => {
    const cells = [
      cell({ output_name: "raw" }),
      cell({ kind: "recipe", source: "", config: { input: "raw" }, output_name: "clean" }),
    ];
    expect(validate(cells)).toEqual([]);
  });

  it("catches a recipe reading a name that comes later", () => {
    // The error would otherwise arrive from the engine at run time rather than
    // from the editor while it was being written.
    const cells = [
      cell({ kind: "recipe", source: "", config: { input: "later" } }),
      cell({ output_name: "later" }),
    ];
    const problems = validate(cells);
    expect(problems[0].cell).toBe(0);
    expect(problems[0].message).toContain("not produced before this cell");
  });

  it("catches a recipe with no input", () => {
    expect(validate([cell({ kind: "recipe", source: "" })])[0].message).toContain(
      "which result it transforms",
    );
  });

  it("catches a name that is not an identifier", () => {
    expect(validate([cell({ output_name: "my result" })])[0].message).toContain("cannot be a name");
  });

  it("catches two cells binding the same name", () => {
    const problems = validate([cell({ output_name: "x" }), cell({ output_name: "x" })]);
    expect(problems.some((problem) => problem.message.includes("later one would win"))).toBe(true);
  });

  it("catches an empty cell", () => {
    expect(validate([cell({ source: "  " })])[0].message).toBe("This cell is empty.");
  });

  it("allows an empty markdown cell", () => {
    expect(validate([cell({ kind: "markdown", source: "" })])).toEqual([]);
  });

  it("allows a recipe with no source, because its steps live in config", () => {
    const cells = [cell({ output_name: "raw" }), cell({ kind: "recipe", source: "", config: { input: "raw" } })];
    expect(validate(cells)).toEqual([]);
  });
});

describe("describeCell", () => {
  const result = (overrides = {}) => ({
    position: 0, kind: "sql", ok: true, duration_ms: 12, output_name: null,
    columns: [] as string[], rows: [], row_count: 0, truncated: false,
    stdout: "", error: "", skipped: false, bindings: {}, ...overrides,
  });

  it("says how many rows and where they went", () => {
    expect(describeCell(result({ columns: ["a"], row_count: 3, output_name: "orders" }))).toBe(
      "3 rows · → orders · 12 ms",
    );
  });

  it("says failed rather than counting", () => {
    expect(describeCell(result({ error: "boom" }))).toBe("failed");
  });

  it("says skipped", () => {
    expect(describeCell(result({ skipped: true }))).toBe("skipped");
  });
});

describe("toPayload", () => {
  it("drops the local id and normalises an empty name to null", () => {
    const payload = toPayload([cell({ output_name: "" })]);
    expect(payload[0]).not.toHaveProperty("id");
    expect(payload[0].output_name).toBeNull();
  });
});
