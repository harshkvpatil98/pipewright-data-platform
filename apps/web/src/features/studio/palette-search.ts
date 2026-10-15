import { STEP_BY_TYPE, STEP_CATALOG, type StepDefinition } from "@/features/studio/step-catalog";
import { queryWords, scoreTools, type Tool } from "@/features/studio/tools/tool-catalogue";

/** A built-in step, ranked by the same rule as the tools. */
function asTool(step: StepDefinition): Tool {
  const keywords = step.keywords ?? "";
  return {
    name: step.type,
    title: step.label,
    category: step.group,
    summary: step.summary,
    // Each word, and the whole list, so a phrase in it ("anti join") counts as one.
    synonyms: [...keywords.split(" "), keywords],
    accepts: "any",
    column_scoped: false,
    params: [],
    example: { rows: [], params: {}, column: null, output: null, expect: [], note: "" },
  };
}

export function scoreSteps(query: string): { step: StepDefinition; score: number }[] {
  return scoreTools(STEP_CATALOG.map(asTool), query).map(({ tool, score }) => ({
    step: STEP_BY_TYPE.get(tool.name)!,
    score,
  }));
}

/** Built-in steps ranked against a query by the same rule as the tools. */
export function rankSteps(query: string): StepDefinition[] {
  if (queryWords(query).length === 0) return STEP_CATALOG;
  return scoreSteps(query).map((entry) => entry.step);
}

/**
 * Whether the steps lead the palette's results for a query: when the best
 * step matches at least as well as the best tool. Otherwise the tools do, so
 * "lookup" opens on Look up values, not on a join that happens to mention it.
 */
export function stepsLead(query: string, tools: Tool[]): boolean {
  const step = scoreSteps(query)[0]?.score ?? 0;
  const tool = scoreTools(tools, query)[0]?.score ?? 0;
  return step > 0 && step >= tool;
}

/** What the palette shows first for a query. */
export function firstMatch(
  query: string,
  tools: Tool[],
): { kind: "step"; step: StepDefinition } | { kind: "tool"; tool: Tool } | null {
  const step = scoreSteps(query)[0];
  const tool = scoreTools(tools, query)[0];
  if (step && (!tool || step.score >= tool.score)) return { kind: "step", step: step.step };
  return tool ? { kind: "tool", tool: tool.tool } : null;
}

/**
 * What can be done to the open step, as commands (Ctrl+K): "disable a step"
 * is a thing people search for, and the answer is the step's power button.
 */
export const STEP_COMMANDS = [
  {
    id: "studio:turn",
    label: "Turn the open step off or on",
    icon: "power",
    keywords: "disable a step enable skip deactivate turn off turn on",
  },
  {
    id: "studio:duplicate",
    label: "Duplicate the open step",
    icon: "copy",
    keywords: "copy clone duplicate a step",
  },
  {
    id: "studio:group",
    label: "Group the open step with the next",
    icon: "list",
    keywords: "macro group steps together",
  },
] as const;

export type StepCommandId = (typeof STEP_COMMANDS)[number]["id"];
