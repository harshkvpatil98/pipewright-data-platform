import Link from "next/link";

import type { AuthUser, DatasetRecord, ProjectDetail, TransformationPipelineRecord } from "@platform/shared-types";
import { Button, EmptyState, SectionPanel, StatusBadge } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { PipelineNameCell } from "@/features/pipelines/components/pipeline-name-cell";
import { RunPipelineButton } from "@/features/pipelines/components/run-pipeline-button";
import { formatDate } from "@/lib/format";

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
            className="inline-flex h-11 items-center justify-center rounded-xl border border-line bg-surface-2 px-4 text-sm font-medium text-ink transition hover:border-line-strong hover:bg-surface-2"
          >
            Back to project
          </Link>
          <Link
            href={createHref}
            className="inline-flex h-11 items-center justify-center rounded-xl bg-[color:var(--accent)] px-4 text-sm font-medium text-accent-ink shadow-[var(--shadow-glow)] transition hover:brightness-110"
          >
            Create pipeline
          </Link>
        </>
      }
      meta={
        <>
          <span className="rounded-full border border-line bg-surface px-3 py-1 text-xs uppercase tracking-[0.18em] text-ink-2">
            {pipelines.length} pipelines
          </span>
          {activeDatasetId ? (
            <span className="rounded-full border border-line bg-surface px-3 py-1 text-xs uppercase tracking-[0.18em] text-ink-2">
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
          <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-line text-left text-sm">
                <thead className="bg-surface text-ink-3">
                  <tr>
                    <th className="cell-pad font-medium">Pipeline</th>
                    <th className="cell-pad font-medium">Base dataset</th>
                    <th className="cell-pad font-medium">Status</th>
                    <th className="cell-pad font-medium">Steps</th>
                    <th className="cell-pad font-medium">Created</th>
                    <th className="cell-pad font-medium text-right">Run</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {pipelines.map((pipeline) => (
                    <tr key={pipeline.id} className="transition hover:bg-surface">
                      <td className="cell-pad align-top">
                        <PipelineNameCell
                          projectId={project.id}
                          pipelineId={pipeline.id}
                          baseDatasetId={pipeline.base_dataset_id}
                          name={pipeline.name}
                        />
                        <div className="mt-1 max-w-sm text-ink-3">{pipeline.description ?? "No pipeline description provided."}</div>
                      </td>
                      <td className="cell-pad align-top text-ink-2">{datasetNameMap.get(pipeline.base_dataset_id) ?? pipeline.base_dataset_id}</td>
                      <td className="cell-pad align-top">
                        <StatusBadge value={pipeline.status} />
                      </td>
                      <td className="cell-pad align-top text-ink-2">{pipeline.step_count}</td>
                      <td className="cell-pad align-top text-ink-3">{formatDate(pipeline.created_at)}</td>
                      <td className="cell-pad align-top">
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
