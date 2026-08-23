import { notFound } from "next/navigation";

import { AssistantPageView } from "@/features/intelligence/components/assistant-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type {
  DocumentationResponse,
  LineageColumnListResponse,
  PiiScanResponse,
  RuleSuggestionResponse,
} from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string; datasetId: string }>;
};

export const metadata = { title: "Assistant" };

/** Analyses that need the stored file can fail on a dataset that has none. */
async function optional<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise;
  } catch {
    return null;
  }
}

export default async function AssistantPage({ params }: PageProps) {
  const { projectId, datasetId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const columns = await serverApiFetch<LineageColumnListResponse>(
      `/projects/${projectId}/datasets/${datasetId}/lineage/columns`,
    );
    const [pii, rules, documentation] = await Promise.all([
      optional(
        serverApiFetch<PiiScanResponse>(`/projects/${projectId}/datasets/${datasetId}/pii`),
      ),
      optional(
        serverApiFetch<RuleSuggestionResponse>(
          `/projects/${projectId}/datasets/${datasetId}/rule-suggestions`,
        ),
      ),
      optional(
        serverApiFetch<DocumentationResponse>(
          `/projects/${projectId}/datasets/${datasetId}/documentation`,
        ),
      ),
    ]);

    return (
      <AssistantPageView
        currentUser={currentUser}
        projectId={projectId}
        datasetId={datasetId}
        datasetName={pii?.dataset_name ?? documentation?.dataset.subject ?? "dataset"}
        columns={columns.columns}
        pii={pii}
        rules={rules}
        documentation={documentation}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
