"use client";

import Link from "next/link";
import { useState } from "react";

import type { AuthUser, RunAuditSummary } from "@platform/shared-types";
import { Button, SectionPanel, StatusBadge } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { downloadFromApi } from "@/lib/api/download";
import { formatDate, titleCase } from "@/lib/format";
import { formatRunTypeLabel } from "@/lib/run-labels";

type RunAuditPageProps = {
  currentUser: AuthUser;
  projectId: string;
  audit: RunAuditSummary;
};

export function RunAuditPageView({ currentUser, projectId, audit }: RunAuditPageProps) {
  const [rawOpen, setRawOpen] = useState(false);
  const [exportingHtml, setExportingHtml] = useState(false);
  const h = audit.highlights;
  const events =
    audit.logs_json && Array.isArray((audit.logs_json as { events?: unknown }).events)
      ? ((audit.logs_json as { events: { stage?: string; message?: string }[] }).events)
      : [];

  async function onDownloadHtml() {
    try {
      setExportingHtml(true);
      await downloadFromApi(
        `/projects/${projectId}/runs/${audit.id}/audit/export?format=html`,
        `run-audit-${audit.id}.html`,
      );
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Download failed.");
    } finally {
      setExportingHtml(false);
    }
  }

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Pipeline run audit"
      title={`Run ${audit.id.slice(0, 8)}…`}
      subtitle="Read-only summary from persisted run, summary_json, and logs_json."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" disabled={exportingHtml} onClick={() => void onDownloadHtml()}>
            {exportingHtml ? "Preparing…" : "Download HTML"}
          </Button>
          <Link
            href={`/projects/${projectId}/runs/${audit.id}/comparison`}
            className="rounded-full border border-white/10 bg-white/[0.05] px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-slate-200 hover:border-white/20"
          >
            View comparison
          </Link>
          <Link
            href={`/projects/${projectId}`}
            className="rounded-full border border-white/10 bg-white/[0.05] px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-slate-200 hover:border-white/20"
          >
            Project
          </Link>
        </div>
      }
      meta={
        <>
          <StatusBadge value={audit.status} />
          <span className="rounded-full border border-white/10 bg-white/[0.05] px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-300">
            {formatRunTypeLabel(audit.run_type)}
          </span>
        </>
      }
    >
      <SectionPanel title="Audit notes" description="Derived from run status, summary, and logs.">
        <ul className="list-inside list-disc space-y-1 text-sm text-slate-200">
          {audit.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      </SectionPanel>

      <div className="grid gap-6 lg:grid-cols-2">
        <SectionPanel title="Run identity" description="Core fields from pipeline_runs.">
          <dl className="grid gap-3 text-sm">
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Run id</dt>
              <dd className="mt-1 font-mono text-xs text-slate-300 break-all">{audit.id}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Triggered by</dt>
              <dd className="mt-1 font-mono text-xs text-slate-300">
                {audit.triggered_by_user_id}
                {audit.triggered_by_user_id === currentUser.id ? " (you)" : ""}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Pipeline id</dt>
              <dd className="mt-1 text-slate-200">
                {audit.pipeline_id ? (
                  <Link
                    href={`/projects/${projectId}/pipelines/${audit.pipeline_id}`}
                    className="text-indigo-300 hover:text-indigo-200"
                  >
                    {audit.pipeline_id}
                  </Link>
                ) : (
                  "—"
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Created</dt>
              <dd className="mt-1 text-slate-200">{formatDate(audit.created_at)}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Started / completed</dt>
              <dd className="mt-1 text-slate-200">
                {audit.started_at ? formatDate(audit.started_at) : "—"} →{" "}
                {audit.completed_at ? formatDate(audit.completed_at) : "—"}
              </dd>
            </div>
          </dl>
        </SectionPanel>

        <SectionPanel title="Audit highlights" description="Inferred from summary_json and logs.">
          <dl className="grid gap-3 text-sm">
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Logged stages</dt>
              <dd className="mt-1 text-slate-200">{h.stage_count}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Failed stage</dt>
              <dd className="mt-1 text-slate-200">{h.failed_stage ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Derived dataset created</dt>
              <dd className="mt-1 text-slate-200">{h.derived_dataset_created ? "Yes" : "No"}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Ingestion / transformation</dt>
              <dd className="mt-1 text-slate-200">
                {[h.ingestion_type, h.transformation_type].filter(Boolean).join(" · ") || "—"}
              </dd>
            </div>
          </dl>
        </SectionPanel>
      </div>

      <SectionPanel
        title="Related datasets"
        description="Ids extracted from summary_json when present (ingestion or transformation runs)."
      >
        {audit.related_dataset_ids.length === 0 ? (
          <p className="text-sm text-slate-400">No related dataset ids found in summary metadata.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {audit.related_dataset_ids.map((id) => (
              <li key={id}>
                <Link href={`/projects/${projectId}/datasets/${id}/audit`} className="text-indigo-300 hover:text-indigo-200">
                  Dataset {id}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </SectionPanel>

      <SectionPanel title="Stage / log overview" description="Latest persisted log events (stage + message).">
        {events.length === 0 ? (
          <p className="text-sm text-slate-400">No log events in logs_json.</p>
        ) : (
          <ol className="space-y-2 text-sm">
            {events.map((ev, idx) => (
              <li key={`${ev.stage}-${idx}`} className="rounded-xl border border-white/8 bg-white/[0.02] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.16em] text-slate-500">{ev.stage ?? "event"}</span>
                <p className="mt-1 text-slate-200">{ev.message ?? "—"}</p>
              </li>
            ))}
          </ol>
        )}
      </SectionPanel>

      <SectionPanel title="Technical details" description="Raw summary and logs for debugging (secondary).">
        <button
          type="button"
          onClick={() => setRawOpen(!rawOpen)}
          className="text-sm text-indigo-300 hover:text-indigo-200"
        >
          {rawOpen ? "Hide raw metadata" : "Show raw metadata"}
        </button>
        {rawOpen ? (
          <div className="mt-4 space-y-4">
            <div>
              <h4 className="text-xs uppercase tracking-[0.18em] text-slate-500">summary_json</h4>
              <pre className="mt-2 max-h-64 overflow-auto rounded-xl border border-white/10 bg-black/30 p-3 text-xs text-slate-300">
                {audit.summary_json ? JSON.stringify(audit.summary_json, null, 2) : "null"}
              </pre>
            </div>
            <div>
              <h4 className="text-xs uppercase tracking-[0.18em] text-slate-500">logs_json</h4>
              <pre className="mt-2 max-h-64 overflow-auto rounded-xl border border-white/10 bg-black/30 p-3 text-xs text-slate-300">
                {audit.logs_json ? JSON.stringify(audit.logs_json, null, 2) : "null"}
              </pre>
            </div>
          </div>
        ) : null}
      </SectionPanel>
    </AppShell>
  );
}
