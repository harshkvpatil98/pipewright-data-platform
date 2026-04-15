"use client";

import Link from "next/link";
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
        </div>
      }
      meta={
        <>
          <StatusBadge value={dataset.ingestion_status} />
          {dataset.is_derived ? (
            <span className="rounded-full border border-indigo-400/25 bg-indigo-500/15 px-3 py-1 text-xs uppercase tracking-[0.18em] text-indigo-200">
              Derived dataset
            </span>
          ) : (
            <span className="rounded-full border border-slate-500/25 bg-slate-500/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-300">
              Source dataset
            </span>
          )}
          <span className="rounded-full border border-white/10 bg-white/[0.05] px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-300">
            {dataset.file_type ? titleCase(dataset.file_type) : "Unknown type"}
          </span>
          <Link href={`/projects/${projectId}`} className="rounded-full border border-white/10 bg-white/[0.05] px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-300">
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
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Parent dataset</dt>
              <dd className="mt-2 text-sm text-slate-200">
                {lineageParent ? (
                  <Link href={`/projects/${projectId}/datasets/${lineageParent.id}`} className="text-indigo-300 hover:text-indigo-200">
                    {lineageParent.name}
                  </Link>
                ) : dataset.parent_dataset_id ? (
                  <span className="font-mono text-xs text-slate-400">{dataset.parent_dataset_id}</span>
                ) : (
                  "--"
                )}
                {dataset.parent_dataset_id ? (
                  <div className="mt-2">
                    <Link
                      href={`/projects/${projectId}/datasets/${dataset.id}/compare/${dataset.parent_dataset_id}`}
                      className="text-xs font-medium uppercase tracking-[0.14em] text-indigo-300/90 hover:text-indigo-200"
                    >
                      Compare with parent
                    </Link>
                  </div>
                ) : null}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Transformation pipeline</dt>
              <dd className="mt-2 text-sm text-slate-200">
                {lineagePipeline ? (
                  <Link
                    href={`/projects/${projectId}/datasets/${lineagePipeline.base_dataset_id}/pipelines/${lineagePipeline.id}`}
                    className="text-indigo-300 hover:text-indigo-200"
                  >
                    {lineagePipeline.name}
                  </Link>
                ) : dataset.created_from_pipeline_id ? (
                  <span className="font-mono text-xs text-slate-400">{dataset.created_from_pipeline_id}</span>
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
            <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Original file</dt>
              <dd className="mt-2 text-sm text-slate-200">{dataset.original_filename ?? "--"}</dd>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Stored file</dt>
              <dd className="mt-2 text-sm text-slate-200">{dataset.file_name ?? "--"}</dd>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Dataset status</dt>
              <dd className="mt-2"><StatusBadge value={dataset.status} /></dd>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Ingestion status</dt>
              <dd className="mt-2"><StatusBadge value={dataset.ingestion_status} /></dd>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Related run</dt>
              <dd className="mt-2 text-sm text-slate-200">
                {dataset.pipeline_run_id ? (
                  <Link
                    href={`/projects/${projectId}/runs/${dataset.pipeline_run_id}/audit`}
                    className="text-indigo-300 hover:text-indigo-200"
                  >
                    View run audit
                  </Link>
                ) : (
                  "--"
                )}
              </dd>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Created</dt>
              <dd className="mt-2 text-sm text-slate-200">{formatDate(dataset.created_at)}</dd>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Profile refreshed</dt>
              <dd className="mt-2 text-sm text-slate-200">
                {dataset.last_profiled_at ? formatDate(dataset.last_profiled_at) : "Not yet"}
              </dd>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Uploaded by</dt>
              <dd className="mt-2 text-sm text-slate-200">
                {dataset.uploaded_by_user_id === currentUser.id ? currentUser.username : dataset.uploaded_by_user_id ?? "--"}
              </dd>
            </div>
          </dl>
          {dataset.ingestion_error ? (
            <div className="mt-5 rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">
              {dataset.ingestion_error}
            </div>
          ) : null}
        </SectionPanel>

        <SectionPanel title="Schema overview" description="Ordered columns and inferred types persisted during ingestion.">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Ordered columns</div>
              <div className="mt-2 text-2xl font-semibold text-white">{formatNumber(schemaColumns.length)}</div>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Preview rows stored</div>
              <div className="mt-2 text-2xl font-semibold text-white">{formatNumber(preview.rows.length)}</div>
            </div>
          </div>
          <div className="mt-5 overflow-hidden rounded-[24px] border border-white/8 bg-black/10">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-white/8 text-left text-sm">
                <thead className="bg-white/[0.03] text-slate-400">
                  <tr>
                    <th className="px-4 py-3 font-medium">Column</th>
                    <th className="px-4 py-3 font-medium">Inferred type</th>
                    <th className="px-4 py-3 font-medium">Nullable</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/6">
                  {schemaColumns.map((column) => (
                    <tr key={String(column.name)} className="transition hover:bg-white/[0.03]">
                      <td className="px-4 py-4 align-top text-slate-100">{String(column.name)}</td>
                      <td className="px-4 py-4 align-top text-slate-300">{String(column.inferred_type ?? "--")}</td>
                      <td className="px-4 py-4 align-top text-slate-300">{column.nullable ? "Yes" : "No"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </SectionPanel>

        <SectionPanel title="Profile summary" description="Initial data quality and structure metrics generated at ingestion time.">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Duplicate rows</div>
              <div className="mt-2 text-2xl font-semibold text-white">{formatNumber(Number(profile?.duplicate_row_count ?? 0))}</div>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Completeness score</div>
              <div className="mt-2 text-2xl font-semibold text-white">{profile?.completeness_score ? `${profile.completeness_score}%` : "--"}</div>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Total null cells</div>
              <div className="mt-2 text-2xl font-semibold text-white">{formatNumber(Number(profile?.total_null_cells ?? 0))}</div>
            </div>
          </div>
          <div className="mt-5 grid gap-3 md:grid-cols-3">
            {Object.entries(qualityFlags).map(([key, values]) => (
              <div key={key} className="rounded-2xl border border-white/8 bg-black/10 px-4 py-4">
                <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{titleCase(key)}</div>
                <div className="mt-2 text-sm text-slate-200">{values.length ? values.join(", ") : "None"}</div>
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
              <div className="rounded-[24px] border border-white/8 bg-black/10 p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Run type</div>
                    <div className="mt-2 text-lg font-semibold text-white">{formatRunTypeLabel(relatedRun.run_type)}</div>
                  </div>
                  <StatusBadge value={relatedRun.status} />
                </div>
                <div className="mt-4 space-y-2 text-sm text-slate-300">
                  <div>Triggered by {relatedRun.triggered_by_username ?? currentUser.username}</div>
                  <div>{getPipelineRunSecondaryText(relatedRun)}</div>
                  <div>Created {formatDate(relatedRun.created_at)}</div>
                  <div>{relatedRun.completed_at ? `Completed ${formatDate(relatedRun.completed_at)}` : "Run still in progress"}</div>
                </div>
              </div>

              <div className="rounded-[24px] border border-white/8 bg-black/10 p-5">
                <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Execution summary</div>
                {isDatasetIngestionRunSummary(runSummary) ? (
                  <div className="mt-4 grid gap-4 md:grid-cols-2">
                    <div>
                      <div className="text-sm text-slate-500">Artifact</div>
                      <div className="mt-2 text-sm text-slate-200">
                        {runSummary.artifact.original_filename} · {runSummary.artifact.file_type.toUpperCase()}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-slate-500">Failure stage</div>
                      <div className="mt-2 text-sm text-slate-200">
                        {runSummary.failure_stage ? titleCase(runSummary.failure_stage) : "None"}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-slate-500">Duplicate rows</div>
                      <div className="mt-2 text-sm text-slate-200">
                        {runSummary.profile ? formatNumber(runSummary.profile.duplicate_row_count) : "--"}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-slate-500">Parser metadata</div>
                      <div className="mt-2 text-sm text-slate-200">
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
                      <div className="text-sm text-slate-500">Rows before → after</div>
                      <div className="mt-2 text-sm text-slate-200">
                        {runSummary.row_count_before != null && runSummary.row_count_after != null
                          ? `${formatNumber(runSummary.row_count_before)} → ${formatNumber(runSummary.row_count_after)}`
                          : "--"}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-slate-500">Columns before → after</div>
                      <div className="mt-2 text-sm text-slate-200">
                        {runSummary.column_count_before != null && runSummary.column_count_after != null
                          ? `${formatNumber(runSummary.column_count_before)} → ${formatNumber(runSummary.column_count_after)}`
                          : "--"}
                      </div>
                    </div>
                    {runSummary.derived_dataset ? (
                      <div>
                        <div className="text-sm text-slate-500">Derived output</div>
                        <div className="mt-2 text-sm text-slate-200">{runSummary.derived_dataset.name}</div>
                      </div>
                    ) : null}
                    {runSummary.failure_stage ? (
                      <div>
                        <div className="text-sm text-slate-500">Failure stage</div>
                        <div className="mt-2 text-sm text-rose-200">{titleCase(runSummary.failure_stage)}</div>
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="mt-4 text-sm text-slate-300">Stored orchestration summary available on the run record.</div>
                )}
              </div>
            </div>
            <Link
              href={`/projects/${projectId}/runs/${relatedRun.id}/audit`}
              className="inline-block text-sm font-medium text-indigo-300 underline hover:text-indigo-200"
            >
              View full run audit
            </Link>
          </div>
        ) : (
          <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-4 text-sm text-slate-300">
            No persisted pipeline run is linked to this dataset yet.
          </div>
        )}
      </SectionPanel>

      <SectionPanel title="Preview" description="The first 50 ingested rows stored as a JSON-safe preview snapshot.">
        <div className="overflow-hidden rounded-[24px] border border-white/8 bg-black/10">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-white/8 text-left text-sm">
              <thead className="bg-white/[0.03] text-slate-400">
                <tr>
                  {preview.columns.map((column) => (
                    <th key={column} className="px-4 py-3 font-medium">{column}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-white/6">
                {preview.rows.map((row, index) => (
                  <tr key={index} className="transition hover:bg-white/[0.03]">
                    {preview.columns.map((column) => (
                      <td key={`${index}-${column}`} className="px-4 py-4 align-top text-slate-200">
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
        <div className="overflow-hidden rounded-[24px] border border-white/8 bg-black/10">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-white/8 text-left text-sm">
              <thead className="bg-white/[0.03] text-slate-400">
                <tr>
                  <th className="px-4 py-3 font-medium">Column</th>
                  <th className="px-4 py-3 font-medium">Type</th>
                  <th className="px-4 py-3 font-medium">Null %</th>
                  <th className="px-4 py-3 font-medium">Unique %</th>
                  <th className="px-4 py-3 font-medium">Sample values</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/6">
                {profileColumns.map((column) => (
                  <tr key={column.name} className="transition hover:bg-white/[0.03]">
                    <td className="px-4 py-4 align-top text-slate-100">{column.name}</td>
                    <td className="px-4 py-4 align-top text-slate-300">{column.inferred_type ?? "--"}</td>
                    <td className="px-4 py-4 align-top text-slate-300">{column.null_percentage}%</td>
                    <td className="px-4 py-4 align-top text-slate-300">{column.unique_percentage}%</td>
                    <td className="px-4 py-4 align-top text-slate-400">
                      {Array.isArray(column.sample_values) ? column.sample_values.map(String).join(", ") : "--"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </SectionPanel>
    </AppShell>
  );
}
