import { notFound } from "next/navigation";

import { DatasetMetricsPageView } from "@/features/dataset-metrics/components/dataset-metrics-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { AnomalyScan, MetricHistory } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string; datasetId: string }>;
};

export const metadata = { title: "Metrics" };

export default async function DatasetMetricsPage({ params }: PageProps) {
  const { projectId, datasetId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const [history, anomalies] = await Promise.all([
      serverApiFetch<MetricHistory>(`/projects/${projectId}/datasets/${datasetId}/metrics`),
      serverApiFetch<AnomalyScan>(`/projects/${projectId}/datasets/${datasetId}/anomalies`),
    ]);
    return (
      <DatasetMetricsPageView
        currentUser={currentUser}
        projectId={projectId}
        datasetId={datasetId}
        initialHistory={history}
        initialAnomalies={anomalies}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
