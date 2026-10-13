import { describe, expect, it } from "vitest";

import { record, redo, startHistory, undo } from "@/features/studio/recipe-history";

describe("recipe history", () => {
  it("undoes and redoes in order", () => {
    let history = startHistory<string[]>([]);
    history = record(history, ["trim"], { now: 0 });
    history = record(history, ["trim", "sort"], { now: 5000 });
    history = undo(history);
    expect(history.present).toEqual(["trim"]);
    history = undo(history);
    expect(history.present).toEqual([]);
    history = redo(history);
    expect(history.present).toEqual(["trim"]);
  });

  it("folds quick changes to the same field into one step", () => {
    let history = startHistory("");
    for (const [index, text] of ["a", "am", "amo", "amount"].entries()) {
      history = record(history, text, { group: "step-1:column", now: index * 200 });
    }
    expect(history.present).toBe("amount");
    expect(undo(history).present).toBe("");
  });

  it("starts a new step after a pause or on another field", () => {
    let history = startHistory("");
    history = record(history, "a", { group: "step-1:column", now: 0 });
    history = record(history, "ab", { group: "step-1:column", now: 3000 });
    history = record(history, "abc", { group: "step-2:column", now: 3100 });
    expect(undo(history).present).toBe("ab");
    expect(undo(undo(history)).present).toBe("a");
  });

  it("drops what could be redone once something new happens", () => {
    let history = startHistory(0);
    history = record(history, 1, { now: 0 });
    history = undo(history);
    history = record(history, 2, { now: 10 });
    expect(history.future).toEqual([]);
    expect(redo(history).present).toBe(2);
  });

  it("ignores a change that changes nothing, and undo with nothing to undo", () => {
    const history = startHistory(["trim"]);
    expect(record(history, history.present)).toBe(history);
    expect(undo(history)).toBe(history);
    expect(redo(history)).toBe(history);
  });

  it("never folds an undone state into the next edit", () => {
    let history = startHistory("");
    history = record(history, "a", { group: "f", now: 0 });
    history = undo(history);
    history = record(history, "b", { group: "f", now: 100 });
    expect(undo(history).present).toBe("");
  });
});
