import { notFound } from "next/navigation";

import { DatasetAuditPageView } from "@/features/audit/components/dataset-audit-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { DatasetAuditSummary } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string; datasetId: string }>;
};

export default async function DatasetAuditPage({ params }: PageProps) {
  const { projectId, datasetId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const audit = await serverApiFetch<DatasetAuditSummary>(
      `/projects/${projectId}/datasets/${datasetId}/audit`,
    );
    return <DatasetAuditPageView currentUser={currentUser} projectId={projectId} audit={audit} />;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
