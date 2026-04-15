import { notFound } from "next/navigation";

import { DatasetComparePageView } from "@/features/comparisons/components/dataset-compare-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { DatasetComparisonSummary } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string; datasetId: string; otherDatasetId: string }>;
};

export default async function DatasetComparePage({ params }: PageProps) {
  const { projectId, datasetId, otherDatasetId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const comparison = await serverApiFetch<DatasetComparisonSummary>(
      `/projects/${projectId}/datasets/${datasetId}/compare/${otherDatasetId}`,
    );
    return <DatasetComparePageView currentUser={currentUser} projectId={projectId} comparison={comparison} />;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
