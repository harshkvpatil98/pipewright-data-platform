import Link from "next/link";

import type { AuthUser, DatasetRecord, ProjectDetail, TransformationPipelineRecord } from "@platform/shared-types";
import {
  buttonClassName,
  EmptyState,
  SectionPanel,
  StatusBadge,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@platform/shared-ui";

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
        <div className="flex flex-wrap gap-2">
          <Link href={`/projects/${project.id}/pipelines/convert`} className={buttonClassName("secondary")}>
            Bring work in
          </Link>
          <Link href={studioHref} className={buttonClassName("primary")}>
            New recipe
          </Link>
        </div>
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
            <Table edge="panel">
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Recipe</TableHeaderCell>
                  <TableHeaderCell>Starts from</TableHeaderCell>
                  <TableHeaderCell>Status</TableHeaderCell>
                  <TableHeaderCell>Steps</TableHeaderCell>
                  <TableHeaderCell>Created</TableHeaderCell>
                  <TableHeaderCell className="text-right">Run</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {pipelines.map((pipeline) => (
                  <TableRow key={pipeline.id}>
                    <TableCell>
                      <PipelineNameCell
                        projectId={project.id}
                        pipelineId={pipeline.id}
                        name={pipeline.name}
                      />
                      <div className="mt-1 max-w-sm text-ink-3">{pipeline.description ?? "No description."}</div>
                    </TableCell>
                    <TableCell className="text-ink-2">{datasetNameMap.get(pipeline.base_dataset_id) ?? pipeline.base_dataset_id}</TableCell>
                    <TableCell>
                      <StatusBadge value={pipeline.status} />
                    </TableCell>
                    <TableCell className="text-ink-2">{pipeline.step_count}</TableCell>
                    <TableCell className="text-ink-3">{formatDate(pipeline.created_at)}</TableCell>
                    <TableCell>
                      <div className="flex justify-end">
                        <RunPipelineButton projectId={project.id} pipelineId={pipeline.id} />
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </SectionPanel>
    </AppShell>
  );
}
