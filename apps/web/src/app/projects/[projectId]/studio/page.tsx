import { notFound } from "next/navigation";

import { StudioPage } from "@/features/studio/studio-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type {
  DatasetListResponse,
  ProjectDetail,
  RecipeSharedCopy,
  TransformationPipelineRecord,
} from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ dataset?: string; recipe?: string }>;
};

export const metadata = { title: "Studio" };

export default async function ProjectStudioPage({ params, searchParams }: PageProps) {
  const { projectId } = await params;
  const { dataset, recipe } = await searchParams;
  const currentUser = await requireCurrentUser();

  try {
    // The project read stays: it is what turns a wrong id into a 404.
    const [, datasets, opened, shared] = await Promise.all([
      serverApiFetch<ProjectDetail>(`/projects/${projectId}`),
      serverApiFetch<DatasetListResponse>(`/projects/${projectId}/datasets`),
      recipe
        ? serverApiFetch<TransformationPipelineRecord>(`/projects/${projectId}/pipelines/${recipe}`)
        : Promise.resolve(null),
      // The recipe's shared working copy and what this person may do (C2).
      recipe
        ? serverApiFetch<RecipeSharedCopy>(`/projects/${projectId}/pipelines/${recipe}/shared`).catch(() => null)
        : Promise.resolve(null),
    ]);

    // Only datasets with a stored artifact can be previewed.
    const usable = datasets.items.filter((item) => item.status === "ready");

    return (
      <StudioPage
        // A different recipe is a different editing session, not an update.
        key={opened?.id ?? "new"}
        currentUser={currentUser}
        projectId={projectId}
        datasets={usable}
        initialDatasetId={dataset}
        recipe={opened}
        shared={shared}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
