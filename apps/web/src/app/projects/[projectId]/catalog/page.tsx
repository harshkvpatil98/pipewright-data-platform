import { notFound } from "next/navigation";

import { CatalogPageView } from "@/features/reporting/components/catalog-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { CatalogSearchResponse, TermListResponse } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export const metadata = { title: "Catalog" };

export default async function CatalogPage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const [catalog, terms] = await Promise.all([
      serverApiFetch<CatalogSearchResponse>(`/projects/${projectId}/catalog`),
      serverApiFetch<TermListResponse>(`/projects/${projectId}/glossary`),
    ]);
    return (
      <CatalogPageView
        currentUser={currentUser}
        projectId={projectId}
        initial={catalog}
        terms={terms}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
