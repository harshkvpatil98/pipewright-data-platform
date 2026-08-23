import { notFound } from "next/navigation";

import { IncidentsPageView } from "@/features/incidents/components/incidents-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { IncidentListResponse } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export const metadata = { title: "Incidents" };

export default async function ProjectIncidentsPage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const incidents = await serverApiFetch<IncidentListResponse>(
      `/projects/${projectId}/incidents?status=open`,
    );
    return (
      <IncidentsPageView currentUser={currentUser} projectId={projectId} initial={incidents} />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
