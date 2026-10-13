import { describe, expect, it } from "vitest";

import { planPhrase, previewScope } from "@/features/studio/studio-words";

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
});
