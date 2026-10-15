/**
 * What a suggested change does to a recipe, a sentence per step (C2).
 *
 * Steps that stay the same are found first (the longest run they share);
 * a step that leaves one place and arrives at another unchanged has moved;
 * the nearest added step of the same kind as a removed one is that step,
 * changed;
 * the rest were added or removed.
 */

import { stableJson } from "./coedit";
import { STEP_BY_TYPE } from "./step-catalog";
import { describeStep } from "./step-summary";

export type PlainStep = { step_type: string; config: Record<string, unknown> };

export type RecipeChange = { kind: "added" | "removed" | "changed" | "moved" | "renamed"; text: string };

const signature = (step: PlainStep) => `${step.step_type}|${stableJson(step.config ?? {})}`;

export function stepWords(step: PlainStep): string {
  const label = STEP_BY_TYPE.get(step.step_type)?.label ?? step.step_type.replace(/_/g, " ");
  const detail = STEP_BY_TYPE.has(step.step_type) ? describeStep(step.step_type, step.config ?? {}) : "";
  return detail ? `${label}: ${detail}` : label;
}

/** Index pairs of the longest common subsequence of two lists of keys. */
function common(before: string[], after: string[]): [number, number][] {
  const table = Array.from({ length: before.length + 1 }, () => new Array<number>(after.length + 1).fill(0));
  for (let i = before.length - 1; i >= 0; i -= 1) {
    for (let j = after.length - 1; j >= 0; j -= 1) {
      table[i][j] = before[i] === after[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  const pairs: [number, number][] = [];
  let i = 0;
  let j = 0;
  while (i < before.length && j < after.length) {
    if (before[i] === after[j]) {
      pairs.push([i, j]);
      i += 1;
      j += 1;
    } else if (table[i + 1][j] > table[i][j + 1]) {
      i += 1;
    } else {
      // On a tie, earlier steps keep their places: a step taken to the
      // front reads as that step moving, not everything after it.
      j += 1;
    }
  }
  return pairs;
}

export function compareRecipes(
  before: { name: string; steps: PlainStep[] },
  after: { name: string; steps: PlainStep[] },
): RecipeChange[] {
  const changes: RecipeChange[] = [];
  if (before.name.trim() !== after.name.trim()) {
    changes.push({ kind: "renamed", text: `Renames it to “${after.name.trim()}”.` });
  }
  const pairs = common(before.steps.map(signature), after.steps.map(signature));
  const keptBefore = new Set(pairs.map(([i]) => i));
  const keptAfter = new Set(pairs.map(([, j]) => j));
  const removed = before.steps.map((step, index) => ({ step, index })).filter(({ index }) => !keptBefore.has(index));
  let added = after.steps.map((step, index) => ({ step, index })).filter(({ index }) => !keptAfter.has(index));

  for (const gone of removed) {
    const moved = added.find((item) => signature(item.step) === signature(gone.step));
    if (moved) {
      changes.push({
        kind: "moved",
        text: `Moves “${stepWords(gone.step)}” from step ${gone.index + 1} to step ${moved.index + 1}.`,
      });
      added = added.filter((item) => item !== moved);
      continue;
    }
    // The nearest added step of the same kind is this one, changed.
    const changed = added
      .filter((item) => item.step.step_type === gone.step.step_type)
      .sort((a, b) => Math.abs(a.index - gone.index) - Math.abs(b.index - gone.index))[0];
    if (changed) {
      changes.push({
        kind: "changed",
        text: `Changes step ${changed.index + 1} from “${stepWords(gone.step)}” to “${stepWords(changed.step)}”.`,
      });
      added = added.filter((item) => item !== changed);
      continue;
    }
    changes.push({ kind: "removed", text: `Removes step ${gone.index + 1}, “${stepWords(gone.step)}”.` });
  }
  for (const item of added) {
    changes.push({ kind: "added", text: `Adds step ${item.index + 1}, “${stepWords(item.step)}”.` });
  }
  return changes;
}
