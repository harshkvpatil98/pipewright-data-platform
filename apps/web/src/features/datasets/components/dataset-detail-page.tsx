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
import {
  Button,
  buttonClassName,
  Icon,
  Modal,
  SectionPanel,
  StatusBadge,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
  useToast,
} from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { ActionMenu } from "@/components/ui/action-menu";
import { typeLabel } from "@/lib/labels";
import { extractErrorMessage } from "@/lib/api/errors";
import { apiFetch } from "@/lib/api/client";
import { downloadFromApi } from "@/lib/api/download";
import { DeleteRowButton } from "@/components/ui/delete-row-button";
import { DatasetCatalogPanel } from "@/features/datasets/components/dataset-catalog-panel";
import { DatasetVersionHistoryPanel } from "@/features/datasets/components/dataset-version-history-panel";
import { DiscussionPanel } from "@/features/team/components/discussion-panel";
import { DatasetPipelinesRunSection } from "@/features/datasets/components/dataset-pipelines-run-section";
import { DatasetSuggestedTransformations } from "@/features/datasets/components/dataset-suggested-transformations";
import { DeliverDatasetModal } from "@/features/datasets/components/deliver-dataset-modal";
import { PublishPowerBiModal } from "@/features/datasets/components/publish-power-bi-modal";
import { PublishTableauModal } from "@/features/datasets/components/publish-tableau-modal";
import {
  getPipelineRunSecondaryText,
  isDatasetIngestionRunSummary,
  isDatasetTransformationRunSummary,
} from "@/features/datasets/run-summary";
import { describeParserMetadata } from "@/features/datasets/parser-metadata";
import { formatDate, formatNumber, titleCase } from "@/lib/format";
import { formatRunTypeLabel } from "@/lib/run-labels";
import { recipeHref } from "@/lib/navigation";

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
  const [isPublishOpen, setIsPublishOpen] = useState(false);
  const [isPublishPowerBiOpen, setIsPublishPowerBiOpen] = useState(false);
  const [isPublishTableauOpen, setIsPublishTableauOpen] = useState(false);
  const toast = useToast();
  const download = async (format: "csv" | "parquet") => {
    try {
      await downloadFromApi(
        `/projects/${projectId}/datasets/${dataset.id}/download?format=${format}`,
        `${dataset.name}.${format}`,
      );
    } catch (caught) {
      toast.error("Could not download the dataset", extractErrorMessage(caught));
    }
  };
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
      title={dataset.name}
      subtitle={
        dataset.is_derived
          ? "Made by a recipe. Its rows, its columns and how complete it is."
          : "Its rows, its columns and how complete it is."
      }
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {dataset.ingestion_status === "succeeded" ? (
            <Link
              href={`/projects/${projectId}/studio?dataset=${dataset.id}`}
              className={buttonClassName("primary", "sm")}
            >
              <Icon name="transform" size={15} />
              Clean in Studio
            </Link>
          ) : null}
          {dataset.ingestion_status === "succeeded" && dataset.file_type ? (
            <ActionMenu
              label="Send to"
              icon="send"
              items={[
                {
                  id: "destination",
                  label: "A destination",
                  icon: "send",
                  description: "A database table or a file in storage.",
                  onSelect: () => setIsPublishOpen(true),
                },
                {
                  id: "power-bi",
                  label: "Power BI",
                  description: "Push it as a Power BI dataset.",
                  onSelect: () => setIsPublishPowerBiOpen(true),
                },
                {
                  id: "tableau",
                  label: "Tableau",
                  description: "Make a Tableau extract.",
                  onSelect: () => setIsPublishTableauOpen(true),
                },
                {
                  id: "download-csv",
                  label: "Download as CSV",
                  icon: "download",
                  description: "Opens in any spreadsheet.",
                  onSelect: () => void download("csv"),
                },
                {
                  id: "download-parquet",
                  label: "Download as Parquet",
                  icon: "download",
                  description: "Keeps column types; for data tools.",
                  onSelect: () => void download("parquet"),
                },
              ]}
            />
          ) : null}
          <ActionMenu
            label="More"
            items={[
              {
                id: "audit",
                label: "History",
                icon: "clock",
                description: "Every version, who made it and when.",
                href: `/projects/${projectId}/datasets/${dataset.id}/audit`,
              },
              {
                id: "lineage",
                label: "Where it comes from",
                icon: "merge",
                description: "Each column traced back to its source.",
                href: `/projects/${projectId}/datasets/${dataset.id}/lineage`,
              },
              {
                id: "health",
                label: "Data health over time",
                icon: "activity",
                description: "Row counts and completeness, run by run.",
                href: `/projects/${projectId}/datasets/${dataset.id}/metrics`,
              },
              {
                id: "assistant",
                label: "Find problems",
                icon: "sparkles",
                description: "Personal data, duplicates and join suggestions.",
                href: `/projects/${projectId}/datasets/${dataset.id}/assistant`,
              },
              {
                id: "rename",
                label: "Rename",
                icon: "settings",
                onSelect: () => setIsRenaming(true),
              },
            ]}
          />
          <DeleteRowButton
            path={`/projects/${projectId}/datasets/${dataset.id}`}
            name={dataset.name}
            kind="dataset"
            requireTypedName
            consequences={[
              "Its stored file, profile, columns and preview go with it.",
              "Recipes and checks built on it will no longer have anything to read.",
            ]}
            onDeleted={() => router.push(`/projects/${projectId}/datasets`)}
          />
        </div>
      }
      meta={
        <>
          {dataset.ingestion_status !== "succeeded" ? (
            <StatusBadge value={dataset.ingestion_status} />
          ) : null}
          <span className="border-line bg-surface text-ink-2 rounded-full border px-3 py-1 text-[13px]">
            {dataset.is_derived ? "Made by a recipe" : "Original data"}
          </span>
          <span className="border-line bg-surface text-ink-2 rounded-full border px-3 py-1 text-[13px]">
            {formatNumber(dataset.row_count)} rows ·{" "}
            {formatNumber(dataset.column_count)} columns
          </span>
        </>
      }
    >
      <DeliverDatasetModal
        open={isPublishOpen}
        onClose={() => setIsPublishOpen(false)}
        projectId={projectId}
        datasetId={dataset.id}
        datasetName={dataset.name}
        columns={schemaColumns.map((column) => column.name)}
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

      <SectionPanel
        title="Rows"
        description={`The first ${formatNumber(preview.rows.length)} of ${formatNumber(dataset.row_count)} rows.`}
      >
        <div className="border-line bg-sunken overflow-hidden rounded-[24px] border">
          <Table edge="panel">
            <TableHead>
              <TableRow>
                {preview.columns.map((column) => (
                  <TableHeaderCell key={column}>
                    {column}
                  </TableHeaderCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {preview.rows.map((row, index) => (
                <TableRow key={index}>
                  {preview.columns.map((column) => (
                    <TableCell
                      key={`${index}-${column}`} className="text-ink"
                    >
                      {row[column] === null ||
                      row[column] === undefined ||
                      row[column] === "" ? (
                        <span className="text-muted">—</span>
                      ) : (
                        String(row[column])
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </SectionPanel>

      <SectionPanel
        title="Columns"
        description={
          profile
            ? `${profile.completeness_score}% of cells have a value. Empty and distinct are shares of the rows.`
            : "Each column's type, how often it is empty and how varied it is."
        }
      >
        <div className="border-line bg-sunken overflow-hidden rounded-[24px] border">
          <Table edge="panel">
            <TableHead>
              <TableRow>
                <TableHeaderCell>Column</TableHeaderCell>
                <TableHeaderCell>Type</TableHeaderCell>
                <TableHeaderCell>Empty</TableHeaderCell>
                <TableHeaderCell>Distinct</TableHeaderCell>
                <TableHeaderCell>Examples</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {profileColumns.map((column) => (
                <TableRow key={column.name}>
                  <TableCell className="text-ink">
                    {column.name}
                  </TableCell>
                  <TableCell className="text-ink-2">
                    {column.inferred_type
                      ? typeLabel(column.inferred_type)
                      : "--"}
                  </TableCell>
                  <TableCell className="text-ink-2">
                    {column.null_percentage}%
                  </TableCell>
                  <TableCell className="text-ink-2">
                    {column.unique_percentage}%
                  </TableCell>
                  <TableCell className="text-ink-3">
                    {Array.isArray(column.sample_values)
                      ? column.sample_values.map(String).join(", ")
                      : "--"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </SectionPanel>

      {dataset.is_derived ? (
        <SectionPanel
          title="Lineage"
          description="A recipe made this dataset from another one in this project."
        >
          <dl className="grid gap-4 md:grid-cols-2">
            <div>
              <dt className="text-ink-3 text-[13px]">Made from</dt>
              <dd className="text-ink mt-2 text-sm">
                {lineageParent ? (
                  <Link
                    href={`/projects/${projectId}/datasets/${lineageParent.id}`}
                    className="text-accent hover:text-accent"
                  >
                    {lineageParent.name}
                  </Link>
                ) : dataset.parent_dataset_id ? (
                  <span className="text-ink-3 font-mono text-xs">
                    {dataset.parent_dataset_id}
                  </span>
                ) : (
                  "--"
                )}
                {dataset.parent_dataset_id ? (
                  <div className="mt-2">
                    <Link
                      href={`/projects/${projectId}/datasets/${dataset.id}/compare/${dataset.parent_dataset_id}`}
                      className="text-accent text-[13px] font-medium hover:underline"
                    >
                      Compare the two
                    </Link>
                  </div>
                ) : null}
              </dd>
            </div>
            <div>
              <dt className="text-ink-3 text-[13px]">By the recipe</dt>
              <dd className="text-ink mt-2 text-sm">
                {lineagePipeline ? (
                  <Link
                    href={recipeHref(projectId, lineagePipeline.id)}
                    className="text-accent hover:text-accent"
                  >
                    {lineagePipeline.name}
                  </Link>
                ) : dataset.created_from_pipeline_id ? (
                  <span className="text-ink-3 font-mono text-xs">
                    {dataset.created_from_pipeline_id}
                  </span>
                ) : (
                  "--"
                )}
              </dd>
            </div>
          </dl>
        </SectionPanel>
      ) : null}

      {!dataset.is_derived ? (
        <DatasetSuggestedTransformations
          projectId={projectId}
          datasetId={dataset.id}
          datasetName={dataset.name}
          suggestions={transformationSuggestions}
        />
      ) : null}

      {!dataset.is_derived && pipelinesForDataset.length > 0 ? (
        <DatasetPipelinesRunSection
          projectId={projectId}
          pipelines={pipelinesForDataset}
        />
      ) : null}

      <DatasetVersionHistoryPanel
        projectId={projectId}
        datasetId={dataset.id}
      />

      <DatasetCatalogPanel
        projectId={projectId}
        datasetId={dataset.id}
        columns={schemaColumns.map((column) => String(column.name))}
      />

      <DiscussionPanel
        projectId={projectId}
        targetType="dataset"
        targetId={dataset.id}
        currentUsername={currentUser.username}
        description="Questions about this data, decisions about how to read it, caveats for the next person. Mention someone with @ and they are notified."
      />

      <details className="group border-line rounded-[28px] border bg-[color:var(--panel)] px-5 py-4 lg:px-6">
        <summary className="text-ink cursor-pointer text-[15px] font-semibold">
          Technical details
          <span className="text-muted ml-2 text-[13px] font-normal">
            The stored file, the load profile and the run that made it
          </span>
        </summary>
        <div className="mt-5 space-y-5">
          <SectionPanel
            title="File and status"
            description="Where this data is stored, and when it was last checked."
          >
            <dl className="grid gap-4 md:grid-cols-2">
              <div className="border-line bg-sunken rounded-2xl border px-4 py-4">
                <dt className="text-ink-3 text-[13px]">Original file</dt>
                <dd className="text-ink mt-2 text-sm">
                  {dataset.original_filename ?? "--"}
                </dd>
              </div>
              <div className="border-line bg-sunken rounded-2xl border px-4 py-4">
                <dt className="text-ink-3 text-[13px]">Stored file</dt>
                <dd className="text-ink mt-2 text-sm">
                  {dataset.file_name ?? "--"}
                </dd>
              </div>
              <div className="border-line bg-sunken rounded-2xl border px-4 py-4">
                <dt className="text-ink-3 text-[13px]">Dataset status</dt>
                <dd className="mt-2">
                  <StatusBadge value={dataset.status} />
                </dd>
              </div>
              <div className="border-line bg-sunken rounded-2xl border px-4 py-4">
                <dt className="text-ink-3 text-[13px]">Loading</dt>
                <dd className="mt-2">
                  <StatusBadge value={dataset.ingestion_status} />
                </dd>
              </div>
              <div className="border-line bg-sunken rounded-2xl border px-4 py-4">
                <dt className="text-ink-3 text-[13px]">Related run</dt>
                <dd className="text-ink mt-2 text-sm">
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
              <div className="border-line bg-sunken rounded-2xl border px-4 py-4">
                <dt className="text-ink-3 text-[13px]">Created</dt>
                <dd className="text-ink mt-2 text-sm">
                  {formatDate(dataset.created_at)}
                </dd>
              </div>
              <div className="border-line bg-sunken rounded-2xl border px-4 py-4">
                <dt className="text-ink-3 text-[13px]">Profile refreshed</dt>
                <dd className="text-ink mt-2 text-sm">
                  {dataset.last_profiled_at
                    ? formatDate(dataset.last_profiled_at)
                    : "Not yet"}
                </dd>
              </div>
              <div className="border-line bg-sunken rounded-2xl border px-4 py-4">
                <dt className="text-ink-3 text-[13px]">Uploaded by</dt>
                <dd className="text-ink mt-2 text-sm">
                  {dataset.uploaded_by_user_id === currentUser.id
                    ? currentUser.username
                    : (dataset.uploaded_by_user_id ?? "--")}
                </dd>
              </div>
            </dl>
            {dataset.ingestion_error ? (
              <div className="border-danger-line bg-danger-soft text-danger mt-5 rounded-2xl border px-4 py-3 text-sm">
                {dataset.ingestion_error}
              </div>
            ) : null}
          </SectionPanel>

          <SectionPanel
            title="Profile"
            description="Measured when the data was loaded."
          >
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              <div className="border-line bg-sunken rounded-2xl border px-4 py-4">
                <div className="text-ink-3 text-[13px]">Duplicate rows</div>
                <div className="text-ink mt-2 text-2xl font-semibold">
                  {formatNumber(Number(profile?.duplicate_row_count ?? 0))}
                </div>
              </div>
              <div className="border-line bg-sunken rounded-2xl border px-4 py-4">
                <div className="text-ink-3 text-[13px]">Completeness score</div>
                <div className="text-ink mt-2 text-2xl font-semibold">
                  {profile?.completeness_score
                    ? `${profile.completeness_score}%`
                    : "--"}
                </div>
              </div>
              <div className="border-line bg-sunken rounded-2xl border px-4 py-4">
                <div className="text-ink-3 text-[13px]">Total null cells</div>
                <div className="text-ink mt-2 text-2xl font-semibold">
                  {formatNumber(Number(profile?.total_null_cells ?? 0))}
                </div>
              </div>
            </div>
            <div className="mt-5 grid gap-3 md:grid-cols-3">
              {Object.entries(qualityFlags).map(([key, values]) => (
                <div
                  key={key}
                  className="border-line bg-sunken rounded-2xl border px-4 py-4"
                >
                  <div className="text-ink-3 text-[13px]">{titleCase(key)}</div>
                  <div className="text-ink mt-2 text-sm">
                    {values.length ? values.join(", ") : "None"}
                  </div>
                </div>
              ))}
            </div>
          </SectionPanel>
          <SectionPanel
            title="The run that made it"
            description="How this data was loaded or produced."
          >
            {relatedRun ? (
              <div className="space-y-4">
                <div className="grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
                  <div className="border-line bg-sunken rounded-[24px] border p-5">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-ink-3 text-[13px]">Run type</div>
                        <div className="text-ink mt-2 text-lg font-semibold">
                          {formatRunTypeLabel(relatedRun.run_type)}
                        </div>
                      </div>
                      <StatusBadge value={relatedRun.status} />
                    </div>
                    <div className="text-ink-2 mt-4 space-y-2 text-sm">
                      <div>
                        Triggered by{" "}
                        {relatedRun.triggered_by_username ??
                          currentUser.username}
                      </div>
                      <div>{getPipelineRunSecondaryText(relatedRun)}</div>
                      <div>Created {formatDate(relatedRun.created_at)}</div>
                      <div>
                        {relatedRun.completed_at
                          ? `Completed ${formatDate(relatedRun.completed_at)}`
                          : "Run still in progress"}
                      </div>
                    </div>
                  </div>

                  <div className="border-line bg-sunken rounded-[24px] border p-5">
                    <div className="text-ink-3 text-[13px]">
                      Execution summary
                    </div>
                    {isDatasetIngestionRunSummary(runSummary) ? (
                      <div className="mt-4 grid gap-4 md:grid-cols-2">
                        <div>
                          <div className="text-muted text-sm">File</div>
                          <div className="text-ink mt-2 text-sm">
                            {runSummary.artifact.original_filename} ·{" "}
                            {runSummary.artifact.file_type.toUpperCase()}
                          </div>
                        </div>
                        <div>
                          <div className="text-muted text-sm">
                            Failure stage
                          </div>
                          <div className="text-ink mt-2 text-sm">
                            {runSummary.failure_stage
                              ? titleCase(runSummary.failure_stage)
                              : "None"}
                          </div>
                        </div>
                        <div>
                          <div className="text-muted text-sm">
                            Duplicate rows
                          </div>
                          <div className="text-ink mt-2 text-sm">
                            {runSummary.profile
                              ? formatNumber(
                                  runSummary.profile.duplicate_row_count,
                                )
                              : "--"}
                          </div>
                        </div>
                        <ParserMetadataSummary
                          metadata={runSummary.parser_metadata}
                        />
                      </div>
                    ) : isDatasetTransformationRunSummary(runSummary) ? (
                      <div className="mt-4 grid gap-4 md:grid-cols-2">
                        <div>
                          <div className="text-muted text-sm">
                            Rows before → after
                          </div>
                          <div className="text-ink mt-2 text-sm">
                            {runSummary.row_count_before != null &&
                            runSummary.row_count_after != null
                              ? `${formatNumber(runSummary.row_count_before)} → ${formatNumber(runSummary.row_count_after)}`
                              : "--"}
                          </div>
                        </div>
                        <div>
                          <div className="text-muted text-sm">
                            Columns before → after
                          </div>
                          <div className="text-ink mt-2 text-sm">
                            {runSummary.column_count_before != null &&
                            runSummary.column_count_after != null
                              ? `${formatNumber(runSummary.column_count_before)} → ${formatNumber(runSummary.column_count_after)}`
                              : "--"}
                          </div>
                        </div>
                        {runSummary.derived_dataset ? (
                          <div>
                            <div className="text-muted text-sm">
                              Derived output
                            </div>
                            <div className="text-ink mt-2 text-sm">
                              {runSummary.derived_dataset.name}
                            </div>
                          </div>
                        ) : null}
                        {runSummary.failure_stage ? (
                          <div>
                            <div className="text-muted text-sm">
                              Failure stage
                            </div>
                            <div className="text-danger mt-2 text-sm">
                              {titleCase(runSummary.failure_stage)}
                            </div>
                          </div>
                        ) : null}
                      </div>
                    ) : (
                      <div className="text-ink-2 mt-4 text-sm">
                        Stored orchestration summary available on the run
                        record.
                      </div>
                    )}
                  </div>
                </div>
                <Link
                  href={`/projects/${projectId}/runs/${relatedRun.id}/audit`}
                  className="text-accent hover:text-accent inline-block text-sm font-medium underline"
                >
                  View full run audit
                </Link>
              </div>
            ) : (
              <div className="border-line bg-sunken text-ink-2 rounded-2xl border px-4 py-4 text-sm">
                No run is recorded for this dataset.
              </div>
            )}
          </SectionPanel>
        </div>
      </details>

      <Modal
        open={isRenaming}
        title="Rename dataset"
        description="A dataset takes its name from the file it was read from, which is rarely the name people want to work with."
        onClose={() => setIsRenaming(false)}
        widthClassName="max-w-md"
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setIsRenaming(false)}
              disabled={renameBusy}
            >
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
                  .catch((caught) =>
                    setRenameError(extractErrorMessage(caught)),
                  )
                  .finally(() => setRenameBusy(false));
              }}
            >
              {renameBusy ? "Saving…" : "Save"}
            </Button>
          </div>
        }
      >
        <label className="block space-y-1.5">
          <span className="text-ink-3 text-[12px]">Name</span>
          <input
            value={renameValue}
            onChange={(event) => setRenameValue(event.target.value)}
            aria-label="Dataset name"
            className="border-line bg-sunken text-ink focus:border-accent h-9 w-full rounded-lg border px-3 text-sm outline-none"
          />
        </label>
        {renameError ? (
          <p role="alert" className="text-danger mt-3 text-sm">
            {renameError}
          </p>
        ) : null}
      </Modal>
    </AppShell>
  );
}

const PARSER_NOTES_SHOWN = 4;

/** How the uploaded file was read, in words; see `parser-metadata.ts`. */
function ParserMetadataSummary({
  metadata,
}: {
  metadata?: Record<string, unknown>;
}) {
  const [showAll, setShowAll] = useState(false);
  const { facts, notes } = describeParserMetadata(metadata);
  const visibleNotes = showAll ? notes : notes.slice(0, PARSER_NOTES_SHOWN);

  return (
    <div className="md:col-span-2">
      <div className="text-muted text-sm">How the file was read</div>
      {facts.length === 0 && notes.length === 0 ? (
        <div className="text-ink mt-2 text-sm">--</div>
      ) : null}
      {facts.length > 0 ? (
        <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm">
          {facts.map((fact) => (
            <div key={fact.label} className="flex gap-1.5">
              <dt className="text-ink-3">{fact.label}</dt>
              <dd className="text-ink">{fact.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {visibleNotes.length > 0 ? (
        <ul className="mt-3 space-y-1.5 text-sm">
          {visibleNotes.map((note, index) => (
            <li key={`${note.stage}-${index}`} className="flex gap-2">
              <span
                className={
                  note.needsReview
                    ? "text-warning shrink-0 font-medium"
                    : "text-ink-2 shrink-0 font-medium"
                }
              >
                {note.label}
                {note.needsReview ? " (check this)" : ""}
              </span>
              <span className="text-ink-3">{note.reason}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {notes.length > PARSER_NOTES_SHOWN ? (
        <button
          type="button"
          onClick={() => setShowAll((current) => !current)}
          className="mt-2 text-sm text-[color:var(--accent-muted)] hover:underline"
        >
          {showAll ? "Show fewer" : `Show all ${notes.length} notes`}
        </button>
      ) : null}
    </div>
  );
}
