import { notFound } from "next/navigation";

import { DataQualityPageView } from "@/features/data-quality/components/data-quality-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type {
  DataQualityRuleListResponse,
  DatasetListResponse,
  RuleCatalogResponse,
} from "@platform/shared-types";

type PageProps = {
  params: Promise<{ projectId: string }>;
};

export const metadata = { title: "Data quality" };

export default async function ProjectDataQualityPage({ params }: PageProps) {
  const { projectId } = await params;
  const currentUser = await requireCurrentUser();

  try {
    const [rules, catalog, datasets] = await Promise.all([
      serverApiFetch<DataQualityRuleListResponse>(`/projects/${projectId}/data-quality/rules`),
      serverApiFetch<RuleCatalogResponse>(`/data-quality/rule-types`),
      serverApiFetch<DatasetListResponse>(`/projects/${projectId}/datasets`),
    ]);

    return (
      <DataQualityPageView
        currentUser={currentUser}
        projectId={projectId}
        initialRules={rules.items}
        ruleTypes={catalog.items}
        datasets={datasets.items}
      />
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}
