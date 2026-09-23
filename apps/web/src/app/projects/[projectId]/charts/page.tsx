import { notFound } from "next/navigation";

import { ChartBuilderPageView } from "@/features/reporting/components/chart-builder-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { ChartListResponse, DatasetListResponse,
  MetricListResponse,
} from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export const metadata = { title: "Charts" };

export default async function ChartsPage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const [datasets, charts, metrics] = await Promise.all([
      serverApiFetch<DatasetListResponse>(`/projects/${projectId}/datasets`),
      serverApiFetch<ChartListResponse>(`/projects/${projectId}/charts`),
      serverApiFetch<MetricListResponse>(`/projects/${projectId}/metrics`),
    ]);
    return (
      <ChartBuilderPageView
        currentUser={currentUser}
        projectId={projectId}
        datasets={datasets.items}
        charts={charts}
        metrics={metrics.items}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
