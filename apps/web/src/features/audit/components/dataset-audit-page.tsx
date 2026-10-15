"use client";

import Link from "next/link";
import { useState } from "react";

import type { AuthUser, DatasetAuditSummary } from "@platform/shared-types";
import { Badge, Button, buttonClassName, SectionPanel, StatTile, StatusBadge } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { DatasetFeedPanel } from "@/features/audit/components/dataset-feed-panel";
import { downloadFromApi } from "@/lib/api/download";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate, formatNumber } from "@/lib/format";
import { fileFormatLabel } from "@/lib/labels";
import { recipeHref } from "@/lib/navigation";

type DatasetAuditPageProps = {
  currentUser: AuthUser;
  projectId: string;
  audit: DatasetAuditSummary;
};

/** A dataset's record in one page: where it came from, who added it, and how healthy it looked. */
export function DatasetAuditPageView({ currentUser, projectId, audit }: DatasetAuditPageProps) {
  const highlights = audit.profile_highlights;
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const addedBy =
    audit.ownership.uploaded_by_user_id === currentUser.id ? "You" : (audit.uploaded_by_name ?? "Not recorded");

  async function onDownload() {
    setExporting(true);
    setExportError(null);
    try {
      await downloadFromApi(`/projects/${projectId}/datasets/${audit.id}/audit/export?format=html`, `dataset-${audit.id}.html`);
    } catch (error) {
      setExportError(extractErrorMessage(error));
    } finally {
      setExporting(false);
    }
  }

  const noHighlights =
    highlights.high_null_columns.length === 0 &&
    highlights.constant_value_columns.length === 0 &&
    highlights.potential_id_columns.length === 0 &&
    highlights.duplicate_row_count == null &&
    highlights.completeness_score == null;

  return (
    <AppShell
      currentUser={currentUser}
      title={audit.name}
      subtitle="This dataset's record: where it came from, what happened to it, how healthy it is."
      actions={
        <>
          <Button variant="secondary" disabled={exporting} onClick={() => void onDownload()}>
            {exporting ? "Preparing…" : "Download a report"}
          </Button>
          <Link href={`/projects/${projectId}/datasets/${audit.id}`} className={buttonClassName("secondary", "md")}>
            Open the dataset
          </Link>
        </>
      }
      meta={
        <>
          <StatusBadge value={audit.metrics.ingestion_status} />
          {audit.is_derived ? <Badge tone="accent">Made by a recipe</Badge> : <Badge>Original data</Badge>}
        </>
      }
    >
      {exportError ? (
        <p role="alert" className="rounded-xl border border-danger-line bg-danger-soft px-3 py-2 text-[13px] text-danger">
          {exportError}
        </p>
      ) : null}

      <SectionPanel title="In short">
        <ul className="list-inside list-disc space-y-1 text-[14px] text-ink">
          {audit.warnings.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </SectionPanel>

      <DatasetFeedPanel projectId={projectId} datasetId={audit.id} />

      <section className="grid gap-4 md:grid-cols-4">
        <StatTile label="Rows" value={formatNumber(audit.metrics.row_count)} />
        <StatTile label="Columns" value={formatNumber(audit.metrics.column_count)} />
        <StatTile
          label="Filled in"
          value={highlights.completeness_score != null ? `${highlights.completeness_score}%` : "Not profiled"}
        />
        <StatTile
          label="Repeated rows"
          value={highlights.duplicate_row_count != null ? formatNumber(highlights.duplicate_row_count) : "Not profiled"}
          caption={highlights.duplicate_row_percentage != null ? `${highlights.duplicate_row_percentage}% of rows` : undefined}
        />
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <SectionPanel title="Where it came from">
          <dl className="grid gap-3 text-[14px]">
            <Fact label="Added by">{addedBy}</Fact>
            {audit.lineage.created_from_pipeline_id ? (
              <Fact label="Made by the recipe">
                <Link href={recipeHref(projectId, audit.lineage.created_from_pipeline_id)} className="text-accent hover:underline">
                  {audit.created_from_pipeline_name ?? "A recipe that has since been deleted"}
                </Link>
              </Fact>
            ) : null}
            {audit.lineage.parent_dataset_id ? (
              <Fact label="Made from">
                <Link href={`/projects/${projectId}/datasets/${audit.lineage.parent_dataset_id}`} className="text-accent hover:underline">
                  {audit.parent_dataset_name ?? "A dataset that has since been deleted"}
                </Link>
              </Fact>
            ) : null}
            {audit.artifact.original_filename ? <Fact label="From the file">{audit.artifact.original_filename}</Fact> : null}
            {audit.lineage.pipeline_run_id ? (
              <Fact label="The run that made it">
                <Link href={`/projects/${projectId}/runs/${audit.lineage.pipeline_run_id}/audit`} className="text-accent hover:underline">
                  Open the run
                </Link>
              </Fact>
            ) : null}
          </dl>
        </SectionPanel>

        <SectionPanel title="When">
          <dl className="grid gap-3 text-[14px]">
            <Fact label="Added">{formatDate(audit.metrics.created_at)}</Fact>
            <Fact label="Last changed">{formatDate(audit.metrics.updated_at)}</Fact>
            <Fact label="Last profiled">
              {audit.metrics.last_profiled_at ? formatDate(audit.metrics.last_profiled_at) : "Not yet"}
            </Fact>
            <Fact label="Stored as">
              {audit.artifact.file_type ? fileFormatLabel(audit.artifact.file_type) : "Not recorded"}
              {audit.artifact.file_size_bytes != null ? `, ${Math.max(1, Math.round(audit.artifact.file_size_bytes / 1024))} KB` : ""}
            </Fact>
          </dl>
        </SectionPanel>
      </div>

      <SectionPanel title="Columns worth a look">
        {noHighlights ? (
          <p className="text-[14px] text-ink-3">Nothing stands out, or the columns have not been profiled yet.</p>
        ) : (
          <dl className="grid gap-4 text-[14px] md:grid-cols-3">
            <Fact label="Mostly empty">{highlights.high_null_columns.join(", ") || "None"}</Fact>
            <Fact label="The same value in every row">{highlights.constant_value_columns.join(", ") || "None"}</Fact>
            <Fact label="Look like identifiers">{highlights.potential_id_columns.join(", ") || "None"}</Fact>
          </dl>
        )}
        {audit.schema_summary.sample_column_names.length > 0 ? (
          <p className="mt-4 text-[13px] text-ink-3">
            First columns: <span className="text-ink-2">{audit.schema_summary.sample_column_names.join(", ")}</span>
          </p>
        ) : null}
      </SectionPanel>
    </AppShell>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[12px] text-muted">{label}</dt>
      <dd className="mt-0.5 text-ink">{children}</dd>
    </div>
  );
}
