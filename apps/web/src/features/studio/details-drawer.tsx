"use client";

import { useEffect, useState } from "react";

import { Icon } from "@/components/ui/icon";
import { RecipeYamlPanel } from "@/features/studio/recipe-yaml-panel";
import { DiscussionPanel } from "@/features/team/components/discussion-panel";
import { typeLabel } from "@/lib/labels";
import { cx } from "@/lib/utils";

export type ExecutionPlan = {
  source_type: string;
  surface: string;
  pushed_steps: number;
  local_steps: number;
  sql?: string | null;
  placements: { node: string; pushed: boolean; reason: string }[];
  note?: string;
  rewrites?: string[];
};

type Tab = "columns" | "runs" | "file" | "comments";

type DetailsDrawerProps = {
  open: boolean;
  onClose: () => void;
  columns: { name: string; inferred_type: string; canonical_type?: string | null }[];
  plan: ExecutionPlan | null;
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
export function DetailsDrawer({ open, onClose, columns, plan, steps, onApplyFile, discussion }: DetailsDrawerProps) {
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
      <div role="tablist" className="flex shrink-0 gap-0.5 overflow-x-auto border-b border-line px-2">
        {(
          [
            ["columns", "Columns"],
            ["runs", "Where it runs"],
            ["file", "File"],
            ["comments", "Comments"],
          ] as [Tab, string][]
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={cx(
              "relative h-10 shrink-0 whitespace-nowrap px-2 text-[13px] transition",
              tab === id ? "font-medium text-ink" : "text-ink-3 hover:text-ink",
            )}
          >
            {label}
            {tab === id ? (
              <span className="absolute inset-x-2 bottom-0 h-[2px] rounded-full bg-[color:var(--accent)]" aria-hidden="true" />
            ) : null}
          </button>
        ))}
      </div>

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

        {tab === "runs" ? <PlanDetail plan={plan} /> : null}

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

function PlanDetail({ plan }: { plan: ExecutionPlan | null }) {
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
            <span
              className={cx(
                "mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[12px]",
                placement.pushed ? "bg-success-soft text-success" : "bg-surface-2 text-ink-3",
              )}
            >
              {placement.pushed ? "In source" : "Here"}
            </span>
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
    </div>
  );
}
