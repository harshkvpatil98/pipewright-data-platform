import { notFound } from "next/navigation";

import type { ProjectDetail } from "@platform/shared-types";

import { AppShell } from "@/components/layout/app-shell";
import { ProjectBundlePanel } from "@/features/projects/components/project-bundle-panel";
import { ProjectSettingsPanel } from "@/features/projects/components/project-settings-panel";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export const metadata = { title: "Project settings" };

export default async function ProjectSettingsPage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  let project: ProjectDetail;
  try {
    project = await serverApiFetch<ProjectDetail>(`/projects/${projectId}`);
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 401)) notFound();
    throw error;
  }

  return (
    <AppShell
      currentUser={currentUser}
      title="Project settings"
      subtitle="Rename, describe, move, archive or delete this project."
    >
      <div className="space-y-6">
        <ProjectSettingsPanel project={project} />
        <ProjectBundlePanel projectId={project.id} projectName={project.name} />
      </div>
    </AppShell>
  );
}
