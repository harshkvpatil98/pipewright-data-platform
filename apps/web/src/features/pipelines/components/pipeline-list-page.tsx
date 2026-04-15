import Link from "next/link";

import type { AuthUser, DatasetRecord, ProjectDetail, TransformationPipelineRecord } from "@platform/shared-types";
import { Button, EmptyState, SectionPanel, StatusBadge } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { RunPipelineButton } from "@/features/pipelines/components/run-pipeline-button";
import { formatDate, titleCase } from "@/lib/format";

type PipelineListPageViewProps = {
  currentUser: AuthUser;
  project: ProjectDetail;
  pipelines: TransformationPipelineRecord[];
  datasets: DatasetRecord[];
  activeDatasetId: string | null;
};

export function PipelineListPageView({ currentUser, project, pipelines, datasets, activeDatasetId }: PipelineListPageViewProps) {
  const datasetNameMap = new Map(datasets.map((dataset) => [dataset.id, dataset.name]));
  const createHref = activeDatasetId
    ? `/projects/${project.id}/pipelines/new?sourceDatasetId=${activeDatasetId}`
    : `/projects/${project.id}/pipelines/new`;

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Transformation pipelines"
      title={`${project.name} pipelines`}
      subtitle="Create reusable ordered transformation plans with strict structure validation and project-scoped ownership checks."
      actions={
        <>
          <Link
            href={`/projects/${project.id}`}
            className="inline-flex h-11 items-center justify-center rounded-xl border border-white/10 bg-white/[0.06] px-4 text-sm font-medium text-slate-100 transition hover:border-white/20 hover:bg-white/[0.09]"
          >
            Back to project
          </Link>
          <Link
            href={createHref}
            className="inline-flex h-11 items-center justify-center rounded-xl bg-[color:var(--accent)] px-4 text-sm font-medium text-white shadow-[0_12px_32px_rgba(79,70,229,0.22)] transition hover:brightness-110"
          >
            Create pipeline
          </Link>
        </>
      }
      meta={
        <>
          <span className="rounded-full border border-white/10 bg-white/[0.05] px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-300">
            {pipelines.length} pipelines
          </span>
          {activeDatasetId ? (
            <span className="rounded-full border border-white/10 bg-white/[0.05] px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-300">
              Filtered by {datasetNameMap.get(activeDatasetId) ?? "dataset"}
            </span>
          ) : null}
        </>
      }
    >
      <SectionPanel title="Pipeline registry" description="Reusable project-scoped transformation plans tied to existing datasets.">
        {pipelines.length === 0 ? (
          <EmptyState
            title="No pipelines created"
            description="Create the first reusable transformation pipeline for this project or dataset."
            action={<Link href={createHref}><Button>Create pipeline</Button></Link>}
          />
        ) : (
          <div className="overflow-hidden rounded-[24px] border border-white/8 bg-black/10">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-white/8 text-left text-sm">
                <thead className="bg-white/[0.03] text-slate-400">
                  <tr>
                    <th className="px-4 py-3 font-medium">Pipeline</th>
                    <th className="px-4 py-3 font-medium">Base dataset</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium">Steps</th>
                    <th className="px-4 py-3 font-medium">Created</th>
                    <th className="px-4 py-3 font-medium text-right">Run</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/6">
                  {pipelines.map((pipeline) => (
                    <tr key={pipeline.id} className="transition hover:bg-white/[0.03]">
                      <td className="px-4 py-4 align-top">
                        <Link
                          href={`/projects/${project.id}/datasets/${pipeline.base_dataset_id}/pipelines/${pipeline.id}`}
                          className="font-medium text-white hover:text-indigo-200"
                        >
                          {pipeline.name}
                        </Link>
                        <div className="mt-1 max-w-sm text-slate-400">{pipeline.description ?? "No pipeline description provided."}</div>
                      </td>
                      <td className="px-4 py-4 align-top text-slate-300">{datasetNameMap.get(pipeline.base_dataset_id) ?? pipeline.base_dataset_id}</td>
                      <td className="px-4 py-4 align-top">
                        <StatusBadge value={pipeline.status} />
                      </td>
                      <td className="px-4 py-4 align-top text-slate-300">{pipeline.step_count}</td>
                      <td className="px-4 py-4 align-top text-slate-400">{formatDate(pipeline.created_at)}</td>
                      <td className="px-4 py-4 align-top">
                        <div className="flex justify-end">
                          <RunPipelineButton projectId={project.id} pipelineId={pipeline.id} />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </SectionPanel>
    </AppShell>
  );
}
