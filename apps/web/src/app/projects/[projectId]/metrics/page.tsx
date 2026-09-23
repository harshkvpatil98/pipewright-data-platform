import { notFound } from "next/navigation";

import type { DatasetListResponse, MetricListResponse } from "@platform/shared-types";

import { MetricsPageView } from "@/features/reporting/components/metrics-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";

type PageProps = { params: Promise<{ projectId: string }> };

export const metadata = { title: "Metrics" };

export default async function MetricsPage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();
  try {
    const [metrics, datasets] = await Promise.all([
      serverApiFetch<MetricListResponse>(`/projects/${projectId}/metrics`),
      serverApiFetch<DatasetListResponse>(`/projects/${projectId}/datasets`),
    ]);
    return (
      <MetricsPageView
        currentUser={currentUser}
        projectId={projectId}
        initial={metrics.items}
        datasets={datasets.items}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
}
