import type { OperatorRunsResponse } from "@platform/shared-types";

import { RunsPageView } from "@/features/operator/components/runs-page";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";

export const dynamic = "force-dynamic";

export default async function RunsPage() {
  const currentUser = await requireCurrentUser();
  const runs = await serverApiFetch<OperatorRunsResponse>("/runs");
  return <RunsPageView currentUser={currentUser} initialRuns={runs.items} />;
}
