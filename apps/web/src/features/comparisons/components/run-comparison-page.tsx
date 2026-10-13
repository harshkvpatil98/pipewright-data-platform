"use client";

import Link from "next/link";

import type { AuthUser, RunComparisonSummary } from "@platform/shared-types";
import { Badge, buttonClassName, SectionPanel, StatTile, StatusBadge } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { formatNumber } from "@/lib/format";
import { recipeHref } from "@/lib/navigation";
import { formatRunTypeLabel } from "@/lib/run-labels";

type RunComparisonPageProps = {
  currentUser: AuthUser;
  projectId: string;
  comparison: RunComparisonSummary;
};

/** A run's input beside its result: how many rows and columns went in and came out. */
export function RunComparisonPageView({ currentUser, projectId, comparison }: RunComparisonPageProps) {
  const rowsChanged =
    comparison.row_count_before !== null && comparison.row_count_after !== null
      ? comparison.row_count_after - comparison.row_count_before
      : null;
  return (
    <AppShell
      currentUser={currentUser}
      title="Before and after"
      subtitle="How many rows and columns went into this run, and how many came out."
      actions={
        <Link href={`/projects/${projectId}/runs/${comparison.run_id}/audit`} className={buttonClassName("secondary", "md")}>
          Back to the run
        </Link>
      }
      meta={
        <>
          <StatusBadge value={comparison.status} />
          <Badge>{formatRunTypeLabel(comparison.run_type)}</Badge>
          {!comparison.summary_available ? <Badge tone="warning">Some counts were not recorded</Badge> : null}
        </>
      }
    >
      <section className="grid gap-4 md:grid-cols-4">
        <StatTile label="Rows in" value={formatNumber(comparison.row_count_before)} />
        <StatTile
          label="Rows out"
          value={formatNumber(comparison.row_count_after)}
          caption={rowsChanged === null || rowsChanged === 0 ? undefined : `${rowsChanged > 0 ? "+" : ""}${formatNumber(rowsChanged)}`}
        />
        <StatTile label="Columns in" value={formatNumber(comparison.column_count_before)} />
        <StatTile label="Columns out" value={formatNumber(comparison.column_count_after)} />
      </section>

      <SectionPanel title="What changed">
        {comparison.comparison_notes.length === 0 ? (
          <p className="text-[14px] text-ink-3">Nothing worth pointing out.</p>
        ) : (
          <ul className="list-inside list-disc space-y-1 text-[14px] text-ink">
            {comparison.comparison_notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        )}
      </SectionPanel>

      <SectionPanel title="Datasets">
        <dl className="grid gap-3 text-[14px] sm:grid-cols-3">
          <div>
            <dt className="text-[12px] text-muted">Input</dt>
            <dd className="mt-0.5">
              {comparison.base_dataset ? (
                <Link href={`/projects/${projectId}/datasets/${comparison.base_dataset.id}`} className="text-accent hover:underline">
                  {comparison.base_dataset.name || "Unnamed dataset"}
                </Link>
              ) : (
                <span className="text-ink-3">Not recorded</span>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-[12px] text-muted">Result</dt>
            <dd className="mt-0.5">
              {comparison.derived_dataset ? (
                <Link href={`/projects/${projectId}/datasets/${comparison.derived_dataset.id}`} className="text-accent hover:underline">
                  {comparison.derived_dataset.name || "Unnamed dataset"}
                </Link>
              ) : (
                <span className="text-ink-3">Not recorded</span>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-[12px] text-muted">Recipe</dt>
            <dd className="mt-0.5">
              {comparison.pipeline_id ? (
                <Link href={recipeHref(projectId, comparison.pipeline_id)} className="text-accent hover:underline">
                  Open the recipe
                  {comparison.step_count !== null ? ` (${comparison.step_count} step${comparison.step_count === 1 ? "" : "s"})` : ""}
                </Link>
              ) : (
                <span className="text-ink-3">None</span>
              )}
            </dd>
          </div>
        </dl>
      </SectionPanel>
    </AppShell>
  );
}
