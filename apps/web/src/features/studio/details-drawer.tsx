"use client";

import { useEffect, useState } from "react";

import { RecipeYamlPanel } from "@/features/studio/recipe-yaml-panel";
import { STEP_BY_TYPE } from "@/features/studio/step-catalog";
import { estimateSummary, roughCount } from "@/features/studio/studio-words";
import { DiscussionPanel } from "@/features/team/components/discussion-panel";
import { formatCount } from "@/lib/format";
import { typeLabel } from "@/lib/labels";
import { Badge, Icon, Tabs } from "@platform/shared-ui";

export type ExecutionPlan = {
  source_type: string;
  surface: string;
  pushed_steps: number;
  local_steps: number;
  sql?: string | null;
  placements: { node: string; pushed: boolean; reason: string }[];
  note?: string;
  rewrites?: string[];
  /** Expected rows after each step, from the data's statistics, and how each was worked out. */
  estimates?: { index: number; step_type: string; rows: number; how: string; guessed: boolean }[];
};

/** The rows each step gave in the preview, which reads every stored row. */
type Counted = { index: number; rows_after: number }[];

type Tab = "columns" | "runs" | "file" | "comments";

type DetailsDrawerProps = {
  open: boolean;
  onClose: () => void;
  columns: { name: string; inferred_type: string; canonical_type?: string | null }[];
  plan: ExecutionPlan | null;
  counted?: Counted;
  steps: { step_type: string; config: Record<string, unknown> }[];
  onApplyFile: (steps: { step_type: string; config: Record<string, unknown> }[]) => void;
  /** Comments are kept with a saved recipe; a new one has nowhere to keep them yet. */
  discussion: { projectId: string; recipeId: string; currentUsername: string } | null;
};

/**
 * What most people never need and some need every time: the result's
 * columns and types, where a full run does its work, and the recipe as a
 * file. Closed until asked for, so the grid keeps the room.
 */
export function DetailsDrawer({
  open,
  onClose,
  columns,
  plan,
  counted,
  steps,
  onApplyFile,
  discussion,
}: DetailsDrawerProps) {
  const [tab, setTab] = useState<Tab>("columns");

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <aside
      aria-label="Details"
      // Beside the preview on a wide screen; over it otherwise, so opening
      // Details never squeezes the grid to a sliver.
      className="absolute inset-y-0 right-0 z-20 flex w-[360px] max-w-full flex-col border-l border-line bg-[color:var(--panel)] shadow-[var(--shadow-lg)] 2xl:static 2xl:z-auto 2xl:shrink-0 2xl:shadow-none"
    >
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-line pl-4 pr-2">
        <h2 className="text-[14px] font-semibold text-ink">Details</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close details"
          className="rounded-lg p-1.5 text-muted transition hover:bg-surface-2 hover:text-ink"
        >
          <Icon name="close" size={15} />
        </button>
      </div>
      <Tabs<Tab>
        label="Recipe details"
        className="shrink-0 px-2"
        value={tab}
        onChange={setTab}
        items={[
          { id: "columns", label: "Columns" },
          { id: "runs", label: "Where it runs" },
          { id: "file", label: "File" },
          { id: "comments", label: "Comments" },
        ]}
      />

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {tab === "columns" ? (
          columns.length === 0 ? (
            <p className="text-[13px] text-muted">The columns appear once the preview has loaded.</p>
          ) : (
            <ul className="space-y-1">
              {columns.map((column) => (
                <li
                  key={column.name}
                  className="flex items-center justify-between gap-2 rounded-lg bg-surface px-2.5 py-2"
                >
                  <span className="truncate text-[13px] text-ink">{column.name}</span>
                  <span
                    className="shrink-0 text-[12px] text-muted"
                    title={column.canonical_type ?? column.inferred_type}
                  >
                    {typeLabel(column.canonical_type ?? column.inferred_type)}
                  </span>
                </li>
              ))}
            </ul>
          )
        ) : null}

        {tab === "runs" ? <PlanDetail plan={plan} counted={counted} /> : null}

        {tab === "comments" ? (
          discussion ? (
            <DiscussionPanel
              bare
              projectId={discussion.projectId}
              targetType="pipeline"
              targetId={discussion.recipeId}
              currentUsername={discussion.currentUsername}
              description="Why a step is there, what a filter is for, what to check before changing it. Mention someone with @ and they are notified."
            />
          ) : (
            <p className="text-[13px] text-muted">Save the recipe to leave comments on it.</p>
          )
        ) : null}

        {tab === "file" ? (
          <div className="flex h-full min-h-[320px] flex-col">
            <RecipeYamlPanel steps={steps} onApply={onApplyFile} />
          </div>
        ) : null}
      </div>
    </aside>
  );
}

