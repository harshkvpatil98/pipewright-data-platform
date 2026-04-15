import { notFound } from "next/navigation";

import { SavedTestsListPageView } from "@/features/comparisons/components/saved-tests-list-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { SavedStatisticalTestListResponse } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ left?: string; right?: string }>;
};

export default async function SavedTestsListPage({ params, searchParams }: PageProps) {
  const { projectId } = await params;
  const sp = await searchParams;
  const currentUser = await requireCurrentUser();

  const qs = new URLSearchParams();
  if (sp.left) {
    qs.set("left_dataset_id", sp.left);
  }
  if (sp.right) {
    qs.set("right_dataset_id", sp.right);
  }
  const suffix = qs.toString() ? `?${qs.toString()}` : "";

  try {
    const data = await serverApiFetch<SavedStatisticalTestListResponse>(
      `/projects/${projectId}/tests/saved${suffix}`,
    );
    return <SavedTestsListPageView currentUser={currentUser} projectId={projectId} items={data.items} />;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
