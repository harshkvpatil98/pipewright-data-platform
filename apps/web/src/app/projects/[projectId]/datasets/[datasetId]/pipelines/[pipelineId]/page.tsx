import { notFound } from "next/navigation";

import type { DatasetListResponse, ProjectDetail, TransformationPipelineRecord } from "@platform/shared-types";

import { PipelineEditorPageView } from "@/features/pipelines/components/pipeline-editor-page";
import { ApiError } from "@/lib/api/errors";
import { requireCurrentUser } from "@/lib/auth/server";
import { serverApiFetch } from "@/lib/api/server";

type DatasetPipelineEditorPageProps = {
  params: Promise<{ projectId: string; datasetId: string; pipelineId: string }>;
};

export default async function DatasetPipelineEditorPage({ params }: DatasetPipelineEditorPageProps) {
  const { projectId, datasetId, pipelineId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const [project, datasets, pipeline] = await Promise.all([
      serverApiFetch<ProjectDetail>(`/projects/${projectId}`),
      serverApiFetch<DatasetListResponse>(`/projects/${projectId}/datasets`),
      serverApiFetch<TransformationPipelineRecord>(`/projects/${projectId}/pipelines/${pipelineId}`),
    ]);

    if (pipeline.base_dataset_id !== datasetId) {
      notFound();
    }

    return (
      <PipelineEditorPageView
        currentUser={currentUser}
        project={project}
        datasets={datasets.items}
        pipeline={pipeline}
        initialDatasetId={pipeline.base_dataset_id}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
