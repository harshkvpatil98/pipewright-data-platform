/**
 * A workflow run's task counts in words, for the run history and the toast
 * when a run ends: "2 done · 1 failed", not "2✓ 1✗ 0⤳" (A7).
 */
export function taskCounts(run: { nodes_succeeded: number; nodes_failed: number; nodes_skipped: number }): string {
  const parts = [
    run.nodes_succeeded ? `${run.nodes_succeeded} done` : null,
    run.nodes_failed ? `${run.nodes_failed} failed` : null,
    run.nodes_skipped ? `${run.nodes_skipped} skipped` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "No task finished";
}
