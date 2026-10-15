import { describe, expect, it } from "vitest";

import { compareRecipes } from "./recipe-diff";

const drop = (columns: string[]) => ({ step_type: "drop_columns", config: { columns } });
const sort = (columns: string[]) => ({ step_type: "sort_rows", config: { columns, ascending: true } });
const dedupe = { step_type: "remove_duplicates", config: {} };

/* What a suggested change does to a recipe (C2), as the reviewer reads it. */
describe("comparing two versions of a recipe", () => {
  it("names what was added, removed, changed and moved", () => {
    const changes = compareRecipes(
      { name: "Clean", steps: [drop(["email"]), sort(["amount"]), dedupe] },
      { name: "Clean orders", steps: [dedupe, drop(["email", "phone"]), sort(["amount"]), { step_type: "limit_rows", config: { n: 10 } }] },
    );
    expect(changes.map((change) => change.kind)).toEqual(["renamed", "changed", "moved", "added"]);
    expect(changes[0].text).toBe("Renames it to “Clean orders”.");
    expect(changes[1].text).toMatch(/^Changes step 2 from “Remove columns/);
    expect(changes[2].text).toMatch(/^Moves “Remove duplicates.*” from step 3 to step 1\.$/);
    expect(changes[3].text).toMatch(/^Adds step 4, “/);
  });

  it("says nothing about a recipe that did not change", () => {
    expect(compareRecipes({ name: "A", steps: [dedupe] }, { name: "A", steps: [dedupe] })).toEqual([]);
  });

  it("names a removed step by its place", () => {
    const [change] = compareRecipes({ name: "A", steps: [dedupe, sort(["a"])] }, { name: "A", steps: [dedupe] });
    expect(change.kind).toBe("removed");
    expect(change.text).toMatch(/^Removes step 2, “Sort/);
  });
});

describe("settings written in another order", () => {
  it("are the same settings", () => {
    // Found rehearsing: the shared copy sorts a step's settings, the saved
    // recipe keeps them as written, and a suggestion called them changed.
    expect(
      compareRecipes(
        { name: "A", steps: [{ step_type: "drop_null_rows", config: { how: "any", columns: ["c"] } }] },
        { name: "A", steps: [{ step_type: "drop_null_rows", config: { columns: ["c"], how: "any" } }] },
      ),
    ).toEqual([]);
  });
});
