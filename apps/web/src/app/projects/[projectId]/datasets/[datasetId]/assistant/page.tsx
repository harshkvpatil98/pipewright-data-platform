import { notFound } from "next/navigation";

import { AssistantPageView } from "@/features/intelligence/components/assistant-page";
import { ApiError, extractErrorMessage } from "@/lib/api/errors";
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

/**
 * An analysis that may be refused (a dataset with no stored file, or one too
 * large to read), with the refusal's reason so the page can say why.
 */
async function optional<T>(promise: Promise<T>): Promise<{ value: T | null; problem: string | null }> {
  try {
    return { value: await promise, problem: null };
  } catch (error) {
    return { value: null, problem: extractErrorMessage(error) };
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
        datasetName={pii.value?.dataset_name ?? documentation.value?.dataset.subject ?? "dataset"}
        columns={columns.columns}
        pii={pii.value}
        rules={rules.value}
        documentation={documentation.value}
        problems={{ pii: pii.problem, rules: rules.problem, documentation: documentation.problem }}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
