import { notFound } from "next/navigation";

import type { DatasetListResponse, ProjectDetail, TransformationStep } from "@platform/shared-types";

import { PipelineEditorPageView } from "@/features/pipelines/components/pipeline-editor-page";
import { ApiError } from "@/lib/api/errors";
import { requireCurrentUser } from "@/lib/auth/server";
import { serverApiFetch } from "@/lib/api/server";

type NewPipelinePageProps = {
  params: Promise<{ projectId: string }>;
  searchParams?: Promise<{ sourceDatasetId?: string; starterSteps?: string }>;
};

function parseStarterSteps(raw: string | undefined): TransformationStep[] | null {
  if (!raw?.trim()) {
    return null;
  }
  try {
    const decoded = decodeURIComponent(raw);
    const parsed: unknown = JSON.parse(decoded);
    if (!Array.isArray(parsed) || parsed.length === 0) {
      return null;
    }
    return parsed as TransformationStep[];
  } catch {
    return null;
  }
}

export default async function NewPipelinePage({ params, searchParams }: NewPipelinePageProps) {
  const { projectId } = await params;
  const resolvedSearchParams = searchParams ? await searchParams : undefined;
  const sourceDatasetId = resolvedSearchParams?.sourceDatasetId ?? null;
  const starterSteps = parseStarterSteps(resolvedSearchParams?.starterSteps);
  const currentUser = await requireCurrentUser();

  try {
    const [project, datasets] = await Promise.all([
      serverApiFetch<ProjectDetail>(`/projects/${projectId}`),
      serverApiFetch<DatasetListResponse>(`/projects/${projectId}/datasets`),
    ]);

    return (
      <PipelineEditorPageView
        currentUser={currentUser}
        project={project}
        datasets={datasets.items}
        pipeline={null}
        initialDatasetId={sourceDatasetId}
        initialStarterSteps={starterSteps}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
