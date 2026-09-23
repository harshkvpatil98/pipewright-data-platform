import type { OperatorDatasetsResponse } from "@platform/shared-types";

import { DatasetsSearchPageView } from "@/features/operator/components/datasets-search-page";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";

export const dynamic = "force-dynamic";

export default async function DatasetsPage() {
  const currentUser = await requireCurrentUser();
  const datasets = await serverApiFetch<OperatorDatasetsResponse>("/datasets");
  return <DatasetsSearchPageView currentUser={currentUser} initialDatasets={datasets.items} />;
}
