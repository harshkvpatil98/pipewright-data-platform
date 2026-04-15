import { notFound } from "next/navigation";

import { BiConnectionsPageView } from "@/features/bi-connections/components/bi-connections-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { BiIntegrationListResponse } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export default async function ProjectBiConnectionsPage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const data = await serverApiFetch<BiIntegrationListResponse>(`/projects/${projectId}/bi-connections`);
    return <BiConnectionsPageView currentUser={currentUser} projectId={projectId} initialItems={data.items} />;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
