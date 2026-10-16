import { notFound } from "next/navigation";

import type { ProjectDetail } from "@platform/shared-types";

import { ConvertPageView } from "@/features/conversions/components/convert-page";
import type { ConversionFormat } from "@/features/conversions/conversion-words";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";

export const metadata = { title: "Bring work in" };

type ConvertPageProps = { params: Promise<{ projectId: string }> };

export default async function ConvertPage({ params }: ConvertPageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();
  try {
    const [project, formats] = await Promise.all([
      serverApiFetch<ProjectDetail>(`/projects/${projectId}`),
      serverApiFetch<ConversionFormat[]>("/conversions/formats"),
    ]);
    return <ConvertPageView currentUser={currentUser} projectId={project.id} formats={formats} />;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
