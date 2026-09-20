"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type {
  AuthUser,
  DatasetPreview,
  DatasetProfileSummary,
  DatasetRecord,
  PipelineRunRecord,
  TransformationPipelineRecord,
  TransformationSuggestion,
} from "@platform/shared-types";
import { Button, SectionPanel, StatCard, StatusBadge } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { extractErrorMessage } from "@/lib/api/errors";
import { apiFetch } from "@/lib/api/client";
import { Modal } from "@/components/ui/modal";
import { DeleteRowButton } from "@/components/ui/delete-row-button";
import { DatasetPipelinesRunSection } from "@/features/datasets/components/dataset-pipelines-run-section";
import { DatasetSuggestedTransformations } from "@/features/datasets/components/dataset-suggested-transformations";
import { PreviewTransformModal } from "@/features/datasets/components/preview-transform-modal";
import { PublishDatasetModal } from "@/features/datasets/components/publish-dataset-modal";
import { PublishPowerBiModal } from "@/features/datasets/components/publish-power-bi-modal";
import { PublishTableauModal } from "@/features/datasets/components/publish-tableau-modal";
import {
  getPipelineRunSecondaryText,
  isDatasetIngestionRunSummary,
  isDatasetTransformationRunSummary,
} from "@/features/datasets/run-summary";
import { formatDate, formatNumber, titleCase } from "@/lib/format";
import { formatRunTypeLabel } from "@/lib/run-labels";

type DatasetDetailPageViewProps = {
  currentUser: AuthUser;
  projectId: string;
  dataset: DatasetRecord;
  preview: DatasetPreview;
  profile: DatasetProfileSummary | null;
  relatedRun: PipelineRunRecord | null;
  pipelinesForDataset: TransformationPipelineRecord[];
  lineageParent: DatasetRecord | null;
  lineagePipeline: TransformationPipelineRecord | null;
  transformationSuggestions: TransformationSuggestion[];
};

