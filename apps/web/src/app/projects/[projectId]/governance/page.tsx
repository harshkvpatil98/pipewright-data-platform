import { notFound } from "next/navigation";

import { GovernancePageView } from "@/features/enterprise/components/governance-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type {
  ErasureListResponse,
  RetentionListResponse,
  SecurityPolicyListResponse,
  UsageResponse,
} from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export const metadata = { title: "Governance" };

export default async function GovernancePage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const [policies, retention, erasures, usage] = await Promise.all([
      serverApiFetch<SecurityPolicyListResponse>(`/projects/${projectId}/security-policies`),
      serverApiFetch<RetentionListResponse>(`/projects/${projectId}/retention`),
      serverApiFetch<ErasureListResponse>(`/projects/${projectId}/erasures`),
      serverApiFetch<UsageResponse>(`/projects/${projectId}/usage`),
    ]);
    return (
      <GovernancePageView
        currentUser={currentUser}
        projectId={projectId}
        policies={policies}
        retention={retention}
        erasures={erasures}
        usage={usage}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