function PlanDetail({ plan, counted }: { plan: ExecutionPlan | null; counted?: Counted }) {
  if (!plan) {
    return <p className="text-[13px] text-muted">Shown once the preview has loaded.</p>;
  }
  const pushes = plan.pushed_steps > 1;
  const rewrites = plan.rewrites ?? [];
  return (
    <div className="space-y-3 text-[13px]">
      <p className="leading-5 text-ink">
        {pushes
          ? `When the recipe runs, ${plan.pushed_steps} steps run inside ${plan.source_type} and the rest here.`
          : `When the recipe runs, every step runs here, because a ${plan.source_type} source cannot run them itself.`}{" "}
        <span className="text-ink-3">The preview always reads the stored copy of the data.</span>
      </p>
      {plan.note ? <p className="text-ink-3">{plan.note}</p> : null}
      {rewrites.length > 0 ? (
        <div className="rounded-lg border border-line bg-sunken px-3 py-2">
          <p className="text-ink">Rewritten first, without changing the result.</p>
          <p className="text-[12px] text-ink-3">Each rewrite is tested to give the same answer on both engines.</p>
          <ul className="mt-1.5 space-y-0.5 text-[12px] text-ink-3">
            {rewrites.map((entry, index) => (
              <li key={`${entry}-${index}`}>{entry}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <ul className="space-y-1.5">
        {plan.placements.map((placement, index) => (
          <li key={`${placement.node}-${index}`} className="flex items-start gap-2">
            <Badge tone={placement.pushed ? "success" : "neutral"} className="mt-0.5 shrink-0">
              {placement.pushed ? "In source" : "Here"}
            </Badge>
            <span className="min-w-0">
              <span className="text-ink">{placement.node}</span>
              <span className="text-ink-3">: {placement.reason}</span>
            </span>
          </li>
        ))}
      </ul>
      {plan.sql ? (
        <div>
          <p className="mb-1 text-[12px] font-medium text-ink-3">SQL sent to {plan.source_type}</p>
          <pre className="overflow-x-auto rounded-lg bg-sunken p-2.5 text-[12px] leading-5 text-ink-2">{plan.sql}</pre>
        </div>
      ) : null}
      <RowsAtEachStep estimates={plan.estimates ?? []} counted={counted ?? []} />
    </div>
  );
}

/**
 * What the planner expected each step to give, beside what it gave. A run
 * against a database is planned from estimates like these, so seeing how
 * close they come here says how far to trust the plan there.
 */
function RowsAtEachStep({ estimates, counted }: { estimates: NonNullable<ExecutionPlan["estimates"]>; counted: Counted }) {
  if (estimates.length === 0) return null;
  const actual = new Map(counted.map((entry) => [entry.index, entry.rows_after]));
  const pairs = estimates
    .filter((estimate) => actual.has(estimate.index))
    .map((estimate) => ({ expected: estimate.rows, actual: actual.get(estimate.index) ?? 0, guessed: estimate.guessed }));
  const summary = estimateSummary(pairs);
  return (
    <div className="border-t border-line pt-3">
      <p className="font-medium text-ink">Rows at each step</p>
      <p className="text-[12px] text-ink-3">Expected from the data&apos;s statistics, beside what the preview counted.</p>
      {summary ? <p className="mt-1 text-[12px] text-ink-2">{summary}</p> : null}
      <ul className="mt-2 space-y-2">
        {estimates.map((estimate) => {
          const rows = actual.get(estimate.index);
          return (
            <li key={estimate.index} className="flex items-start justify-between gap-3">
              <span className="min-w-0">
                <span className="block text-ink">
                  {estimate.index + 1}. {STEP_BY_TYPE.get(estimate.step_type)?.label ?? "Tool step"}
                </span>
                <span className="block text-[12px] text-ink-3">{estimate.how}</span>
              </span>
              <span className="shrink-0 text-right tabular-nums">
                <span className="block text-ink">{rows === undefined ? "--" : formatCount(rows)}</span>
                <span className="block text-[12px] text-ink-3">
                  {estimate.guessed ? "guessed" : "expected"} {roughCount(estimate.rows)}
                </span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
