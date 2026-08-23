import { notFound } from "next/navigation";

import { SchemaDriftPageView } from "@/features/schema-drift/components/schema-drift-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { SchemaDriftEventListResponse } from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export const metadata = { title: "Schema drift" };

export default async function ProjectSchemaDriftPage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const events = await serverApiFetch<SchemaDriftEventListResponse>(
      `/projects/${projectId}/schema-drift/events`,
    );
    return (
      <SchemaDriftPageView
        currentUser={currentUser}
        projectId={projectId}
        initialEvents={events.items}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
