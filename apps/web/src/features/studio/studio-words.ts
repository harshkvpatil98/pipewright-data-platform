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

/** An estimate as a rough figure: whole below 1,000, three significant figures above ("2,090"). */
export function roughCount(value: number): string {
  const rounded = Math.round(value);
  if (rounded < 1000) return formatCount(rounded);
  const scale = 10 ** (String(rounded).length - 3);
  return formatCount(Math.round(rounded / scale) * scale);
}

/**
 * How the estimates compare with the rows the preview counted, in one
 * sentence: the furthest one off, and how many could only be guessed.
 */
export function estimateSummary(pairs: { expected: number; actual: number; guessed: boolean }[]): string | null {
  if (pairs.length === 0) return null;
  const known = pairs.filter((pair) => !pair.guessed);
  const guessed = pairs.length - known.length;
  if (known.length === 0) return "Every figure is a guess: there are no statistics to estimate from.";
  const worst = Math.max(...known.map((pair) => Math.abs(pair.expected - pair.actual) / Math.max(pair.actual, 1)));
  const lead =
    worst < 0.005
      ? "Every estimate matched the rows counted."
      : worst <= 1
        ? `Every estimate was within ${Math.max(1, Math.round(worst * 100))}% of the rows counted.`
        : "At least one estimate was more than double the rows counted.";
  return guessed > 0 ? `${lead} ${countOf(guessed, "step")} could only be guessed.` : lead;
}
