"use client";

import Link from "next/link";
import { useState } from "react";

import type { AuthUser, DatasetAuditSummary } from "@platform/shared-types";
import { Button, SectionPanel, StatCard, StatusBadge } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { downloadFromApi } from "@/lib/api/download";
import { formatDate, formatNumber, titleCase } from "@/lib/format";

type DatasetAuditPageProps = {
  currentUser: AuthUser;
  projectId: string;
  audit: DatasetAuditSummary;
};

export function DatasetAuditPageView({ currentUser, projectId, audit }: DatasetAuditPageProps) {
  const ph = audit.profile_highlights;
  const [exportingHtml, setExportingHtml] = useState(false);

  async function onDownloadHtml() {
    try {
      setExportingHtml(true);
      await downloadFromApi(
        `/projects/${projectId}/datasets/${audit.id}/audit/export?format=html`,
        `dataset-audit-${audit.id}.html`,
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
      eyebrow="Dataset audit"
      title={audit.name}
      subtitle="Read-only summary assembled from persisted dataset metadata, schema, profile, and lineage."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" disabled={exportingHtml} onClick={() => void onDownloadHtml()}>
            {exportingHtml ? "Preparing…" : "Download HTML"}
          </Button>
          <Link
            href={`/projects/${projectId}/datasets/${audit.id}`}
            className="rounded-full border border-white/10 bg-white/[0.05] px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-slate-200 hover:border-white/20"
          >
            Dataset detail
          </Link>
        </div>
      }
      meta={
        <>
          <StatusBadge value={audit.metrics.ingestion_status} />
          {audit.is_derived ? (
            <span className="rounded-full border border-indigo-400/25 bg-indigo-500/15 px-3 py-1 text-xs uppercase tracking-[0.18em] text-indigo-200">
              Derived
            </span>
          ) : null}
          <span className="rounded-full border border-white/10 bg-white/[0.05] px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-300">
            Project: {audit.project.name}
          </span>
        </>
      }
    >
      <SectionPanel title="Audit notes" description="Deterministic highlights derived from stored metadata.">
        <ul className="list-inside list-disc space-y-1 text-sm text-slate-200">
          {audit.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      </SectionPanel>

      <section className="grid gap-4 md:grid-cols-4">
        <StatCard label="Rows" value={formatNumber(audit.metrics.row_count)} caption="From dataset record." />
        <StatCard label="Columns" value={formatNumber(audit.metrics.column_count)} caption="From dataset record." />
        <StatCard
          label="Completeness"
          value={ph.completeness_score != null ? `${ph.completeness_score}%` : "--"}
          caption="From latest profile when available."
        />
        <StatCard
          label="Duplicate rows"
          value={ph.duplicate_row_count != null ? formatNumber(ph.duplicate_row_count) : "--"}
          caption={
            ph.duplicate_row_percentage != null ? `${ph.duplicate_row_percentage}% of rows` : "Profile metric"
          }
        />
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <SectionPanel title="Artifact" description="File names and storage hints safe to display.">
          <dl className="grid gap-3 text-sm">
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Original filename</dt>
              <dd className="mt-1 text-slate-200">{audit.artifact.original_filename ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Stored file name</dt>
              <dd className="mt-1 text-slate-200">{audit.artifact.file_name ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Type / size</dt>
              <dd className="mt-1 text-slate-200">
                {audit.artifact.file_type ? titleCase(audit.artifact.file_type) : "—"}
                {audit.artifact.file_size_bytes != null
                  ? ` · ${Math.round(audit.artifact.file_size_bytes / 1024)} KB`
                  : ""}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Storage path</dt>
              <dd className="mt-1 font-mono text-xs text-slate-300 break-all">
                {audit.artifact.file_path ?? "Not shown (absolute or unsafe paths are hidden)."}
              </dd>
            </div>
          </dl>
        </SectionPanel>

        <SectionPanel title="Ownership & lifecycle" description="Project context and timestamps.">
          <dl className="grid gap-3 text-sm">
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Uploaded by (user id)</dt>
              <dd className="mt-1 font-mono text-xs text-slate-300">
                {audit.ownership.uploaded_by_user_id ?? "—"}
                {audit.ownership.uploaded_by_user_id === currentUser.id ? " (you)" : ""}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Created</dt>
              <dd className="mt-1 text-slate-200">{formatDate(audit.metrics.created_at)}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Updated</dt>
              <dd className="mt-1 text-slate-200">{formatDate(audit.metrics.updated_at)}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Last profiled</dt>
              <dd className="mt-1 text-slate-200">
                {audit.metrics.last_profiled_at ? formatDate(audit.metrics.last_profiled_at) : "Not yet"}
              </dd>
            </div>
          </dl>
        </SectionPanel>
      </div>

      <SectionPanel title="Quality / profile highlights" description="From persisted profile_json when present.">
        {ph.high_null_columns.length === 0 &&
        ph.constant_value_columns.length === 0 &&
        ph.potential_id_columns.length === 0 &&
        ph.duplicate_row_count == null &&
        ph.completeness_score == null ? (
          <p className="text-sm text-slate-400">
            No profile highlights available. The dataset may not have been profiled yet, or profile metadata is empty.
          </p>
        ) : (
          <dl className="grid gap-4 md:grid-cols-2 text-sm">
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">High-null columns</dt>
              <dd className="mt-1 text-slate-200">
                {ph.high_null_columns.length ? ph.high_null_columns.join(", ") : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Constant columns</dt>
              <dd className="mt-1 text-slate-200">
                {ph.constant_value_columns.length ? ph.constant_value_columns.join(", ") : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Potential identifier columns</dt>
              <dd className="mt-1 text-slate-200">
                {ph.potential_id_columns.length ? ph.potential_id_columns.join(", ") : "—"}
              </dd>
            </div>
          </dl>
        )}
      </SectionPanel>

      <div className="grid gap-6 lg:grid-cols-2">
        <SectionPanel title="Schema summary" description="Lightweight view of stored schema_json.">
          <p className="text-sm text-slate-300">
            Column count: {audit.schema_summary.column_count ?? "—"}
          </p>
          {audit.schema_summary.sample_column_names.length > 0 ? (
            <p className="mt-2 text-xs text-slate-500">
              Sample columns:{" "}
              <span className="text-slate-300">{audit.schema_summary.sample_column_names.join(", ")}</span>
            </p>
          ) : null}
        </SectionPanel>

        <SectionPanel title="Lineage & related runs" description="Foreign keys stored on the dataset row.">
          <dl className="grid gap-3 text-sm">
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Parent dataset</dt>
              <dd className="mt-1 text-slate-200">
                {audit.lineage.parent_dataset_id ? (
                  <Link
                    href={`/projects/${projectId}/datasets/${audit.lineage.parent_dataset_id}/audit`}
                    className="text-indigo-300 hover:text-indigo-200"
                  >
                    {audit.lineage.parent_dataset_id}
                  </Link>
                ) : (
                  "—"
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Created from pipeline</dt>
              <dd className="mt-1 font-mono text-xs text-slate-300">
                {audit.lineage.created_from_pipeline_id ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Ingestion / materialization run</dt>
              <dd className="mt-1 text-slate-200">
                {audit.lineage.pipeline_run_id ? (
                  <Link
                    href={`/projects/${projectId}/runs/${audit.lineage.pipeline_run_id}/audit`}
                    className="text-indigo-300 hover:text-indigo-200"
                  >
                    View run audit
                  </Link>
                ) : (
                  "—"
                )}
              </dd>
            </div>
          </dl>
        </SectionPanel>
      </div>
    </AppShell>
  );
}
