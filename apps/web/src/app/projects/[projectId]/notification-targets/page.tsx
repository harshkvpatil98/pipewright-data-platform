import { notFound } from "next/navigation";

import { NotificationTargetsPageView } from "@/features/notifications/components/notification-targets-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { ExternalNotificationTargetListResponse } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export default async function ProjectNotificationTargetsPage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const data = await serverApiFetch<ExternalNotificationTargetListResponse>(
      `/projects/${projectId}/notification-targets`,
    );
    return (
      <NotificationTargetsPageView currentUser={currentUser} projectId={projectId} initialItems={data.items} />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
