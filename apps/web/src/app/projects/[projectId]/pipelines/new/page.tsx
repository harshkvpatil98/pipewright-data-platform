import { redirect } from "next/navigation";

type PageProps = {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ sourceDatasetId?: string }>;
};

/** New recipes are made in the Studio; this address is kept for old links. */
export default async function NewRecipeAddressPage({ params, searchParams }: PageProps) {
  const { projectId } = await params;
  const { sourceDatasetId } = await searchParams;
  redirect(
    sourceDatasetId
      ? `/projects/${projectId}/studio?dataset=${encodeURIComponent(sourceDatasetId)}`
      : `/projects/${projectId}/studio`,
  );
}
