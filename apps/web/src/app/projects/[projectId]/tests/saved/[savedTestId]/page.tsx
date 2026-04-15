import { notFound } from "next/navigation";

import { SavedTestDetailPageView } from "@/features/comparisons/components/saved-test-detail-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { SavedStatisticalTestDetail } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string; savedTestId: string }>;
};

export default async function SavedTestDetailPage({ params }: PageProps) {
  const { projectId, savedTestId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const detail = await serverApiFetch<SavedStatisticalTestDetail>(
      `/projects/${projectId}/tests/saved/${savedTestId}`,
    );
    return <SavedTestDetailPageView currentUser={currentUser} projectId={projectId} detail={detail} />;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
