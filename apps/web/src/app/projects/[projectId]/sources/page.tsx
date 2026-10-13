import { notFound } from "next/navigation";

import { ExtractionPageView } from "@/features/extraction/components/extraction-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type {
  DatasetListResponse,
  ExtractionConnectionListResponse,
  ExtractionJobListResponse,
  PipelineRunListResponse,
  StreamSourceListResponse,
} from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ connect?: string }>;
};

export const metadata = { title: "Sources" };

export default async function ProjectSourcesPage({ params, searchParams }: PageProps) {
  const { projectId } = await params;
  const { connect } = await searchParams;
  const currentUser = await requireCurrentUser();

  try {
    // Independent reads, so fetch them together rather than in series.
    const [connections, jobs, streams, datasets, runs] = await Promise.all([
      serverApiFetch<ExtractionConnectionListResponse>(
        `/projects/${projectId}/extraction/connections`,
      ),
      serverApiFetch<ExtractionJobListResponse>(`/projects/${projectId}/extraction/jobs`),
      serverApiFetch<StreamSourceListResponse>(`/projects/${projectId}/streams`),
      serverApiFetch<DatasetListResponse>(`/projects/${projectId}/datasets`),
      serverApiFetch<PipelineRunListResponse>(`/projects/${projectId}/runs`).catch(() => ({
        items: [],
      })),
    ]);

    return (
      <ExtractionPageView
        currentUser={currentUser}
        initialStreams={streams.items}
        projectId={projectId}
        initialConnections={connections.items}
        initialJobs={jobs.items}
        datasets={datasets.items}
        runs={runs.items}
        startConnecting={connect === "1"}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
