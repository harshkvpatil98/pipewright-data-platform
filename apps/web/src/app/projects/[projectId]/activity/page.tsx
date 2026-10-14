import { notFound } from "next/navigation";

import type { ActivityResponse } from "@platform/shared-types";

import { ActivityPageView } from "@/features/activity/components/activity-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export const metadata = { title: "Activity" };

export default async function Page({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const initial = await serverApiFetch<ActivityResponse>(`/projects/${projectId}/activity`);
    return <ActivityPageView currentUser={currentUser} projectId={projectId} initial={initial} />;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
