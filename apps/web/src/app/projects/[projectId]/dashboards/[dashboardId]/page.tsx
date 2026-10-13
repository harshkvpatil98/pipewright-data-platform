import type { Metadata } from "next";
import { notFound } from "next/navigation";

import type { ChartListResponse, DashboardDetail } from "@platform/shared-types";

import { DashboardViewPage } from "@/features/reporting/components/dashboard-view-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";

type PageProps = {
  params: Promise<{ projectId: string; dashboardId: string }>;
};

/** The browser tab names the dashboard, so several open side by side can be told apart. */
export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { projectId, dashboardId } = await params;
  try {
    const record = await serverApiFetch<DashboardDetail>(`/projects/${projectId}/dashboards/${dashboardId}`);
    return { title: record.name };
  } catch {
    return { title: "Dashboard" };
  }
}

export default async function DashboardPage({ params }: PageProps) {
  const { projectId, dashboardId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const [dashboard, charts] = await Promise.all([
      serverApiFetch<DashboardDetail>(`/projects/${projectId}/dashboards/${dashboardId}`),
      serverApiFetch<ChartListResponse>(`/projects/${projectId}/charts`),
    ]);
    return (
      <DashboardViewPage
        currentUser={currentUser}
        projectId={projectId}
        initialDashboard={dashboard}
        charts={charts.items}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
