import { notFound } from "next/navigation";

import { ChangesPageView } from "@/features/team/components/changes-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { ChangeRequestListResponse } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export const metadata = { title: "Changes" };

export default async function Page({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const initial = await serverApiFetch<ChangeRequestListResponse>(`/projects/${projectId}/changes`);
    return <ChangesPageView currentUser={currentUser} projectId={projectId} initial={initial} />;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
