import { describe, expect, it } from "vitest";

import type { ContractProblem, ContractTerms } from "@platform/shared-types";

import {
  blankColumn,
  chipWords,
  columnPromise,
  consumerHref,
  consumerKind,
  datasetPromises,
  hoursWords,
  missingPromised,
  problemHeadline,
  statusWords,
  takesRange,
} from "./contract-words";

const terms = (changes: Partial<ContractTerms> = {}): ContractTerms => ({
  columns: [],
  other_columns: "allowed",
  rows_at_least: null,
  rows_at_most: null,
  largest_drop_percent: null,
  new_data_every_hours: null,
  ...changes,
});

const problem = (changes: Partial<ContractProblem>): ContractProblem => ({
  id: "p",
  kind: "new_data",
  outcome: "stopped",
  source_type: "recipe",
  source_id: "r",
  source_name: "Clean orders",
  reasons: [],
  times_seen: 1,
  first_seen_at: "2026-10-15T09:00:00Z",
  last_seen_at: "2026-10-15T09:00:00Z",
  resolved_at: null,
  pipeline_run_id: null,
  contract_version: 1,
  ...changes,
});

/* Data contracts (Phase 19, C1): the words the pages use for them. */
describe("contract words", () => {
  it("says what each column promises in a line", () => {
    expect(columnPromise({ ...blankColumn("id"), kind: "whole_number", always_filled: true, no_repeats: true })).toBe(
      "Whole number, always filled, no repeats",
    );
    expect(columnPromise({ ...blankColumn("status"), kind: "text", allowed_values: ["a", "b"] })).toBe("Text, one of 2 values");
    expect(columnPromise({ ...blankColumn("qty"), kind: "decimal_number", lowest: 0.5, highest: 10 })).toBe(
      "Decimal number, between 0.5 and 10",
    );
    expect(columnPromise({ ...blankColumn("qty"), lowest: 1 })).toBe("Any, at least 1");
  });

  it("says what the dataset as a whole promises", () => {
    expect(datasetPromises(terms())).toEqual(["New columns may appear without breaking it."]);
    expect(
      datasetPromises(
        terms({ rows_at_least: 1, rows_at_most: 1000, largest_drop_percent: 20, new_data_every_hours: 24, other_columns: "not_allowed" }),
      ),
    ).toEqual([
      "Between 1 and 1,000 rows.",
      "No more than 20% fewer rows than the data before.",
      "New data at least every 1 day.",
      "Only the promised columns; a new column breaks it.",
    ]);
    expect(datasetPromises(terms({ rows_at_least: 1 }))[0]).toBe("At least 1 row.");
    expect(hoursWords(6)).toBe("6 hours");
    expect(hoursWords(1.5)).toBe("1.5 hours");
    expect(hoursWords(48)).toBe("2 days");
  });

  it("names its state, and only numbers take a range", () => {
    expect(statusWords("broken")).toEqual({ word: "Broken", tone: "danger" });
    expect(statusWords("not_checked").word).toBe("Not checked yet");
    expect(chipWords("kept")).toBe("Contract kept");
    expect(takesRange("text")).toBe(false);
    expect(takesRange("whole_number")).toBe(true);
  });

  it("says what each problem was, from where", () => {
    expect(problemHeadline(problem({}))).toBe("The recipe Clean orders made data that breaks it, so the data was not saved.");
    expect(problemHeadline(problem({ outcome: "let_through", source_type: "import", source_name: "Shop" }))).toBe(
      "The import Shop made data that breaks it. It was saved, because the contract is set to warn.",
    );
    expect(problemHeadline(problem({ outcome: "let_through", source_type: "check", source_name: null }))).toBe(
      "The current data breaks it.",
    );
    expect(problemHeadline(problem({ kind: "overdue", outcome: "overdue", source_type: null }))).toBe("New data is overdue.");
    expect(problemHeadline(problem({ outcome: "let_through", source_type: "rollback", source_name: null }))).toBe(
      "Rolling back made data that breaks it. It was saved, because the contract is set to warn.",
    );
  });

  it("names and links what relies on a dataset", () => {
    expect(consumerKind("delivery", 2)).toBe("Scheduled deliveries");
    expect(consumerHref("p1", { kind: "recipe", id: "r1", name: "x" })).toBe("/projects/p1/pipelines/r1");
    expect(consumerHref("p1", { kind: "dashboard", id: "d1", name: "x" })).toBe("/projects/p1/dashboards/d1");
  });

  it("finds promised columns a result no longer has", () => {
    const promised = terms({ columns: [blankColumn("id"), blankColumn("email"), blankColumn("status")] });
    expect(missingPromised(promised, ["id", "status", "extra"])).toEqual(["email"]);
  });
});
