import { notFound } from "next/navigation";

import { DatasetContractPageView } from "@/features/contracts/components/dataset-contract-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { ContractHistoryResponse, DatasetContractResponse, DatasetRecord } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string; datasetId: string }>;
};

export const metadata = { title: "Contract" };

export default async function DatasetContractPage({ params }: PageProps) {
  const { projectId, datasetId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const [dataset, contract] = await Promise.all([
      serverApiFetch<DatasetRecord>(`/projects/${projectId}/datasets/${datasetId}`),
      serverApiFetch<DatasetContractResponse>(`/projects/${projectId}/datasets/${datasetId}/contract`),
    ]);
    const history = contract.contract
      ? await serverApiFetch<ContractHistoryResponse>(`/projects/${projectId}/datasets/${datasetId}/contract/history`)
      : { items: [] };
    return (
      <DatasetContractPageView
        currentUser={currentUser}
        projectId={projectId}
        dataset={{
          id: dataset.id,
          name: dataset.name,
          columns: (dataset.schema_json?.columns ?? []).map((column) => column.name),
          ready: dataset.ingestion_status === "succeeded",
        }}
        initial={contract}
        initialHistory={history.items}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
