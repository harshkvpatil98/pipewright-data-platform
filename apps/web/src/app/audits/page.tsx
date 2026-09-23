import type { AuditCenterResponse } from "@platform/shared-types";

import { AuditCenterPageView } from "@/features/audit/components/audit-center-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";

export const dynamic = "force-dynamic";

export default async function AuditsPage() {
  const currentUser = await requireCurrentUser();
  try {
    const initial = await serverApiFetch<AuditCenterResponse>("/audits?limit=100");
    return <AuditCenterPageView currentUser={currentUser} initial={initial} forbidden={false} />;
  } catch (error) {
    // The Audit Center is admin-only; a non-admin gets a clear message, not a crash.
    if (error instanceof ApiError && error.status === 403) {
      return <AuditCenterPageView currentUser={currentUser} initial={null} forbidden />;
    }
    throw error;
  }
}
