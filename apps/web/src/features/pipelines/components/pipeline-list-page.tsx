import Link from "next/link";

import type { AuthUser, DatasetRecord, ProjectDetail, TransformationPipelineRecord } from "@platform/shared-types";
import { EmptyState, SectionPanel, StatusBadge, buttonClassName } from "@platform/shared-ui";

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
  const studioHref = activeDatasetId
    ? `/projects/${project.id}/studio?dataset=${activeDatasetId}`
    : `/projects/${project.id}/studio`;

  return (
    <AppShell
      currentUser={currentUser}
      title="Recipes"
      subtitle="Saved recipes: the steps that turn one dataset into another."
      actions={
        <Link href={studioHref} className={buttonClassName("primary")}>
          New recipe
        </Link>
      }
      meta={
        activeDatasetId ? (
          <span className="rounded-full border border-line bg-surface px-3 py-1 text-[13px] text-ink-2">
            Starting from {datasetNameMap.get(activeDatasetId) ?? "one dataset"}
          </span>
        ) : undefined
      }
    >
      <SectionPanel
        title={`${pipelines.length} saved recipe${pipelines.length === 1 ? "" : "s"}`}
        description="Open one in the Studio to change its steps, or run it to make a fresh copy of its result."
      >
        {pipelines.length === 0 ? (
          <EmptyState
            title="No recipes yet"
            description="Open Studio, pick a dataset and add steps. Save it, and it appears here."
            action={
              <Link href={studioHref} className={buttonClassName("primary", "sm")}>
                Open Studio
              </Link>
            }
          />
        ) : (
          <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-line text-left text-sm">
                <thead className="bg-surface text-ink-3">
                  <tr>
                    <th className="cell-pad font-medium">Recipe</th>
                    <th className="cell-pad font-medium">Starts from</th>
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
                          name={pipeline.name}
                        />
                        <div className="mt-1 max-w-sm text-ink-3">{pipeline.description ?? "No description."}</div>
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
