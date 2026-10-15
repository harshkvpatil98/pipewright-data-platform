import { describe, expect, it } from "vitest";

import { anchorFor, anchorMatches, anchorWords } from "./thread-words";

/* Threads on a dataset's cells (C2). */
describe("naming a cell", () => {
  const row = { order_id: 1004, amount: 1200 };

  it("names a row by its identifier when there is one, and finds it again", () => {
    const anchor = anchorFor({ column: "amount", row, index: 3, identifier: "order_id", version: 2 });
    expect(anchorWords(anchor)).toBe("On amount, the row with order_id 1004");
    // A new version moved the row; its identifier still finds it.
    expect(anchorMatches(anchor, { column: "amount", row, index: 9, version: 5 })).toBe(true);
    expect(anchorMatches(anchor, { column: "order_id", row, index: 9, version: 5 })).toBe(false);
  });

  it("names a row by its number in one version when there is no identifier", () => {
    const anchor = anchorFor({ column: "amount", row, index: 3, identifier: null, version: 2 });
    expect(anchorWords(anchor)).toBe("On amount, row 4 of version 2");
    expect(anchorMatches(anchor, { column: "amount", row, index: 3, version: 2 })).toBe(true);
    // In another version row 4 is another row.
    expect(anchorMatches(anchor, { column: "amount", row, index: 3, version: 3 })).toBe(false);
  });

  it("falls back to the row's number when its identifier is empty", () => {
    expect(anchorFor({ column: "a", row: { order_id: null }, index: 0, identifier: "order_id", version: 1 }).row_number).toBe(1);
  });
});
