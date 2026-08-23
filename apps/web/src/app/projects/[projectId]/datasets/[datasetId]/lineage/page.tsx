import { notFound } from "next/navigation";

import { LineagePageView } from "@/features/lineage/components/lineage-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { DatasetLineage } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string; datasetId: string }>;
};

export const metadata = { title: "Lineage" };

export default async function DatasetLineagePage({ params }: PageProps) {
  const { projectId, datasetId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const lineage = await serverApiFetch<DatasetLineage>(
      `/projects/${projectId}/datasets/${datasetId}/lineage`,
    );
    return (
      <LineagePageView
        currentUser={currentUser}
        projectId={projectId}
        datasetId={datasetId}
        initial={lineage}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
