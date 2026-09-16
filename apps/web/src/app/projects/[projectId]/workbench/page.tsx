import { notFound } from "next/navigation";

import { WorkbenchPage } from "@/features/workbench/workbench-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { ProjectDetail } from "@platform/shared-types";

type PageProps = { params: Promise<{ projectId: string }> };

type ConnectionList = {
  items: { id: string; name: string; connector_type: string; status: string }[];
};

export const metadata = { title: "SQL workbench" };

export default async function ProjectWorkbenchPage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const [project, connections] = await Promise.all([
      serverApiFetch<ProjectDetail>(`/projects/${projectId}`),
      serverApiFetch<ConnectionList>(`/projects/${projectId}/extraction/connections`),
    ]);

    return (
      <WorkbenchPage
        currentUser={currentUser}
        projectId={projectId}
        projectName={project.name}
        projectEnvironment={project.environment ?? "development"}
        connections={connections.items.filter((item) => item.status === "active")}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
