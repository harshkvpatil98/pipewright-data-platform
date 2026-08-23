import { notFound } from "next/navigation";

import { StudioPage } from "@/features/studio/studio-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { DatasetListResponse, ProjectDetail } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ dataset?: string }>;
};

export const metadata = { title: "Studio" };

export default async function ProjectStudioPage({ params, searchParams }: PageProps) {
  const { projectId } = await params;
  const { dataset } = await searchParams;
  const currentUser = await requireCurrentUser();

  try {
    const [project, datasets] = await Promise.all([
      serverApiFetch<ProjectDetail>(`/projects/${projectId}`),
      serverApiFetch<DatasetListResponse>(`/projects/${projectId}/datasets`),
    ]);

    // Only datasets with a stored artifact can be previewed.
    const usable = datasets.items.filter((item) => item.status === "ready");

    return (
      <StudioPage
        currentUser={currentUser}
        projectId={projectId}
        projectName={project.name}
        datasets={usable}
        initialDatasetId={dataset}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
