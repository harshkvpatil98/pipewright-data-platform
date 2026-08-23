import { notFound } from "next/navigation";

import { TableEditorPage } from "@/features/writeback/table-editor-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { ProjectDetail } from "@platform/shared-types";

type PageProps = { params: Promise<{ projectId: string }> };

type ConnectionList = {
  items: { id: string; name: string; connector_type: string; status: string }[];
};

export const metadata = { title: "Table editor" };

export default async function ProjectTableEditorPage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const [project, connections] = await Promise.all([
      serverApiFetch<ProjectDetail>(`/projects/${projectId}`),
      serverApiFetch<ConnectionList>(`/projects/${projectId}/extraction/connections`),
    ]);

    // Only live database connections can be written back to. A file source has
    // no rows to address.
    const writable = connections.items.filter((item) => item.status === "active");

    return (
      <TableEditorPage
        currentUser={currentUser}
        projectId={projectId}
        projectName={project.name}
        projectEnvironment={project.environment ?? "development"}
        connections={writable}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
