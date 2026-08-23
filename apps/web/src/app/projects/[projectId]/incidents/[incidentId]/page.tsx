import { notFound } from "next/navigation";

import { IncidentDetailPageView } from "@/features/incidents/components/incident-detail-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { IncidentDetail } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string; incidentId: string }>;
};

export const metadata = { title: "Incident" };

export default async function IncidentPage({ params }: PageProps) {
  const { projectId, incidentId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const incident = await serverApiFetch<IncidentDetail>(
      `/projects/${projectId}/incidents/${incidentId}`,
    );
    return (
      <IncidentDetailPageView
        currentUser={currentUser}
        projectId={projectId}
        initial={incident}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
