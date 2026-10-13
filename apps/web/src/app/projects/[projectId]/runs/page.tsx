import { notFound } from "next/navigation";

import type { PipelineRunListResponse } from "@platform/shared-types";

import { ProjectRunsPageView } from "@/features/operator/components/project-runs-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export const metadata = { title: "Runs" };
export const dynamic = "force-dynamic";

export default async function ProjectRunsPage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const runs = await serverApiFetch<PipelineRunListResponse>(`/projects/${projectId}/runs`);
    return <ProjectRunsPageView currentUser={currentUser} projectId={projectId} runs={runs.items} />;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
}
