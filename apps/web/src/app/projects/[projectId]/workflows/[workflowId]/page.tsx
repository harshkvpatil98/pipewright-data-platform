import { notFound } from "next/navigation";

import { WorkflowEditorPage } from "@/features/workflows/components/workflow-editor-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type {
  DatasetListResponse,
  DestinationListResponse,
  ExtractionJobListResponse,
  ProjectDetail,
  WorkflowDetail,
} from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string; workflowId: string }>;
};

export const metadata = { title: "Workflow" };

export default async function WorkflowEditorRoute({ params }: PageProps) {
  const { projectId, workflowId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    // Everything the node inspector needs to offer real choices, fetched
    // together so the editor opens ready to configure rather than loading.
    const [project, workflow, jobs, pipelines, destinations, datasets] = await Promise.all([
      serverApiFetch<ProjectDetail>(`/projects/${projectId}`),
      serverApiFetch<WorkflowDetail>(`/projects/${projectId}/workflows/${workflowId}`),
      serverApiFetch<ExtractionJobListResponse>(`/projects/${projectId}/extraction/jobs`).catch(
        () => ({ items: [] }),
      ),
      serverApiFetch<{ items: { id: string; name: string }[] }>(
        `/projects/${projectId}/pipelines`,
      ).catch(() => ({ items: [] })),
      serverApiFetch<DestinationListResponse>(`/projects/${projectId}/destinations`).catch(() => ({
        items: [],
      })),
      serverApiFetch<DatasetListResponse>(`/projects/${projectId}/datasets`).catch(() => ({
        items: [],
      })),
    ]);

    return (
      <WorkflowEditorPage
        currentUser={currentUser}
        projectId={projectId}
        projectName={project.name}
        workflow={workflow}
        options={{
          extractionJobs: jobs.items.map((job) => ({ id: job.id, name: job.name })),
          pipelines: pipelines.items.map((pipeline) => ({
            id: pipeline.id,
            name: pipeline.name,
          })),
          destinations: destinations.items.map((destination) => ({
            id: destination.id,
            name: destination.name,
          })),
          datasets: datasets.items.filter((dataset) => dataset.status === "ready"),
        }}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
