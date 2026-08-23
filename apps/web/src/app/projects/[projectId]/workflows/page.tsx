import { notFound } from "next/navigation";

import { WorkflowListPage } from "@/features/workflows/components/workflow-list-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { ProjectDetail, WorkflowListResponse } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export const metadata = { title: "Workflows" };

export default async function ProjectWorkflowsPage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const [project, workflows] = await Promise.all([
      serverApiFetch<ProjectDetail>(`/projects/${projectId}`),
      serverApiFetch<WorkflowListResponse>(`/projects/${projectId}/workflows`),
    ]);

    return (
      <WorkflowListPage
        currentUser={currentUser}
        projectId={projectId}
        projectName={project.name}
        initialWorkflows={workflows.items}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
