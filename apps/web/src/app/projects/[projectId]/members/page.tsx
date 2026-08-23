import { notFound } from "next/navigation";

import { MembersPageView } from "@/features/team/components/members-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { MemberListResponse } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export const metadata = { title: "People" };

export default async function Page({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const initial = await serverApiFetch<MemberListResponse>(`/projects/${projectId}/members`);
    return <MembersPageView currentUser={currentUser} projectId={projectId} initial={initial} />;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
