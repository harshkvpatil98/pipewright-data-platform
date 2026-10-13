import { redirect } from "next/navigation";

type PageProps = {
  params: Promise<{ projectId: string; datasetId: string; pipelineId: string }>;
};

/** The form editor that lived here is retired; recipes open in the Studio. */
export default async function DatasetRecipeAddressPage({ params }: PageProps) {
  const { projectId, pipelineId } = await params;
  redirect(`/projects/${projectId}/studio?recipe=${pipelineId}`);
}
