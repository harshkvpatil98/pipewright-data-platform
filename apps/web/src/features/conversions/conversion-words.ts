/**
 * The words and links of converting work from another tool (E2, X3), kept
 * apart from the page so they are tested on their own.
 */

import type { BadgeTone } from "@platform/shared-ui";

import { countOf } from "@/lib/format";
import { recipeHref } from "@/lib/navigation";

export type ConversionFormat = { key: string; title: string; upload: string; extensions: string[] };

export type ConversionEntry = {
  subject: string;
  status: "converted" | "not converted" | "nothing to do";
  became: string[];
  reason: string | null;
  notes: string[];
};

export type ConversionNeed = {
  key: string;
  name: string;
  what: string;
  columns: string[];
  status: "matched" | "chosen" | "missing";
  dataset_id: string | null;
  dataset_name: string | null;
  reason: string | null;
};

export type ConversionPreview = {
  format: string;
  title: string;
  needs: ConversionNeed[];
  seeds: { key: string; name: string; what: string; file_name: string }[];
  recipes: { key: string; name: string; steps: number; complete: boolean; reads: string; parameters: string[] }[];
  checks: { key: string; name: string; rule_type: string; reads: string }[];
  workflows: { key: string; name: string; tasks: number; trigger_type: string; cron_expression: string | null }[];
  sections: { title: string; entries: ConversionEntry[] }[];
  counts: { converted: number; not_converted: number; nothing_to_do: number };
  notes: string[];
  choices: { id: string; name: string }[];
};

export type ConversionMade = {
  kind: "dataset" | "recipe" | "check" | "workflow";
  key: string;
  name: string;
  status: "made" | "used" | "skipped" | "failed";
  id: string | null;
  detail: string | null;
};

export type ConversionResult = ConversionPreview & { made: ConversionMade[] };

export const STATUS_TONE: Record<ConversionEntry["status"], BadgeTone> = {
  converted: "success",
  "not converted": "warning",
  "nothing to do": "neutral",
};

export const MADE_TONE: Record<ConversionMade["status"], BadgeTone> = {
  made: "success",
  used: "info",
  skipped: "neutral",
  failed: "danger",
};

/** "3 recipes, 2 checks, a workflow and 1 dataset from its data" for what a preview would make. */
export function madeWords(preview: ConversionPreview): string {
  const drafts = preview.recipes.filter((recipe) => !recipe.complete).length;
  const parts = [
    preview.recipes.length ? countOf(preview.recipes.length, "recipe") + (drafts ? ` (${countOf(drafts, "draft")})` : "") : "",
    preview.checks.length ? countOf(preview.checks.length, "check") : "",
    preview.workflows.length ? countOf(preview.workflows.length, "workflow") : "",
    preview.seeds.length ? `${countOf(preview.seeds.length, "dataset")} from its data` : "",
  ].filter(Boolean);
  if (!parts.length) return "Nothing to make";
  return parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

/** "12 parts converted, 3 not and 1 with nothing to do" for a report's counts. */
export function countsWords(counts: ConversionPreview["counts"]): string {
  const parts = [`${countOf(counts.converted, "part")} converted`];
  if (counts.not_converted) parts.push(`${counts.not_converted} not`);
  if (counts.nothing_to_do) parts.push(`${counts.nothing_to_do} with nothing to do`);
  return parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

/** Where what an import made is opened. */
export function madeHref(projectId: string, item: ConversionMade): string | null {
  if (!item.id || item.status === "skipped") return null;
  switch (item.kind) {
    case "recipe":
      return recipeHref(projectId, item.id);
    case "workflow":
      return `/projects/${projectId}/workflows/${item.id}`;
    case "check":
      return `/projects/${projectId}/checks`;
    case "dataset":
      return `/projects/${projectId}/datasets/${item.id}`;
    default:
      return null;
  }
}

/** The sections with something to see under a filter: everything, or only the parts that did not convert. */
export function visibleSections(
  sections: ConversionPreview["sections"],
  onlyProblems: boolean,
): ConversionPreview["sections"] {
  if (!onlyProblems) return sections.filter((section) => section.entries.length);
  return sections
    .map((section) => ({ ...section, entries: section.entries.filter((entry) => entry.status === "not converted") }))
    .filter((section) => section.entries.length);
}

/** The report as Markdown, to keep or send on. */
export function reportMarkdown(preview: ConversionPreview): string {
  const lines = [`# Converting ${preview.title}`, "", `${countsWords(preview.counts)}. It makes ${madeWords(preview).toLowerCase()}.`, ""];
  for (const section of preview.sections) {
    if (!section.entries.length) continue;
    lines.push(`## ${section.title}`, "");
    for (const entry of section.entries) {
      lines.push(`- **${entry.subject}**: ${entry.status}${entry.reason ? `. ${entry.reason}` : ""}`);
      for (const line of entry.became) lines.push(`  - ${line}`);
      for (const note of entry.notes) lines.push(`  - Note: ${note}`);
    }
    lines.push("");
  }
  if (preview.notes.length) lines.push(...preview.notes.map((note) => `_${note}_`));
  return lines.join("\n").trimEnd() + "\n";
}
