"use client";

import Link from "next/link";

import type { TransformationPipelineRecord } from "@platform/shared-types";
import { SectionPanel } from "@platform/shared-ui";

import { RunPipelineButton } from "@/features/pipelines/components/run-pipeline-button";

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
      title="Saved pipelines"
      description="Open the structured editor or run a saved pipeline against this dataset."
    >
      <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-line text-left text-sm">
            <thead className="bg-surface text-ink-3">
              <tr>
                <th className="cell-pad font-medium">Pipeline</th>
                <th className="cell-pad font-medium">Status</th>
                <th className="cell-pad font-medium">Steps</th>
                <th className="cell-pad font-medium text-right">Edit</th>
                <th className="cell-pad font-medium text-right">Run</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {pipelines.map((pipeline) => (
                <tr key={pipeline.id} className="transition hover:bg-surface">
                  <td className="cell-pad align-top">
                    <Link
                      href={`/projects/${projectId}/datasets/${pipeline.base_dataset_id}/pipelines/${pipeline.id}`}
                      className="font-medium text-ink hover:text-accent"
                    >
                      {pipeline.name}
                    </Link>
                    <div className="mt-1 text-sm leading-6 text-ink-3">
                      {pipeline.description ?? "No pipeline description provided."}
                    </div>
                  </td>
                  <td className="cell-pad align-top text-ink-2">{pipeline.status}</td>
                  <td className="cell-pad align-top text-ink-3">{pipeline.step_count}</td>
                  <td className="cell-pad align-top">
                    <div className="flex justify-end">
                      <Link
                        href={`/projects/${projectId}/datasets/${pipeline.base_dataset_id}/pipelines/${pipeline.id}`}
                        className="text-sm text-accent hover:text-accent"
                      >
                        Open editor
                      </Link>
                    </div>
                  </td>
                  <td className="cell-pad align-top">
                    <div className="flex justify-end">
                      <RunPipelineButton projectId={projectId} pipelineId={pipeline.id} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </SectionPanel>
  );
}
