import type { ExecutionPlan } from "@/features/studio/details-drawer";
import { countOf, formatCount } from "@/lib/format";

/** "Runs here", or "3 of 4 steps run in PostgreSQL": the plan in one phrase. */
export function planPhrase(plan: ExecutionPlan | null): string | null {
  if (!plan) return null;
  // A bare read of the source is not work done there.
  if (plan.pushed_steps <= 1) return "Runs here";
  const total = plan.pushed_steps + plan.local_steps;
  return `${plan.pushed_steps} of ${total} steps run in ${plan.source_type}`;
}

/** "All 49 rows", or "First 50 of 1,234 rows" when the preview is part of the result. */
export function previewScope(shown: number, total: number): string {
  if (shown >= total) return `All ${countOf(total, "row")}`;
  return `First ${formatCount(shown)} of ${countOf(total, "row")}`;
}
