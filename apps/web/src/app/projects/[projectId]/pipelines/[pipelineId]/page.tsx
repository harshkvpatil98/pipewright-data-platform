import { redirect } from "next/navigation";

type PageProps = {
  params: Promise<{ projectId: string; pipelineId: string }>;
};

/** A recipe opens in the Studio; this address is kept for links and bookmarks. */
export default async function RecipeAddressPage({ params }: PageProps) {
  const { projectId, pipelineId } = await params;
  redirect(`/projects/${projectId}/studio?recipe=${pipelineId}`);
}
