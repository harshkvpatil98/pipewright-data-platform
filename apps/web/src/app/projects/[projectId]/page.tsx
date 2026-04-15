import { notFound } from "next/navigation";

import { ProjectDetailPageView } from "@/features/projects/components/project-detail-page";
import { ApiError } from "@/lib/api/errors";
import { requireCurrentUser } from "@/lib/auth/server";
import { serverApiFetch } from "@/lib/api/server";
import type {
  DatasetListResponse,
  PipelineRunListResponse,
  ProjectDetail,
  SourceListResponse,
} from "@platform/shared-types";

type ProjectDetailPageProps = {
  params: Promise<{ projectId: string }>;
};

export default async function ProjectDetailPage({ params }: ProjectDetailPageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();
  let project: ProjectDetail;
  let sources: SourceListResponse;
  let datasets: DatasetListResponse;
  let runs: PipelineRunListResponse;

  try {
    [project, sources, datasets, runs] = await Promise.all([
      serverApiFetch<ProjectDetail>(`/projects/${projectId}`),
      serverApiFetch<SourceListResponse>(`/projects/${projectId}/sources`),
      serverApiFetch<DatasetListResponse>(`/projects/${projectId}/datasets`),
      serverApiFetch<PipelineRunListResponse>(`/projects/${projectId}/runs`),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    if (error instanceof ApiError && error.status === 401) {
      notFound();
    }
    throw error;
  }

  return (
    <ProjectDetailPageView
      currentUser={currentUser}
      project={project}
      sources={sources.items}
      datasets={datasets.items}
      runs={runs.items}
    />
  );
}
