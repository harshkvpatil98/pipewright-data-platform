import { notFound } from "next/navigation";

import type {
  DatasetListResponse,
  PipelineRunListResponse,
  StreamSourceListResponse,
} from "@platform/shared-types";

import { DatasetsListPageView } from "@/features/datasets/components/datasets-list-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export const metadata = { title: "Datasets" };

export default async function ProjectDatasetsPage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    // Runs and feeds say where each dataset came from; neither is essential,
    // so a failure there shows "Other" rather than no page.
    const [datasets, runs, feeds] = await Promise.all([
      serverApiFetch<DatasetListResponse>(`/projects/${projectId}/datasets`),
      serverApiFetch<PipelineRunListResponse>(`/projects/${projectId}/runs`).catch(() => ({
        items: [],
      })),
      serverApiFetch<StreamSourceListResponse>(`/projects/${projectId}/streams`).catch(() => ({
        items: [],
      })),
    ]);
    return (
      <DatasetsListPageView
        currentUser={currentUser}
        projectId={projectId}
        datasets={datasets.items}
        runs={runs.items}
        feeds={feeds.items}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
}
