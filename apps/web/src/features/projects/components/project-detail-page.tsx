"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import type {
  AuthUser,
  DatasetRecord,
  PipelineRunRecord,
  ProjectDetail,
  SourceRecord,
} from "@platform/shared-types";
import { Button, EmptyState, SectionPanel, StatCard, StatusBadge } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { getPipelineRunSecondaryText, isDatasetIngestionRunSummary } from "@/features/datasets/run-summary";
import { UploadDatasetModal } from "@/features/datasets/components/upload-dataset-modal";
import { ProjectChecklist } from "@/features/projects/components/project-checklist";
import { WorkspaceMenu } from "@/features/projects/components/workspace-menu";
import { CreateDatasetModal } from "@/features/projects/components/create-dataset-modal";
import { CreateSourceModal } from "@/features/projects/components/create-source-modal";
import { ProjectSettingsPanel } from "@/features/projects/components/project-settings-panel";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate, formatNumber, titleCase } from "@/lib/format";
import { formatRunTypeLabel } from "@/lib/run-labels";

type ProjectDetailPageViewProps = {
  currentUser: AuthUser;
  project: ProjectDetail;
  sources: SourceRecord[];
  datasets: DatasetRecord[];
  runs: PipelineRunRecord[];
};

type ProjectTab = "overview" | "sources" | "datasets" | "runs";

const tabOptions: Array<{ key: ProjectTab; label: string }> = [
  { key: "overview", label: "Overview" },
  { key: "sources", label: "Sources" },
  { key: "datasets", label: "Datasets" },
  { key: "runs", label: "Runs" },
];

