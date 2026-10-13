import { notFound } from "next/navigation";

import type {
  DatasetListResponse,
  PipelineRunListResponse,
  ProjectDetail,
  StreamSourceListResponse,
} from "@platform/shared-types";

import { ProjectDetailPageView } from "@/features/projects/components/project-detail-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";

type ProjectDetailPageProps = {
  params: Promise<{ projectId: string }>;
};

export const dynamic = "force-dynamic";

export default async function ProjectDetailPage({ params }: ProjectDetailPageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const [project, datasets, runs, feeds] = await Promise.all([
      serverApiFetch<ProjectDetail>(`/projects/${projectId}`),
      serverApiFetch<DatasetListResponse>(`/projects/${projectId}/datasets`),
      serverApiFetch<PipelineRunListResponse>(`/projects/${projectId}/runs`),
      // Only says which datasets are live feeds; never worth failing the page.
      serverApiFetch<StreamSourceListResponse>(`/projects/${projectId}/streams`).catch(() => ({
        items: [],
      })),
    ]);
    return (
      <ProjectDetailPageView
        currentUser={currentUser}
        project={project}
        datasets={datasets.items}
        runs={runs.items}
        feeds={feeds.items}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 401)) notFound();
    throw error;
  }
}
