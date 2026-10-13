import { ProjectsPageView } from "@/features/projects/components/projects-page";
import { requireCurrentUser } from "@/lib/auth/server";
import { serverApiFetch } from "@/lib/api/server";
import type { ProjectListResponse } from "@platform/shared-types";

export const metadata = { title: "Projects" };

type PageProps = { searchParams: Promise<{ new?: string }> };

export default async function ProjectsPage({ searchParams }: PageProps) {
  const currentUser = await requireCurrentUser();
  const [{ new: startNew }, response] = await Promise.all([
    searchParams,
    serverApiFetch<ProjectListResponse>("/projects"),
  ]);
  return (
    <ProjectsPageView
      currentUser={currentUser}
      projects={response.items}
      startCreating={startNew === "1"}
    />
  );
}
