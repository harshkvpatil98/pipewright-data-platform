import { ProjectsPageView } from "@/features/projects/components/projects-page";
import { requireCurrentUser } from "@/lib/auth/server";
import { serverApiFetch } from "@/lib/api/server";
import type { ProjectListResponse } from "@platform/shared-types";

export default async function ProjectsPage() {
  const currentUser = await requireCurrentUser();
  const response = await serverApiFetch<ProjectListResponse>("/projects");
  return <ProjectsPageView currentUser={currentUser} projects={response.items} />;
}
