import { notFound } from "next/navigation";

import type { DatasetListResponse, ProjectDetail, TransformationPipelineListResponse } from "@platform/shared-types";

import { PipelineListPageView } from "@/features/pipelines/components/pipeline-list-page";
import { ApiError } from "@/lib/api/errors";
import { requireCurrentUser } from "@/lib/auth/server";
import { serverApiFetch } from "@/lib/api/server";

type ProjectPipelinesPageProps = {
  params: Promise<{ projectId: string }>;
  searchParams?: Promise<{ datasetId?: string }>;
};

export default async function ProjectPipelinesPage({ params, searchParams }: ProjectPipelinesPageProps) {
  const { projectId } = await params;
  const resolvedSearchParams = searchParams ? await searchParams : undefined;
  const datasetId = resolvedSearchParams?.datasetId ?? null;
  const currentUser = await requireCurrentUser();

  try {
    const [project, datasets, pipelines] = await Promise.all([
      serverApiFetch<ProjectDetail>(`/projects/${projectId}`),
      serverApiFetch<DatasetListResponse>(`/projects/${projectId}/datasets`),
      datasetId
        ? serverApiFetch<TransformationPipelineListResponse>(`/projects/${projectId}/datasets/${datasetId}/pipelines`)
        : serverApiFetch<TransformationPipelineListResponse>(`/projects/${projectId}/pipelines`),
    ]);

    return (
      <PipelineListPageView
        currentUser={currentUser}
        project={project}
        pipelines={pipelines.items}
        datasets={datasets.items}
        activeDatasetId={datasetId}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
