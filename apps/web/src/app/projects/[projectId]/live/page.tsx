import { notFound } from "next/navigation";

import { LiveFeedsPageView } from "@/features/live/components/live-feeds-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type {
  ExtractionConnectionListResponse,
  LiveKindListResponse,
  StreamSourceListResponse,
} from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export const metadata = { title: "Live feeds" };

export default async function ProjectLiveFeedsPage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const [feeds, kinds, connections] = await Promise.all([
      serverApiFetch<StreamSourceListResponse>(`/projects/${projectId}/streams`),
      serverApiFetch<LiveKindListResponse>(`/projects/${projectId}/live/kinds`),
      serverApiFetch<ExtractionConnectionListResponse>(`/projects/${projectId}/extraction/connections`),
    ]);
    return (
      <LiveFeedsPageView
        currentUser={currentUser}
        projectId={projectId}
        feeds={feeds.items}
        kinds={kinds.items}
        connections={connections.items}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
