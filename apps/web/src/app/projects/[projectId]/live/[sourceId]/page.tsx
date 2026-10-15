import { notFound } from "next/navigation";

import { LiveFeedPageView } from "@/features/live/components/live-feed-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type {
  DatasetListResponse,
  ExtractionConnectionListResponse,
  LiveKindListResponse,
  LiveRecipeListResponse,
  StreamEvent,
  StreamSource,
  ThroughputResponse,
  TransformationPipelineListResponse,
} from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string; sourceId: string }>;
};

export async function generateMetadata({ params }: PageProps) {
  const { projectId, sourceId } = await params;
  try {
    const feed = await serverApiFetch<StreamSource>(`/projects/${projectId}/streams/${sourceId}`);
    return { title: feed.name };
  } catch {
    return { title: "Live feed" };
  }
}

export default async function ProjectLiveFeedPage({ params }: PageProps) {
  const { projectId, sourceId } = await params;
  const currentUser = await requireCurrentUser();
  const base = `/projects/${projectId}/streams/${sourceId}`;

  try {
    const [feed, kinds, connections, throughput, events, liveRecipes, recipes, datasets] = await Promise.all([
      serverApiFetch<StreamSource>(base),
      serverApiFetch<LiveKindListResponse>(`/projects/${projectId}/live/kinds`),
      serverApiFetch<ExtractionConnectionListResponse>(`/projects/${projectId}/extraction/connections`),
      serverApiFetch<ThroughputResponse>(`${base}/throughput`),
      serverApiFetch<{ items: StreamEvent[] }>(`${base}/events?limit=20`),
      serverApiFetch<LiveRecipeListResponse>(`${base}/recipes`),
      serverApiFetch<TransformationPipelineListResponse>(`/projects/${projectId}/pipelines`),
      serverApiFetch<DatasetListResponse>(`/projects/${projectId}/datasets`),
    ]);
    return (
      <LiveFeedPageView
        currentUser={currentUser}
        projectId={projectId}
        initialFeed={feed}
        kinds={kinds.items}
        connections={connections.items}
        initialThroughput={throughput.items}
        initialEvents={events.items}
        initialRecipes={liveRecipes.items}
        recipes={recipes.items}
        datasets={datasets.items
          .filter((dataset) => dataset.ingestion_status === "succeeded")
          .map((dataset) => ({ id: dataset.id, name: dataset.name }))}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