export function DatasetDetailPageView({
  currentUser,
  projectId,
  dataset,
  preview,
  profile,
  relatedRun,
  pipelinesForDataset,
  lineageParent,
  lineagePipeline,
  transformationSuggestions,
}: DatasetDetailPageViewProps) {
  const router = useRouter();
  const [isRenaming, setIsRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState(dataset.name);
  const [renameBusy, setRenameBusy] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);
  const [isPreviewTransformOpen, setIsPreviewTransformOpen] = useState(false);
  const [isPublishOpen, setIsPublishOpen] = useState(false);
  const [isPublishPowerBiOpen, setIsPublishPowerBiOpen] = useState(false);
  const [isPublishTableauOpen, setIsPublishTableauOpen] = useState(false);
  const profileColumns = profile?.columns ?? [];
  const qualityFlags = profile?.quality_flags ?? {
    high_null_columns: [],
    constant_value_columns: [],
    potential_id_columns: [],
    mixed_type_suspicions: [],
  };
  const schemaColumns = dataset.schema_json?.columns ?? [];
  const runSummary = relatedRun?.summary_json;

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Dataset detail"
      title={dataset.name}
      subtitle="Inspect file metadata, inferred schema, quality profile, and a stable preview of ingested rows."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Link href={`/projects/${projectId}/datasets/${dataset.id}/audit`}>
            <Button variant="secondary" size="sm">View Audit</Button>
          </Link>
          <Link href={`/projects/${projectId}/datasets/${dataset.id}/lineage`}>
            <Button variant="secondary" size="sm">Lineage</Button>
          </Link>
          <Link href={`/projects/${projectId}/datasets/${dataset.id}/metrics`}>
            <Button variant="secondary" size="sm">Metrics</Button>
          </Link>
          <Link href={`/projects/${projectId}/datasets/${dataset.id}/assistant`}>
            <Button variant="secondary" size="sm">Assistant</Button>
          </Link>
          <Button variant="secondary" size="sm" onClick={() => setIsPreviewTransformOpen(true)}>
            Preview Transform
          </Button>
          {dataset.ingestion_status === "succeeded" && dataset.file_type ? (
            <>
              <Button variant="secondary" size="sm" onClick={() => setIsPublishOpen(true)}>
                Publish to PostgreSQL
              </Button>
              <Button variant="secondary" size="sm" onClick={() => setIsPublishPowerBiOpen(true)}>
                Publish to Power BI
              </Button>
              <Button variant="secondary" size="sm" onClick={() => setIsPublishTableauOpen(true)}>
                Publish to Tableau
              </Button>
            </>
          ) : null}
          {!dataset.is_derived ? (
            <Link href={`/projects/${projectId}/pipelines/new?sourceDatasetId=${dataset.id}`}>
              <Button size="sm">Create Pipeline</Button>
            </Link>
          ) : null}
          <Button variant="secondary" size="sm" onClick={() => setIsRenaming(true)}>
            Rename
          </Button>
          <DeleteRowButton
            path={`/projects/${projectId}/datasets/${dataset.id}`}
            name={dataset.name}
            kind="dataset"
            requireTypedName
            consequences={[
              "Its stored file, profile, schema and preview go with it.",
              "Pipelines and rules built on it will no longer have a source.",
            ]}
            onDeleted={() => router.push(`/projects/${projectId}`)}
          />
        </div>
      }
      meta={
        <>
          <StatusBadge value={dataset.ingestion_status} />
          {dataset.is_derived ? (
            <span className="rounded-full border border-accent-line bg-accent-soft px-3 py-1 text-xs uppercase tracking-[0.18em] text-accent">
              Derived dataset
            </span>
          ) : (
            <span className="rounded-full border border-line bg-surface-2 px-3 py-1 text-xs uppercase tracking-[0.18em] text-ink-2">
              Source dataset
            </span>
          )}
          <span className="rounded-full border border-line bg-surface px-3 py-1 text-xs uppercase tracking-[0.18em] text-ink-2">
            {dataset.file_type ? titleCase(dataset.file_type) : "Unknown type"}
          </span>
          <Link href={`/projects/${projectId}`} className="rounded-full border border-line bg-surface px-3 py-1 text-xs uppercase tracking-[0.18em] text-ink-2">
            Back to project
          </Link>
        </>
      }
    >
      <PreviewTransformModal
        open={isPreviewTransformOpen}
        onClose={() => setIsPreviewTransformOpen(false)}
        projectId={projectId}
        datasetId={dataset.id}
      />
      <PublishDatasetModal
        open={isPublishOpen}
        onClose={() => setIsPublishOpen(false)}
        projectId={projectId}
        datasetId={dataset.id}
      />
      <PublishPowerBiModal
        open={isPublishPowerBiOpen}
        onClose={() => setIsPublishPowerBiOpen(false)}
        projectId={projectId}
        datasetId={dataset.id}
      />
      <PublishTableauModal
        open={isPublishTableauOpen}
        onClose={() => setIsPublishTableauOpen(false)}
        projectId={projectId}
        datasetId={dataset.id}
      />

      {!dataset.is_derived && pipelinesForDataset.length > 0 ? (
        <DatasetPipelinesRunSection projectId={projectId} pipelines={pipelinesForDataset} />
      ) : null}

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Rows" value={formatNumber(dataset.row_count)} caption="Parsed row count from the uploaded file." />
        <StatCard label="Columns" value={formatNumber(dataset.column_count)} caption="Detected structural columns after parsing." />
        <StatCard label="File size" value={dataset.file_size_bytes ? `${Math.round(dataset.file_size_bytes / 1024)} KB` : "--"} caption="Stored artifact size in local development storage." />
        <StatCard label="Completeness" value={profile ? `${profile.completeness_score}%` : "--"} caption="Overall non-null cell coverage across the persisted preview profile." />
      </section>

      {!dataset.is_derived ? (
        <DatasetSuggestedTransformations
          projectId={projectId}
          datasetId={dataset.id}
          datasetName={dataset.name}
          suggestions={transformationSuggestions}
        />
      ) : null}

      {dataset.is_derived ? (
        <SectionPanel
          title="Lineage"
          description="This dataset was produced by a transformation pipeline from another dataset in this project."
        >
          <dl className="grid gap-4 md:grid-cols-2">
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Parent dataset</dt>
              <dd className="mt-2 text-sm text-ink">
                {lineageParent ? (
                  <Link href={`/projects/${projectId}/datasets/${lineageParent.id}`} className="text-accent hover:text-accent">
                    {lineageParent.name}
                  </Link>
                ) : dataset.parent_dataset_id ? (
                  <span className="font-mono text-xs text-ink-3">{dataset.parent_dataset_id}</span>
                ) : (
                  "--"
                )}
                {dataset.parent_dataset_id ? (
                  <div className="mt-2">
                    <Link
                      href={`/projects/${projectId}/datasets/${dataset.id}/compare/${dataset.parent_dataset_id}`}
                      className="text-xs font-medium uppercase tracking-[0.14em] text-accent hover:text-accent"
                    >
                      Compare with parent
                    </Link>
                  </div>
                ) : null}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Transformation pipeline</dt>
              <dd className="mt-2 text-sm text-ink">
                {lineagePipeline ? (
                  <Link
                    href={`/projects/${projectId}/datasets/${lineagePipeline.base_dataset_id}/pipelines/${lineagePipeline.id}`}
                    className="text-accent hover:text-accent"
                  >
                    {lineagePipeline.name}
                  </Link>
                ) : dataset.created_from_pipeline_id ? (
                  <span className="font-mono text-xs text-ink-3">{dataset.created_from_pipeline_id}</span>
                ) : (
                  "--"
                )}
              </dd>
            </div>
          </dl>
        </SectionPanel>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <SectionPanel title="Dataset metadata" description="Stored file and lineage information for this dataset artifact.">
          <dl className="grid gap-4 md:grid-cols-2">
            <div className="rounded-2xl border border-line bg-sunken px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Original file</dt>
              <dd className="mt-2 text-sm text-ink">{dataset.original_filename ?? "--"}</dd>
            </div>
            <div className="rounded-2xl border border-line bg-sunken px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Stored file</dt>
              <dd className="mt-2 text-sm text-ink">{dataset.file_name ?? "--"}</dd>
            </div>
            <div className="rounded-2xl border border-line bg-sunken px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Dataset status</dt>
              <dd className="mt-2"><StatusBadge value={dataset.status} /></dd>
            </div>
            <div className="rounded-2xl border border-line bg-sunken px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Ingestion status</dt>
              <dd className="mt-2"><StatusBadge value={dataset.ingestion_status} /></dd>
            </div>
            <div className="rounded-2xl border border-line bg-sunken px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Related run</dt>
              <dd className="mt-2 text-sm text-ink">
                {dataset.pipeline_run_id ? (
                  <Link
                    href={`/projects/${projectId}/runs/${dataset.pipeline_run_id}/audit`}
                    className="text-accent hover:text-accent"
                  >
                    View run audit
                  </Link>
                ) : (
                  "--"
                )}
              </dd>
            </div>
            <div className="rounded-2xl border border-line bg-sunken px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Created</dt>
              <dd className="mt-2 text-sm text-ink">{formatDate(dataset.created_at)}</dd>
            </div>
            <div className="rounded-2xl border border-line bg-sunken px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Profile refreshed</dt>
              <dd className="mt-2 text-sm text-ink">
                {dataset.last_profiled_at ? formatDate(dataset.last_profiled_at) : "Not yet"}
              </dd>
            </div>
            <div className="rounded-2xl border border-line bg-sunken px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Uploaded by</dt>
              <dd className="mt-2 text-sm text-ink">
                {dataset.uploaded_by_user_id === currentUser.id ? currentUser.username : dataset.uploaded_by_user_id ?? "--"}
              </dd>
            </div>
          </dl>
          {dataset.ingestion_error ? (
            <div className="mt-5 rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
              {dataset.ingestion_error}
            </div>
          ) : null}
        </SectionPanel>

        <SectionPanel title="Schema overview" description="Ordered columns and inferred types persisted during ingestion.">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-2xl border border-line bg-sunken px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-muted">Ordered columns</div>
              <div className="mt-2 text-2xl font-semibold text-ink">{formatNumber(schemaColumns.length)}</div>
            </div>
            <div className="rounded-2xl border border-line bg-sunken px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-muted">Preview rows stored</div>
              <div className="mt-2 text-2xl font-semibold text-ink">{formatNumber(preview.rows.length)}</div>
            </div>
          </div>
          <div className="mt-5 overflow-hidden rounded-[24px] border border-line bg-sunken">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-line text-left text-sm">
                <thead className="bg-surface text-ink-3">
                  <tr>
                    <th className="cell-pad font-medium">Column</th>
                    <th className="cell-pad font-medium">Inferred type</th>
                    <th className="cell-pad font-medium">Nullable</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {schemaColumns.map((column) => (
                    <tr key={String(column.name)} className="transition hover:bg-surface">
                      <td className="cell-pad align-top text-ink">{String(column.name)}</td>
                      <td className="cell-pad align-top text-ink-2">{String(column.inferred_type ?? "--")}</td>
                      <td className="cell-pad align-top text-ink-2">{column.nullable ? "Yes" : "No"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </SectionPanel>

        <SectionPanel title="Profile summary" description="Initial data quality and structure metrics generated at ingestion time.">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <div className="rounded-2xl border border-line bg-sunken px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-muted">Duplicate rows</div>
              <div className="mt-2 text-2xl font-semibold text-ink">{formatNumber(Number(profile?.duplicate_row_count ?? 0))}</div>
            </div>
            <div className="rounded-2xl border border-line bg-sunken px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-muted">Completeness score</div>
              <div className="mt-2 text-2xl font-semibold text-ink">{profile?.completeness_score ? `${profile.completeness_score}%` : "--"}</div>
            </div>
            <div className="rounded-2xl border border-line bg-sunken px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-muted">Total null cells</div>
              <div className="mt-2 text-2xl font-semibold text-ink">{formatNumber(Number(profile?.total_null_cells ?? 0))}</div>
            </div>
          </div>
          <div className="mt-5 grid gap-3 md:grid-cols-3">
            {Object.entries(qualityFlags).map(([key, values]) => (
              <div key={key} className="rounded-2xl border border-line bg-sunken px-4 py-4">
                <div className="text-xs uppercase tracking-[0.18em] text-muted">{titleCase(key)}</div>
                <div className="mt-2 text-sm text-ink">{values.length ? values.join(", ") : "None"}</div>
              </div>
            ))}
          </div>
        </SectionPanel>
      </div>

      <SectionPanel
        title="Related run"
        description="Persisted pipeline run linked to this dataset (ingestion, transformation, or publish when applicable)."
      >
        {relatedRun ? (
          <div className="space-y-4">
            <div className="grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
              <div className="rounded-[24px] border border-line bg-sunken p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-xs uppercase tracking-[0.18em] text-muted">Run type</div>
                    <div className="mt-2 text-lg font-semibold text-ink">{formatRunTypeLabel(relatedRun.run_type)}</div>
                  </div>
                  <StatusBadge value={relatedRun.status} />
                </div>
                <div className="mt-4 space-y-2 text-sm text-ink-2">
                  <div>Triggered by {relatedRun.triggered_by_username ?? currentUser.username}</div>
                  <div>{getPipelineRunSecondaryText(relatedRun)}</div>
                  <div>Created {formatDate(relatedRun.created_at)}</div>
                  <div>{relatedRun.completed_at ? `Completed ${formatDate(relatedRun.completed_at)}` : "Run still in progress"}</div>
                </div>
              </div>

              <div className="rounded-[24px] border border-line bg-sunken p-5">
                <div className="text-xs uppercase tracking-[0.18em] text-muted">Execution summary</div>
                {isDatasetIngestionRunSummary(runSummary) ? (
                  <div className="mt-4 grid gap-4 md:grid-cols-2">
                    <div>
                      <div className="text-sm text-muted">Artifact</div>
                      <div className="mt-2 text-sm text-ink">
                        {runSummary.artifact.original_filename} · {runSummary.artifact.file_type.toUpperCase()}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-muted">Failure stage</div>
                      <div className="mt-2 text-sm text-ink">
                        {runSummary.failure_stage ? titleCase(runSummary.failure_stage) : "None"}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-muted">Duplicate rows</div>
                      <div className="mt-2 text-sm text-ink">
                        {runSummary.profile ? formatNumber(runSummary.profile.duplicate_row_count) : "--"}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-muted">Parser metadata</div>
                      <div className="mt-2 text-sm text-ink">
                        {runSummary.parser_metadata
                          ? Object.entries(runSummary.parser_metadata)
                              .map(([key, value]) => `${titleCase(key)}: ${String(value)}`)
                              .join(" · ")
                          : "--"}
                      </div>
                    </div>
                  </div>
                ) : isDatasetTransformationRunSummary(runSummary) ? (
                  <div className="mt-4 grid gap-4 md:grid-cols-2">
                    <div>
                      <div className="text-sm text-muted">Rows before → after</div>
                      <div className="mt-2 text-sm text-ink">
                        {runSummary.row_count_before != null && runSummary.row_count_after != null
                          ? `${formatNumber(runSummary.row_count_before)} → ${formatNumber(runSummary.row_count_after)}`
                          : "--"}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-muted">Columns before → after</div>
                      <div className="mt-2 text-sm text-ink">
                        {runSummary.column_count_before != null && runSummary.column_count_after != null
                          ? `${formatNumber(runSummary.column_count_before)} → ${formatNumber(runSummary.column_count_after)}`
                          : "--"}
                      </div>
                    </div>
                    {runSummary.derived_dataset ? (
                      <div>
                        <div className="text-sm text-muted">Derived output</div>
                        <div className="mt-2 text-sm text-ink">{runSummary.derived_dataset.name}</div>
                      </div>
                    ) : null}
                    {runSummary.failure_stage ? (
                      <div>
                        <div className="text-sm text-muted">Failure stage</div>
                        <div className="mt-2 text-sm text-danger">{titleCase(runSummary.failure_stage)}</div>
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="mt-4 text-sm text-ink-2">Stored orchestration summary available on the run record.</div>
                )}
              </div>
            </div>
            <Link
              href={`/projects/${projectId}/runs/${relatedRun.id}/audit`}
              className="inline-block text-sm font-medium text-accent underline hover:text-accent"
            >
              View full run audit
            </Link>
          </div>
        ) : (
          <div className="rounded-2xl border border-line bg-sunken px-4 py-4 text-sm text-ink-2">
            No persisted pipeline run is linked to this dataset yet.
          </div>
        )}
      </SectionPanel>

      <SectionPanel title="Preview" description="The first 50 ingested rows stored as a JSON-safe preview snapshot.">
        <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-line text-left text-sm">
              <thead className="bg-surface text-ink-3">
                <tr>
                  {preview.columns.map((column) => (
                    <th key={column} className="cell-pad font-medium">{column}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {preview.rows.map((row, index) => (
                  <tr key={index} className="transition hover:bg-surface">
                    {preview.columns.map((column) => (
                      <td key={`${index}-${column}`} className="cell-pad align-top text-ink">
                        {String(row[column] ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </SectionPanel>

      <SectionPanel title="Column insights" description="Column-level null, uniqueness, and inferred type metrics derived from profiling.">
        <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-line text-left text-sm">
              <thead className="bg-surface text-ink-3">
                <tr>
                  <th className="cell-pad font-medium">Column</th>
                  <th className="cell-pad font-medium">Type</th>
                  <th className="cell-pad font-medium">Null %</th>
                  <th className="cell-pad font-medium">Unique %</th>
                  <th className="cell-pad font-medium">Sample values</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {profileColumns.map((column) => (
                  <tr key={column.name} className="transition hover:bg-surface">
                    <td className="cell-pad align-top text-ink">{column.name}</td>
                    <td className="cell-pad align-top text-ink-2">{column.inferred_type ?? "--"}</td>
                    <td className="cell-pad align-top text-ink-2">{column.null_percentage}%</td>
                    <td className="cell-pad align-top text-ink-2">{column.unique_percentage}%</td>
                    <td className="cell-pad align-top text-ink-3">
                      {Array.isArray(column.sample_values) ? column.sample_values.map(String).join(", ") : "--"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </SectionPanel>
      <Modal
        open={isRenaming}
        title="Rename dataset"
        description="A dataset takes its name from the file it was read from, which is rarely the name people want to work with."
        onClose={() => setIsRenaming(false)}
        widthClassName="max-w-md"
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setIsRenaming(false)} disabled={renameBusy}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={renameBusy || renameValue.trim().length < 2}
              onClick={() => {
                setRenameBusy(true);
                setRenameError(null);
                void apiFetch(`/projects/${projectId}/datasets/${dataset.id}`, {
                  method: "PATCH",
                  body: JSON.stringify({ name: renameValue.trim() }),
                })
                  .then(() => {
                    setIsRenaming(false);
                    router.refresh();
                  })
                  .catch((caught) => setRenameError(extractErrorMessage(caught)))
                  .finally(() => setRenameBusy(false));
              }}
            >
              {renameBusy ? "Saving…" : "Save"}
            </Button>
          </div>
        }
      >
        <label className="block space-y-1.5">
          <span className="text-[12px] text-ink-3">Name</span>
          <input
            value={renameValue}
            onChange={(event) => setRenameValue(event.target.value)}
            aria-label="Dataset name"
            className="h-9 w-full rounded-lg border border-line bg-sunken px-3 text-sm text-ink outline-none focus:border-accent"
          />
        </label>
        {renameError ? (
          <p role="alert" className="mt-3 text-sm text-danger">
            {renameError}
          </p>
        ) : null}
      </Modal>
    </AppShell>
  );
}
