import { notFound } from "next/navigation";

import { ReportsPageView } from "@/features/reporting/components/reports-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type {
  ChartListResponse,
  DashboardListResponse,
  DatasetListResponse,
  ReportListResponse,
  ExternalNotificationTargetListResponse,
} from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export const metadata = { title: "Reports" };

export default async function ReportsPage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const [reports, datasets, charts, dashboards, targets] = await Promise.all([
      serverApiFetch<ReportListResponse>(`/projects/${projectId}/reports`),
      serverApiFetch<DatasetListResponse>(`/projects/${projectId}/datasets`),
      serverApiFetch<ChartListResponse>(`/projects/${projectId}/charts`),
      serverApiFetch<DashboardListResponse>(`/projects/${projectId}/dashboards`),
      serverApiFetch<ExternalNotificationTargetListResponse>(`/projects/${projectId}/notification-targets`),
    ]);
    return (
      <ReportsPageView
        currentUser={currentUser}
        projectId={projectId}
        initial={reports}
        datasets={datasets.items}
        charts={charts}
        dashboards={dashboards}
        targets={targets.items}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
