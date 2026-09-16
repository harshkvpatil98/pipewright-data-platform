import { notFound } from "next/navigation";

import { SchedulesPageView } from "@/features/schedules/components/schedules-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { ScheduleListResponse, ScheduleType } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

function parseScheduleType(value: string | undefined): ScheduleType | null {
  if (
    value === "transformation_pipeline_run" ||
    value === "postgres_publish" ||
    value === "connector_schema_watch"
  ) {
    return value;
  }
  return null;
}

export default async function ProjectSchedulesPage({ params, searchParams }: PageProps) {
  const { projectId } = await params;
  const sp = await searchParams;
  const currentUser = await requireCurrentUser();

  const newRaw = sp.new;
  const initialOpenCreate = newRaw === "1" || newRaw === "true";
  const initialScheduleType = parseScheduleType(typeof sp.type === "string" ? sp.type : undefined);
  const initialPipelineId = typeof sp.pipelineId === "string" ? sp.pipelineId : null;
  const initialDatasetId = typeof sp.datasetId === "string" ? sp.datasetId : null;

  try {
    const data = await serverApiFetch<ScheduleListResponse>(`/projects/${projectId}/schedules`);
    return (
      <SchedulesPageView
        currentUser={currentUser}
        projectId={projectId}
        initialItems={data.items}
        initialOpenCreate={initialOpenCreate}
        initialScheduleType={initialScheduleType}
        initialPipelineId={initialPipelineId}
        initialDatasetId={initialDatasetId}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
