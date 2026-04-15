import { notFound, redirect } from "next/navigation";

import type { TransformationPipelineRecord } from "@platform/shared-types";
import { ApiError } from "@/lib/api/errors";
import { requireCurrentUser } from "@/lib/auth/server";
import { serverApiFetch } from "@/lib/api/server";

type PipelineEditorPageProps = {
  params: Promise<{ projectId: string; pipelineId: string }>;
};

export default async function PipelineEditorPage({ params }: PipelineEditorPageProps) {
  const { projectId, pipelineId } = await params;
  await requireCurrentUser();

  try {
    const pipeline = await serverApiFetch<TransformationPipelineRecord>(`/projects/${projectId}/pipelines/${pipelineId}`);
    redirect(`/projects/${projectId}/datasets/${pipeline.base_dataset_id}/pipelines/${pipeline.id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
