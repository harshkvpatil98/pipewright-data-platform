import { notFound } from "next/navigation";

import { ExtractionPageView } from "@/features/extraction/components/extraction-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type {
  ExtractionConnectionListResponse,
  ExtractionJobListResponse,
} from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export const metadata = { title: "Extraction" };

export default async function ProjectExtractionPage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    // Independent reads, so fetch them together rather than in series.
    const [connections, jobs] = await Promise.all([
      serverApiFetch<ExtractionConnectionListResponse>(
        `/projects/${projectId}/extraction/connections`,
      ),
      serverApiFetch<ExtractionJobListResponse>(`/projects/${projectId}/extraction/jobs`),
    ]);

    return (
      <ExtractionPageView
        currentUser={currentUser}
        projectId={projectId}
        initialConnections={connections.items}
        initialJobs={jobs.items}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
