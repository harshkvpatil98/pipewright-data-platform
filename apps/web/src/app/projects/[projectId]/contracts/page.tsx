import { notFound } from "next/navigation";

import { ContractsPageView } from "@/features/contracts/components/contracts-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { DataContractListResponse, DatasetListResponse } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export const metadata = { title: "Contracts" };

export default async function ProjectContractsPage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const [contracts, datasets] = await Promise.all([
      serverApiFetch<DataContractListResponse>(`/projects/${projectId}/contracts`),
      serverApiFetch<DatasetListResponse>(`/projects/${projectId}/datasets`),
    ]);
    return (
      <ContractsPageView
        currentUser={currentUser}
        projectId={projectId}
        contracts={contracts.items}
        datasets={datasets.items
          .filter((dataset) => dataset.ingestion_status === "succeeded")
          .map((dataset) => ({ id: dataset.id, name: dataset.name }))}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
