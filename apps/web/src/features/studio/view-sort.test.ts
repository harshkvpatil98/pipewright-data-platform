import { describe, expect, it } from "vitest";

import { sortForView } from "@/features/studio/view-sort";

const rows = [
  { name: "item 10", amount: 5 },
  { name: "Item 2", amount: null },
  { name: "item 1", amount: 12 },
  { name: "", amount: 3 },
];

describe("sortForView", () => {
  it("leaves the rows alone with no sort", () => {
    expect(sortForView(rows, null)).toBe(rows);
  });

  it("compares numbers as numbers and keeps empty values last", () => {
    expect(sortForView(rows, { column: "amount", direction: "asc" }).map((row) => row.amount)).toEqual([
      3, 5, 12, null,
    ]);
    expect(sortForView(rows, { column: "amount", direction: "desc" }).map((row) => row.amount)).toEqual([
      12, 5, 3, null,
    ]);
  });

  it("reads text the way people do", () => {
    expect(sortForView(rows, { column: "name", direction: "asc" }).map((row) => row.name)).toEqual([
      "item 1",
      "Item 2",
      "item 10",
      "",
    ]);
  });

  it("does not change the rows it was given", () => {
    const copy = rows.map((row) => ({ ...row }));
    sortForView(rows, { column: "amount", direction: "asc" });
    expect(rows).toEqual(copy);
  });

  it("keeps equal values in their original order", () => {
    const tied = [
      { id: 1, group: "a" },
      { id: 2, group: "a" },
      { id: 3, group: "a" },
    ];
    expect(sortForView(tied, { column: "group", direction: "desc" }).map((row) => row.id)).toEqual([1, 2, 3]);
  });
});
