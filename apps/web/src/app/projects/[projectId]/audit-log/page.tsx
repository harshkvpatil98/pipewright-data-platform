import { notFound } from "next/navigation";

import { AuditLogPageView } from "@/features/team/components/audit-log-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { AuditListResponse } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export const metadata = { title: "Audit log" };

export default async function Page({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const initial = await serverApiFetch<AuditListResponse>(`/projects/${projectId}/audit-log`);
    return <AuditLogPageView currentUser={currentUser} projectId={projectId} initial={initial} />;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
