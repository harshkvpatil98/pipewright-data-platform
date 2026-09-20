import { DashboardsPageView } from "@/features/reporting/components/dashboards-page";
import { requireCurrentUser } from "@/lib/auth/server";
import { serverApiFetch } from "@/lib/api/server";
import type { ChartListResponse, DashboardListResponse } from "@platform/shared-types";

type DashboardsPageProps = {
  params: Promise<{ projectId: string }>;
};

export default async function DashboardsPage({ params }: DashboardsPageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  const [dashboards, charts] = await Promise.all([
    serverApiFetch<DashboardListResponse>(`/projects/${projectId}/dashboards`),
    serverApiFetch<ChartListResponse>(`/projects/${projectId}/charts`),
  ]);

  return (
    <DashboardsPageView
      currentUser={currentUser}
      projectId={projectId}
      dashboards={dashboards.items}
      charts={charts.items}
    />
  );
}
