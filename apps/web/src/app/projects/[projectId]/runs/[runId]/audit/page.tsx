import { notFound } from "next/navigation";

import { RunAuditPageView } from "@/features/audit/components/run-audit-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { RunAuditSummary } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string; runId: string }>;
};

export default async function RunAuditPage({ params }: PageProps) {
  const { projectId, runId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const audit = await serverApiFetch<RunAuditSummary>(`/projects/${projectId}/runs/${runId}/audit`);
    return <RunAuditPageView currentUser={currentUser} projectId={projectId} audit={audit} />;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
