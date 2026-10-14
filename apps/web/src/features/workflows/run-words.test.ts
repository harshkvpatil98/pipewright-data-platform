import { describe, expect, it } from "vitest";

import { taskCounts } from "./run-words";

describe("a run's task counts", () => {
  it("names only what happened", () => {
    expect(taskCounts({ nodes_succeeded: 2, nodes_failed: 1, nodes_skipped: 0 })).toBe("2 done · 1 failed");
    expect(taskCounts({ nodes_succeeded: 0, nodes_failed: 0, nodes_skipped: 3 })).toBe("3 skipped");
  });

  it("says so when the run stopped before any task finished", () => {
    expect(taskCounts({ nodes_succeeded: 0, nodes_failed: 0, nodes_skipped: 0 })).toBe("No task finished");
  });
});
