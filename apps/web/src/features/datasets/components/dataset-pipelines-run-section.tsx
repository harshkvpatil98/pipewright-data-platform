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
      <div className="overflow-hidden rounded-[24px] border border-white/8 bg-black/10">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-white/8 text-left text-sm">
            <thead className="bg-white/[0.03] text-slate-400">
              <tr>
                <th className="px-4 py-3 font-medium">Pipeline</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Steps</th>
                <th className="px-4 py-3 font-medium text-right">Edit</th>
                <th className="px-4 py-3 font-medium text-right">Run</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/6">
              {pipelines.map((pipeline) => (
                <tr key={pipeline.id} className="transition hover:bg-white/[0.03]">
                  <td className="px-4 py-4 align-top">
                    <Link
                      href={`/projects/${projectId}/datasets/${pipeline.base_dataset_id}/pipelines/${pipeline.id}`}
                      className="font-medium text-white hover:text-indigo-200"
                    >
                      {pipeline.name}
                    </Link>
                    <div className="mt-1 text-sm leading-6 text-slate-400">
                      {pipeline.description ?? "No pipeline description provided."}
                    </div>
                  </td>
                  <td className="px-4 py-4 align-top text-slate-300">{pipeline.status}</td>
                  <td className="px-4 py-4 align-top text-slate-400">{pipeline.step_count}</td>
                  <td className="px-4 py-4 align-top">
                    <div className="flex justify-end">
                      <Link
                        href={`/projects/${projectId}/datasets/${pipeline.base_dataset_id}/pipelines/${pipeline.id}`}
                        className="text-sm text-indigo-300 hover:text-indigo-200"
                      >
                        Open editor
                      </Link>
                    </div>
                  </td>
                  <td className="px-4 py-4 align-top">
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
