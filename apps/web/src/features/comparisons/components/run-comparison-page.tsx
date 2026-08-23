"use client";

import Link from "next/link";

import type { AuthUser, RunComparisonSummary } from "@platform/shared-types";
import { SectionPanel, StatCard, StatusBadge } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { formatNumber } from "@/lib/format";
import { formatRunTypeLabel } from "@/lib/run-labels";

type RunComparisonPageProps = {
  currentUser: AuthUser;
  projectId: string;
  comparison: RunComparisonSummary;
};

export function RunComparisonPageView({ currentUser, projectId, comparison }: RunComparisonPageProps) {
  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Testing lab"
      title="Run comparison"
      subtitle="Before/after metrics from persisted pipeline run summary_json (transformation runs have the richest view)."
      actions={
        <div className="flex flex-wrap gap-2">
          <Link
            href={`/projects/${projectId}/runs/${comparison.run_id}/audit`}
            className="rounded-full border border-line bg-surface px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-ink hover:border-line-strong"
          >
            Run audit
          </Link>
          <Link
            href={`/projects/${projectId}`}
            className="rounded-full border border-line bg-surface px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-ink hover:border-line-strong"
          >
            Project
          </Link>
        </div>
      }
      meta={
        <>
          <StatusBadge value={comparison.status} />
          <span className="rounded-full border border-line bg-surface px-3 py-1 text-xs uppercase tracking-[0.18em] text-ink-2">
            {formatRunTypeLabel(comparison.run_type)}
          </span>
          {!comparison.summary_available ? (
            <span className="rounded-full border border-warning-line bg-warning-soft px-3 py-1 text-xs uppercase tracking-[0.18em] text-warning">
              Partial summary
            </span>
          ) : null}
        </>
      }
    >
      <section className="grid gap-4 md:grid-cols-4">
        <StatCard
          label="Rows before"
          value={formatNumber(comparison.row_count_before)}
          caption="From run summary when available."
        />
        <StatCard
          label="Rows after"
          value={formatNumber(comparison.row_count_after)}
          caption="From run summary when available."
        />
        <StatCard
          label="Columns before"
          value={formatNumber(comparison.column_count_before)}
          caption="Transformation summaries."
        />
        <StatCard
          label="Columns after"
          value={formatNumber(comparison.column_count_after)}
          caption="Transformation summaries."
        />
      </section>

      <SectionPanel title="Comparison notes" description="Derived from run type and summary_json.">
        {comparison.comparison_notes.length === 0 ? (
          <p className="text-sm text-ink-3">No notes.</p>
        ) : (
          <ul className="list-inside list-disc space-y-1 text-sm text-ink">
            {comparison.comparison_notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
        {!comparison.raw_summary_present ? (
          <p className="mt-3 text-sm text-muted">No summary_json stored on this run.</p>
        ) : null}
      </SectionPanel>

      <div className="grid gap-6 lg:grid-cols-2">
        <SectionPanel title="Linked datasets" description="IDs from transformation summary when present.">
          <dl className="space-y-3 text-sm">
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Base dataset</dt>
              <dd className="mt-1">
                {comparison.base_dataset ? (
                  <Link
                    href={`/projects/${projectId}/datasets/${comparison.base_dataset.id}`}
                    className="text-accent hover:text-accent"
                  >
                    {comparison.base_dataset.name || comparison.base_dataset.id}
                  </Link>
                ) : (
                  <span className="text-ink-3">—</span>
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Derived dataset</dt>
              <dd className="mt-1">
                {comparison.derived_dataset ? (
                  <Link
                    href={`/projects/${projectId}/datasets/${comparison.derived_dataset.id}`}
                    className="text-accent hover:text-accent"
                  >
                    {comparison.derived_dataset.name || comparison.derived_dataset.id}
                  </Link>
                ) : (
                  <span className="text-ink-3">—</span>
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Pipeline id</dt>
              <dd className="mt-1 font-mono text-xs text-ink-2">
                {comparison.pipeline_id ? (
                  <Link
                    href={`/projects/${projectId}/pipelines/${comparison.pipeline_id}`}
                    className="text-accent hover:text-accent"
                  >
                    {comparison.pipeline_id}
                  </Link>
                ) : (
                  "—"
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Steps (summary)</dt>
              <dd className="mt-1 text-ink">{formatNumber(comparison.step_count)}</dd>
            </div>
          </dl>
        </SectionPanel>

        <SectionPanel title="Summary availability" description="Whether before/after metrics are complete.">
          <p className="text-sm text-ink-2">
            Full transformation before/after:{" "}
            <span className={comparison.summary_available ? "text-success" : "text-muted"}>
              {comparison.summary_available ? "Yes" : "No"}
            </span>
          </p>
          <p className="mt-2 text-xs text-muted">
            Statistical significance testing is not part of this view; this is persisted metadata only.
          </p>
        </SectionPanel>
      </div>
    </AppShell>
  );
}
