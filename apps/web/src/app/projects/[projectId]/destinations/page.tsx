import { notFound } from "next/navigation";

import { DestinationsPageView } from "@/features/destinations/components/destinations-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { DestinationListResponse } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export default async function ProjectDestinationsPage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const data = await serverApiFetch<DestinationListResponse>(`/projects/${projectId}/destinations`);
    return <DestinationsPageView currentUser={currentUser} projectId={projectId} initialItems={data.items} />;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
