import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { DatasetDetailPageView } from "@/features/datasets/components/dataset-detail-page";
import { ApiError } from "@/lib/api/errors";
import { requireCurrentUser } from "@/lib/auth/server";
import { serverApiFetch } from "@/lib/api/server";
import type {
  DataContractListResponse,
  DatasetVersionListResponse,
  DatasetPreview,
  DatasetProfile,
  DatasetRecord,
  DatasetTransformationSuggestionsResponse,
  PipelineRunRecord,
  TransformationPipelineListResponse,
  TransformationPipelineRecord,
} from "@platform/shared-types";

type DatasetDetailPageProps = {
  params: Promise<{ projectId: string; datasetId: string }>;
};

/** The browser tab names the dataset, so several open side by side can be told apart. */
export async function generateMetadata({ params }: DatasetDetailPageProps): Promise<Metadata> {
  const { projectId, datasetId } = await params;
  try {
    const record = await serverApiFetch<DatasetRecord>(`/projects/${projectId}/datasets/${datasetId}`);
    return { title: record.name };
  } catch {
    return { title: "Dataset" };
  }
}

export default async function DatasetDetailPage({ params }: DatasetDetailPageProps) {
  const { projectId, datasetId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const dataset = await serverApiFetch<DatasetRecord>(`/projects/${projectId}/datasets/${datasetId}`);

    let pipelinesForDataset: TransformationPipelineRecord[] = [];
    let lineageParent: DatasetRecord | null = null;
    let lineagePipeline: TransformationPipelineRecord | null = null;

    if (!dataset.is_derived) {
      const pipelineList = await serverApiFetch<TransformationPipelineListResponse>(
        `/projects/${projectId}/datasets/${datasetId}/pipelines`,
      );
      pipelinesForDataset = pipelineList.items;
    } else {
      try {
        if (dataset.parent_dataset_id) {
          lineageParent = await serverApiFetch<DatasetRecord>(
            `/projects/${projectId}/datasets/${dataset.parent_dataset_id}`,
          );
        }
      } catch {
        lineageParent = null;
      }
      try {
        if (dataset.created_from_pipeline_id) {
          lineagePipeline = await serverApiFetch<TransformationPipelineRecord>(
            `/projects/${projectId}/pipelines/${dataset.created_from_pipeline_id}`,
          );
        }
      } catch {
        lineagePipeline = null;
      }
    }

    const [preview, profile, relatedRun, suggestionsPayload, contracts, versions] = await Promise.all([
      serverApiFetch<DatasetPreview>(`/projects/${projectId}/datasets/${datasetId}/preview`),
      serverApiFetch<DatasetProfile>(`/projects/${projectId}/datasets/${datasetId}/profile`),
      dataset.pipeline_run_id
        ? serverApiFetch<PipelineRunRecord>(`/projects/${projectId}/runs/${dataset.pipeline_run_id}`)
        : Promise.resolve(null),
      !dataset.is_derived
        ? serverApiFetch<DatasetTransformationSuggestionsResponse>(
            `/projects/${projectId}/datasets/${datasetId}/suggestions`,
          ).catch(() => null)
        : Promise.resolve(null),
      // Its contract's state, for the chip; one list, so no request per dataset.
      serverApiFetch<DataContractListResponse>(`/projects/${projectId}/contracts`).catch(() => null),
      // Which version its rows are from, to name a row by its number (C2).
      serverApiFetch<DatasetVersionListResponse>(`/projects/${projectId}/datasets/${datasetId}/versions`).catch(() => null),
    ]);

    return (
      <DatasetDetailPageView
        currentUser={currentUser}
        projectId={projectId}
        dataset={dataset}
        preview={preview}
        profile={profile.profile}
        relatedRun={relatedRun}
        pipelinesForDataset={pipelinesForDataset}
        lineageParent={lineageParent}
        lineagePipeline={lineagePipeline}
        transformationSuggestions={suggestionsPayload?.suggestions ?? []}
        contract={contracts?.items.find((item) => item.dataset_id === datasetId) ?? null}
        currentVersion={versions?.current_version ?? null}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