export function ProjectDetailPageView({
  currentUser,
  project,
  sources,
  datasets,
  runs,
}: ProjectDetailPageViewProps) {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<ProjectTab>("overview");
  const [sourceModalOpen, setSourceModalOpen] = useState(false);
  const [datasetModalOpen, setDatasetModalOpen] = useState(false);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [runSubmitting, setRunSubmitting] = useState(false);
  const [runFeedback, setRunFeedback] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const linkedDatasets = useMemo(
    () => datasets.filter((dataset) => dataset.source_id !== null).length,
    [datasets],
  );
  const triggerSampleRun = async () => {
    setRunSubmitting(true);
    setRunError(null);
    setRunFeedback(null);

    try {
      await apiFetch(`/projects/${project.id}/runs/sample`, {
        method: "POST",
      });
      setRunFeedback("Sample orchestration run created successfully.");
      router.refresh();
    } catch (error) {
      setRunError(extractErrorMessage(error));
    } finally {
      setRunSubmitting(false);
    }
  };

  return (
    <>
      <AppShell
        currentUser={currentUser}
        eyebrow="Project workspace"
        title={project.name}
        subtitle={
          project.description ??
          "Manage the registered sources, uploaded datasets, and run history that define this owned project workspace."
        }
        actions={
          <>
            <Link
              href={`/projects/${project.id}/studio`}
              className="inline-flex items-center rounded-full border border-[color:var(--accent-soft)] bg-[color:var(--accent-faint)] px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-ink hover:brightness-110"
            >
              Open Studio
            </Link>
            <WorkspaceMenu projectId={project.id} />
            <Button onClick={() => setUploadModalOpen(true)}>Add data</Button>
            <Button variant="secondary" onClick={() => setSourceModalOpen(true)}>
              Connect a source
            </Button>
          </>
        }
        meta={
          <>
            <StatusBadge value={project.status} />
            <span className="rounded-full border border-line bg-surface px-3 py-1 text-xs uppercase tracking-[0.18em] text-ink-2">
              {project.slug}
            </span>
            <span className="rounded-full border border-line bg-surface px-3 py-1 text-xs uppercase tracking-[0.18em] text-ink-2">
              Owned by {currentUser.username}
            </span>
          </>
        }
      >
        <section className="grid gap-4 md:grid-cols-5">
          <StatCard label="Sources" value={String(sources.length)} caption="Connected registrations for this workspace." />
          <StatCard label="Datasets" value={String(datasets.length)} caption="Stored datasets and uploaded file artifacts in this project." />
          <StatCard label="Linked datasets" value={String(linkedDatasets)} caption="Datasets tied directly to a registered source." />
          <StatCard label="Runs" value={String(runs.length)} caption="Persisted orchestration and ingestion history for this project." />
          <StatCard label="Last updated" value={formatDate(project.updated_at)} caption="Most recent project-level change timestamp." />
        </section>

        <ProjectChecklist projectId={project.id} datasetCount={datasets.length} onAddData={() => setUploadModalOpen(true)} />

        <SectionPanel
          title="Workspace surface"
          description="Move between owned project overview, sources, datasets, and orchestration run history without losing context."
          actions={
            <div className="flex flex-wrap items-center gap-3">
              <div className="inline-flex rounded-2xl border border-line bg-sunken p-1">
                {tabOptions.map((tab) => (
                  <button
                    key={tab.key}
                    className={[
                      "rounded-xl px-4 py-2 text-sm font-medium transition",
                      activeTab === tab.key
                        ? "bg-[color:var(--accent)] text-accent-ink shadow-[var(--shadow-glow)]"
                        : "text-ink-3 hover:text-ink",
                    ].join(" ")}
                    onClick={() => setActiveTab(tab.key)}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
              {activeTab === "runs" ? (
                <Button onClick={triggerSampleRun} disabled={runSubmitting}>
                  {runSubmitting ? "Running..." : "Trigger sample run"}
                </Button>
              ) : null}
              {activeTab === "datasets" ? (
                <Button onClick={() => setUploadModalOpen(true)}>Upload dataset</Button>
              ) : null}
            </div>
          }
          contentClassName="space-y-5 px-5 py-5 lg:px-6"
        >
          {runFeedback ? (
            <div className="rounded-2xl border border-success-line bg-success-soft px-4 py-3 text-sm text-success">
              {runFeedback}
            </div>
          ) : null}
          {runError ? (
            <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
              {runError}
            </div>
          ) : null}

          {activeTab === "overview" ? (
            <div className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
              <div className="space-y-5">
                <div className="rounded-[24px] border border-line bg-sunken p-5">
                  <div className="text-xs uppercase tracking-[0.2em] text-muted">Project summary</div>
                  <div className="mt-4 grid gap-4 md:grid-cols-2">
                    <div>
                      <div className="text-sm text-muted">Description</div>
                      <div className="mt-2 text-sm leading-6 text-ink">
                        {project.description ?? "No project description has been recorded yet."}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-muted">Operational posture</div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <StatusBadge value={project.status} />
                        <span className="rounded-full border border-line px-3 py-1 text-xs uppercase tracking-[0.18em] text-ink-2">
                          {sources.length} sources
                        </span>
                        <span className="rounded-full border border-line px-3 py-1 text-xs uppercase tracking-[0.18em] text-ink-2">
                          {datasets.length} datasets
                        </span>
                        <span className="rounded-full border border-line px-3 py-1 text-xs uppercase tracking-[0.18em] text-ink-2">
                          {runs.length} runs
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="rounded-[24px] border border-line bg-sunken p-5">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-xs uppercase tracking-[0.2em] text-muted">Recent sources</div>
                      <div className="mt-2 text-lg font-semibold text-ink">Connection registrations</div>
                    </div>
                    <Button variant="secondary" size="sm" onClick={() => setSourceModalOpen(true)}>
                      Add source
                    </Button>
                  </div>
                  <div className="mt-4 space-y-3">
                    {sources.slice(0, 3).map((source) => (
                      <div key={source.id} className="rounded-2xl border border-line bg-surface px-4 py-3">
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <div className="font-medium text-ink">{source.name}</div>
                            <div className="mt-1 text-sm text-ink-3">
                              {source.description ?? `${titleCase(source.source_type)} registration`}
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <StatusBadge value={source.status} />
                            <span className="rounded-full border border-line px-2.5 py-1 text-[11px] uppercase tracking-[0.18em] text-ink-2">
                              {titleCase(source.source_type)}
                            </span>
                          </div>
                        </div>
                      </div>
                    ))}
                    {sources.length === 0 ? (
                      <EmptyState
                        title="No sources registered"
                        description="Register the first owned data source to begin building a traceable project surface."
                        action={<Button onClick={() => setSourceModalOpen(true)}>Register source</Button>}
                      />
                    ) : null}
                  </div>
                </div>
              </div>

              <div className="rounded-[24px] border border-line bg-sunken p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-xs uppercase tracking-[0.2em] text-muted">Recent runs</div>
                    <div className="mt-2 text-lg font-semibold text-ink">Owned orchestration history</div>
                  </div>
                  <Button size="sm" onClick={triggerSampleRun} disabled={runSubmitting}>
                    {runSubmitting ? "Running..." : "Run sample"}
                  </Button>
                </div>
                <div className="mt-4 space-y-3">
                  {runs.slice(0, 4).map((run) => (
                    <div key={run.id} className="rounded-2xl border border-line bg-surface px-4 py-3">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <Link href={`/projects/${project.id}/runs/${run.id}/audit`} className="font-medium text-ink hover:text-accent">
                            {formatRunTypeLabel(run.run_type)}
                          </Link>
                          <div className="mt-1 text-sm text-ink-3">
                            Triggered by {run.triggered_by_username ?? "current user"}
                          </div>
                        </div>
                        <StatusBadge value={run.status} />
                      </div>
                      <div className="mt-3 flex flex-wrap gap-3 text-xs uppercase tracking-[0.18em] text-muted">
                        <span>Created {formatDate(run.created_at)}</span>
                        <span>{run.completed_at ? `Completed ${formatDate(run.completed_at)}` : "Not completed"}</span>
                      </div>
                    </div>
                  ))}
                  {runs.length === 0 ? (
                    <EmptyState
                      title="No runs yet"
                      description="Trigger the first sample orchestration run to persist platform coordination history for this project."
                      action={<Button onClick={triggerSampleRun} disabled={runSubmitting}>{runSubmitting ? "Running..." : "Trigger sample run"}</Button>}
                    />
                  ) : null}
                </div>
              </div>
            </div>
          ) : null}

          {activeTab === "sources" ? (
            sources.length === 0 ? (
              <EmptyState
                title="No sources registered"
                description="Create the first source for this project to define where incoming data will originate."
                action={<Button onClick={() => setSourceModalOpen(true)}>Add source</Button>}
              />
            ) : (
              <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-line text-left text-sm">
                    <thead className="bg-surface text-ink-3">
                      <tr>
                        <th className="cell-pad font-medium">Source</th>
                        <th className="cell-pad font-medium">Type</th>
                        <th className="cell-pad font-medium">Status</th>
                        <th className="cell-pad font-medium">Config keys</th>
                        <th className="cell-pad font-medium">Updated</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {sources.map((source) => (
                        <tr key={source.id} className="transition hover:bg-surface">
                          <td className="cell-pad align-top">
                            <div className="font-medium text-ink">{source.name}</div>
                            <div className="mt-1 max-w-sm text-ink-3">{source.description ?? "No source description provided."}</div>
                          </td>
                          <td className="cell-pad align-top text-ink-2">{titleCase(source.source_type)}</td>
                          <td className="cell-pad align-top"><StatusBadge value={source.status} /></td>
                          <td className="cell-pad align-top text-ink-2">{Object.keys(source.config_json ?? {}).length}</td>
                          <td className="cell-pad align-top text-ink-3">{formatDate(source.updated_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )
          ) : null}

          {activeTab === "datasets" ? (
            datasets.length === 0 ? (
              <EmptyState
                title="No datasets registered"
                description="Upload a csv, xlsx, or json file to create a profiled dataset artifact inside this project."
                action={<Button onClick={() => setUploadModalOpen(true)}>Upload dataset</Button>}
              />
            ) : (
              <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-line text-left text-sm">
                    <thead className="bg-surface text-ink-3">
                      <tr>
                        <th className="cell-pad font-medium">Dataset</th>
                        <th className="cell-pad font-medium">File type</th>
                        <th className="cell-pad font-medium">Ingestion</th>
                        <th className="cell-pad font-medium">Rows</th>
                        <th className="cell-pad font-medium">Columns</th>
                        <th className="cell-pad font-medium">Uploaded</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {datasets.map((dataset) => (
                        <tr key={dataset.id} className="transition hover:bg-surface">
                          <td className="cell-pad align-top">
                            <Link href={`/projects/${project.id}/datasets/${dataset.id}`} className="font-medium text-ink hover:text-accent">
                              {dataset.name}
                            </Link>
                            <div className="mt-1 text-ink-3">
                              {dataset.original_filename ?? dataset.file_name ?? "No file metadata"}
                            </div>
                          </td>
                          <td className="cell-pad align-top text-ink-2">{dataset.file_type ? titleCase(dataset.file_type) : "--"}</td>
                          <td className="cell-pad align-top">
                            <div className="flex flex-col gap-2">
                              <StatusBadge value={dataset.ingestion_status} />
                              <span className="text-xs text-muted">
                                {dataset.pipeline_run_id ? `Linked run ${dataset.pipeline_run_id.slice(0, 8)}` : "No run linked"}
                              </span>
                            </div>
                          </td>
                          <td className="cell-pad align-top text-ink-2">{formatNumber(dataset.row_count)}</td>
                          <td className="cell-pad align-top text-ink-2">{formatNumber(dataset.column_count)}</td>
                          <td className="cell-pad align-top text-ink-3">{formatDate(dataset.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )
          ) : null}

          {activeTab === "runs" ? (
            runs.length === 0 ? (
              <EmptyState
                title="No runs recorded"
                description="Trigger a sample orchestration run or upload a file to create persisted project-scoped run history."
                action={<Button onClick={triggerSampleRun} disabled={runSubmitting}>{runSubmitting ? "Running..." : "Trigger sample run"}</Button>}
              />
            ) : (
              <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-line text-left text-sm">
                    <thead className="bg-surface text-ink-3">
                      <tr>
                        <th className="cell-pad font-medium">Run type</th>
                        <th className="cell-pad font-medium">Triggered by</th>
                        <th className="cell-pad font-medium">Status</th>
                        <th className="cell-pad font-medium">Started</th>
                        <th className="cell-pad font-medium">Completed</th>
                        <th className="cell-pad font-medium">Created</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {runs.map((run) => (
                        <tr key={run.id} className="transition hover:bg-surface">
                          <td className="cell-pad align-top">
                            <Link
                              href={`/projects/${project.id}/runs/${run.id}/audit`}
                              className="font-medium text-ink hover:text-accent"
                            >
                              {formatRunTypeLabel(run.run_type)}
                            </Link>
                            <div className="mt-1 max-w-sm text-ink-3">
                              {getPipelineRunSecondaryText(run)}
                            </div>
                            {isDatasetIngestionRunSummary(run.summary_json) ? (
                              <div className="mt-2 text-xs text-muted">
                                {run.summary_json.failure_stage
                                  ? `Failed during ${titleCase(run.summary_json.failure_stage)}`
                                  : `${formatNumber(run.summary_json.dataset.row_count)} rows · ${formatNumber(run.summary_json.dataset.column_count)} columns`}
                              </div>
                            ) : null}
                          </td>
                          <td className="cell-pad align-top text-ink-2">{run.triggered_by_username ?? currentUser.username}</td>
                          <td className="cell-pad align-top"><StatusBadge value={run.status} /></td>
                          <td className="cell-pad align-top text-ink-2">{run.started_at ? formatDate(run.started_at) : "--"}</td>
                          <td className="cell-pad align-top text-ink-2">{run.completed_at ? formatDate(run.completed_at) : "--"}</td>
                          <td className="cell-pad align-top text-ink-3">{formatDate(run.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )
          ) : null}
        </SectionPanel>

        {activeTab === "overview" ? <ProjectSettingsPanel project={project} /> : null}
      </AppShell>

      <CreateSourceModal open={sourceModalOpen} onClose={() => setSourceModalOpen(false)} projectId={project.id} />
      <CreateDatasetModal
        open={datasetModalOpen}
        onClose={() => setDatasetModalOpen(false)}
        projectId={project.id}
        sources={sources}
      />
      <UploadDatasetModal
        open={uploadModalOpen}
        onClose={() => setUploadModalOpen(false)}
        projectId={project.id}
      />
    </>
  );
}
