"use client";

import Link from "next/link";

import type { TransformationPipelineRecord } from "@platform/shared-types";
import {
  SectionPanel,
  StatusBadge,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@platform/shared-ui";

import { RunPipelineButton } from "@/features/pipelines/components/run-pipeline-button";
import { recipeHref } from "@/lib/navigation";

type DatasetPipelinesRunSectionProps = {
  projectId: string;
  pipelines: TransformationPipelineRecord[];
};

export function DatasetPipelinesRunSection({ projectId, pipelines }: DatasetPipelinesRunSectionProps) {
  if (pipelines.length === 0) {
    return null;
  }

  return (
    <SectionPanel
      title="Recipes that start here"
      description="Run one to make a fresh copy of its result from this data."
    >
      <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
        <Table>
          <TableHead>
            <TableRow>
              <TableHeaderCell>Recipe</TableHeaderCell>
              <TableHeaderCell>Status</TableHeaderCell>
              <TableHeaderCell>Steps</TableHeaderCell>
              <TableHeaderCell className="text-right">
                <span className="sr-only">Open</span>
              </TableHeaderCell>
              <TableHeaderCell className="text-right">
                <span className="sr-only">Run</span>
              </TableHeaderCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {pipelines.map((pipeline) => (
              <TableRow key={pipeline.id}>
                <TableCell>
                  <Link
                    href={recipeHref(projectId, pipeline.id)}
                    className="font-medium text-ink hover:text-accent"
                  >
                    {pipeline.name}
                  </Link>
                  <div className="mt-1 text-sm leading-6 text-ink-3">
                    {pipeline.description ?? `${pipeline.step_count} step${pipeline.step_count === 1 ? "" : "s"}`}
                  </div>
                </TableCell>
                <TableCell>
                  <StatusBadge value={pipeline.status} />
                </TableCell>
                <TableCell className="text-ink-3">{pipeline.step_count}</TableCell>
                <TableCell>
                  <div className="flex justify-end">
                    <Link
                      href={recipeHref(projectId, pipeline.id)}
                      className="text-sm text-accent hover:text-accent"
                    >
                      Open
                    </Link>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex justify-end">
                    <RunPipelineButton projectId={projectId} pipelineId={pipeline.id} />
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </SectionPanel>
  );
}
