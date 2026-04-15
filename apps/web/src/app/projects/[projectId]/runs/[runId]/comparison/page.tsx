import { notFound } from "next/navigation";

import { RunComparisonPageView } from "@/features/comparisons/components/run-comparison-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { RunComparisonSummary } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string; runId: string }>;
};

export default async function RunComparisonPage({ params }: PageProps) {
  const { projectId, runId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const comparison = await serverApiFetch<RunComparisonSummary>(
      `/projects/${projectId}/runs/${runId}/comparison`,
    );
    return <RunComparisonPageView currentUser={currentUser} projectId={projectId} comparison={comparison} />;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
