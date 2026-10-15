import { describe, expect, it } from "vitest";

import { estimateSummary, planPhrase, previewScope, roughCount } from "@/features/studio/studio-words";

const plan = (pushed: number, local: number) => ({
  source_type: "PostgreSQL",
  surface: "sql",
  pushed_steps: pushed,
  local_steps: local,
  placements: [],
});

describe("studio words", () => {
  it("says where a recipe runs in one phrase", () => {
    expect(planPhrase(null)).toBeNull();
    expect(planPhrase(plan(1, 3))).toBe("Runs here");
    expect(planPhrase(plan(3, 1))).toBe("3 of 4 steps run in PostgreSQL");
  });

  it("says whether the preview is all of the result", () => {
    expect(previewScope(49, 49)).toBe("All 49 rows");
    expect(previewScope(1, 1)).toBe("All 1 row");
    expect(previewScope(50, 1234)).toBe("First 50 of 1,234 rows");
  });

  it("rounds an estimate the way it is meant", () => {
    expect(roughCount(7.4)).toBe("7");
    expect(roughCount(999.6)).toBe("1,000");
    expect(roughCount(2087.3)).toBe("2,090");
    expect(roughCount(1_234_567)).toBe("1,230,000");
  });

  it("sums up how close the estimates came", () => {
    expect(estimateSummary([])).toBeNull();
    expect(estimateSummary([{ expected: 100, actual: 100, guessed: false }])).toBe("Every estimate matched the rows counted.");
    expect(
      estimateSummary([
        { expected: 2100, actual: 2000, guessed: false },
        { expected: 90, actual: 100, guessed: false },
        { expected: 1000, actual: 10, guessed: true },
      ]),
    ).toBe("Every estimate was within 10% of the rows counted. 1 step could only be guessed.");
    expect(estimateSummary([{ expected: 500, actual: 100, guessed: false }])).toBe(
      "At least one estimate was more than double the rows counted.",
    );
    expect(estimateSummary([{ expected: 1000, actual: 3, guessed: true }])).toBe(
      "Every figure is a guess: there are no statistics to estimate from.",
    );
  });
});
