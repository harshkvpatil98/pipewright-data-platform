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
import { CreateDatasetModal } from "@/features/projects/components/create-dataset-modal";
import { CreateSourceModal } from "@/features/projects/components/create-source-modal";
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
  const sourceNameMap = useMemo(
    () => new Map(sources.map((source) => [source.id, source.name])),
    [sources],
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
              href={`/projects/${project.id}/destinations`}
              className="inline-flex items-center rounded-full border border-white/10 bg-white/[0.05] px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-slate-200 hover:border-white/20"
            >
              Destinations
            </Link>
            <Link
              href={`/projects/${project.id}/bi-connections`}
              className="inline-flex items-center rounded-full border border-white/10 bg-white/[0.05] px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-slate-200 hover:border-white/20"
            >
              BI connections
            </Link>
            <Link
              href={`/projects/${project.id}/schedules`}
              className="inline-flex items-center rounded-full border border-white/10 bg-white/[0.05] px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-slate-200 hover:border-white/20"
            >
              Schedules
            </Link>
            <Link
              href={`/projects/${project.id}/notification-targets`}
              className="inline-flex items-center rounded-full border border-white/10 bg-white/[0.05] px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-slate-200 hover:border-white/20"
            >
              Notification targets
            </Link>
            <Link
              href={`/projects/${project.id}/tests/saved`}
              className="inline-flex items-center rounded-full border border-white/10 bg-white/[0.05] px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-slate-200 hover:border-white/20"
            >
              Saved tests
            </Link>
            <Button variant="secondary" onClick={() => setDatasetModalOpen(true)}>
              Register dataset
            </Button>
            <Button variant="secondary" onClick={() => setUploadModalOpen(true)}>
              Upload dataset
            </Button>
            <Button onClick={() => setSourceModalOpen(true)}>Add source</Button>
          </>
        }
        meta={
          <>
            <StatusBadge value={project.status} />
            <span className="rounded-full border border-white/10 bg-white/[0.05] px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-300">
              {project.slug}
            </span>
            <span className="rounded-full border border-white/10 bg-white/[0.05] px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-300">
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

        <SectionPanel
          title="Workspace surface"
          description="Move between owned project overview, sources, datasets, and orchestration run history without losing context."
          actions={
            <div className="flex flex-wrap items-center gap-3">
              <div className="inline-flex rounded-2xl border border-white/10 bg-black/10 p-1">
                {tabOptions.map((tab) => (
                  <button
                    key={tab.key}
                    className={[
                      "rounded-xl px-4 py-2 text-sm font-medium transition",
                      activeTab === tab.key
                        ? "bg-[color:var(--accent)] text-white shadow-[0_12px_24px_rgba(79,70,229,0.18)]"
                        : "text-slate-400 hover:text-white",
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
            <div className="rounded-2xl border border-emerald-400/20 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-200">
              {runFeedback}
            </div>
          ) : null}
          {runError ? (
            <div className="rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">
              {runError}
            </div>
          ) : null}

          {activeTab === "overview" ? (
            <div className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
              <div className="space-y-5">
                <div className="rounded-[24px] border border-white/8 bg-black/10 p-5">
                  <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Project summary</div>
                  <div className="mt-4 grid gap-4 md:grid-cols-2">
                    <div>
                      <div className="text-sm text-slate-500">Description</div>
                      <div className="mt-2 text-sm leading-6 text-slate-200">
                        {project.description ?? "No project description has been recorded yet."}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-slate-500">Operational posture</div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <StatusBadge value={project.status} />
                        <span className="rounded-full border border-white/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-300">
                          {sources.length} sources
                        </span>
                        <span className="rounded-full border border-white/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-300">
                          {datasets.length} datasets
                        </span>
                        <span className="rounded-full border border-white/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-300">
                          {runs.length} runs
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="rounded-[24px] border border-white/8 bg-black/10 p-5">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Recent sources</div>
                      <div className="mt-2 text-lg font-semibold text-white">Connection registrations</div>
                    </div>
                    <Button variant="secondary" size="sm" onClick={() => setSourceModalOpen(true)}>
                      Add source
                    </Button>
                  </div>
                  <div className="mt-4 space-y-3">
                    {sources.slice(0, 3).map((source) => (
                      <div key={source.id} className="rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-3">
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <div className="font-medium text-white">{source.name}</div>
                            <div className="mt-1 text-sm text-slate-400">
                              {source.description ?? `${titleCase(source.source_type)} registration`}
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <StatusBadge value={source.status} />
                            <span className="rounded-full border border-white/10 px-2.5 py-1 text-[11px] uppercase tracking-[0.18em] text-slate-300">
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

              <div className="rounded-[24px] border border-white/8 bg-black/10 p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Recent runs</div>
                    <div className="mt-2 text-lg font-semibold text-white">Owned orchestration history</div>
                  </div>
                  <Button size="sm" onClick={triggerSampleRun} disabled={runSubmitting}>
                    {runSubmitting ? "Running..." : "Run sample"}
                  </Button>
                </div>
                <div className="mt-4 space-y-3">
                  {runs.slice(0, 4).map((run) => (
                    <div key={run.id} className="rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-3">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <Link href={`/projects/${project.id}/runs/${run.id}/audit`} className="font-medium text-white hover:text-indigo-200">
                            {formatRunTypeLabel(run.run_type)}
                          </Link>
                          <div className="mt-1 text-sm text-slate-400">
                            Triggered by {run.triggered_by_username ?? "current user"}
                          </div>
                        </div>
                        <StatusBadge value={run.status} />
                      </div>
                      <div className="mt-3 flex flex-wrap gap-3 text-xs uppercase tracking-[0.18em] text-slate-500">
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
              <div className="overflow-hidden rounded-[24px] border border-white/8 bg-black/10">
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-white/8 text-left text-sm">
                    <thead className="bg-white/[0.03] text-slate-400">
                      <tr>
                        <th className="px-4 py-3 font-medium">Source</th>
                        <th className="px-4 py-3 font-medium">Type</th>
                        <th className="px-4 py-3 font-medium">Status</th>
                        <th className="px-4 py-3 font-medium">Config keys</th>
                        <th className="px-4 py-3 font-medium">Updated</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/6">
                      {sources.map((source) => (
                        <tr key={source.id} className="transition hover:bg-white/[0.03]">
                          <td className="px-4 py-4 align-top">
                            <div className="font-medium text-white">{source.name}</div>
                            <div className="mt-1 max-w-sm text-slate-400">{source.description ?? "No source description provided."}</div>
                          </td>
                          <td className="px-4 py-4 align-top text-slate-300">{titleCase(source.source_type)}</td>
                          <td className="px-4 py-4 align-top"><StatusBadge value={source.status} /></td>
                          <td className="px-4 py-4 align-top text-slate-300">{Object.keys(source.config_json ?? {}).length}</td>
                          <td className="px-4 py-4 align-top text-slate-400">{formatDate(source.updated_at)}</td>
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
              <div className="overflow-hidden rounded-[24px] border border-white/8 bg-black/10">
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-white/8 text-left text-sm">
                    <thead className="bg-white/[0.03] text-slate-400">
                      <tr>
                        <th className="px-4 py-3 font-medium">Dataset</th>
                        <th className="px-4 py-3 font-medium">File type</th>
                        <th className="px-4 py-3 font-medium">Ingestion</th>
                        <th className="px-4 py-3 font-medium">Rows</th>
                        <th className="px-4 py-3 font-medium">Columns</th>
                        <th className="px-4 py-3 font-medium">Uploaded</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/6">
                      {datasets.map((dataset) => (
                        <tr key={dataset.id} className="transition hover:bg-white/[0.03]">
                          <td className="px-4 py-4 align-top">
                            <Link href={`/projects/${project.id}/datasets/${dataset.id}`} className="font-medium text-white hover:text-indigo-200">
                              {dataset.name}
                            </Link>
                            <div className="mt-1 text-slate-400">
                              {dataset.original_filename ?? dataset.file_name ?? "No file metadata"}
                            </div>
                          </td>
                          <td className="px-4 py-4 align-top text-slate-300">{dataset.file_type ? titleCase(dataset.file_type) : "--"}</td>
                          <td className="px-4 py-4 align-top">
                            <div className="flex flex-col gap-2">
                              <StatusBadge value={dataset.ingestion_status} />
                              <span className="text-xs text-slate-500">
                                {dataset.pipeline_run_id ? `Linked run ${dataset.pipeline_run_id.slice(0, 8)}` : "No run linked"}
                              </span>
                            </div>
                          </td>
                          <td className="px-4 py-4 align-top text-slate-300">{formatNumber(dataset.row_count)}</td>
                          <td className="px-4 py-4 align-top text-slate-300">{formatNumber(dataset.column_count)}</td>
                          <td className="px-4 py-4 align-top text-slate-400">{formatDate(dataset.created_at)}</td>
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
              <div className="overflow-hidden rounded-[24px] border border-white/8 bg-black/10">
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-white/8 text-left text-sm">
                    <thead className="bg-white/[0.03] text-slate-400">
                      <tr>
                        <th className="px-4 py-3 font-medium">Run type</th>
                        <th className="px-4 py-3 font-medium">Triggered by</th>
                        <th className="px-4 py-3 font-medium">Status</th>
                        <th className="px-4 py-3 font-medium">Started</th>
                        <th className="px-4 py-3 font-medium">Completed</th>
                        <th className="px-4 py-3 font-medium">Created</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/6">
                      {runs.map((run) => (
                        <tr key={run.id} className="transition hover:bg-white/[0.03]">
                          <td className="px-4 py-4 align-top">
                            <Link
                              href={`/projects/${project.id}/runs/${run.id}/audit`}
                              className="font-medium text-white hover:text-indigo-200"
                            >
                              {formatRunTypeLabel(run.run_type)}
                            </Link>
                            <div className="mt-1 max-w-sm text-slate-400">
                              {getPipelineRunSecondaryText(run)}
                            </div>
                            {isDatasetIngestionRunSummary(run.summary_json) ? (
                              <div className="mt-2 text-xs text-slate-500">
                                {run.summary_json.failure_stage
                                  ? `Failed during ${titleCase(run.summary_json.failure_stage)}`
                                  : `${formatNumber(run.summary_json.dataset.row_count)} rows · ${formatNumber(run.summary_json.dataset.column_count)} columns`}
                              </div>
                            ) : null}
                          </td>
                          <td className="px-4 py-4 align-top text-slate-300">{run.triggered_by_username ?? currentUser.username}</td>
                          <td className="px-4 py-4 align-top"><StatusBadge value={run.status} /></td>
                          <td className="px-4 py-4 align-top text-slate-300">{run.started_at ? formatDate(run.started_at) : "--"}</td>
                          <td className="px-4 py-4 align-top text-slate-300">{run.completed_at ? formatDate(run.completed_at) : "--"}</td>
                          <td className="px-4 py-4 align-top text-slate-400">{formatDate(run.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )
          ) : null}
        </SectionPanel>
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
