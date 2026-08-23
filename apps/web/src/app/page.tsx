import { HomeDashboard } from "@/features/dashboard/components/home-dashboard";
import { getCurrentUser } from "@/lib/auth/server";
import { serverApiFetch } from "@/lib/api/server";
import type { PlatformStatusResponse, ProjectListResponse } from "@platform/shared-types";

// Operational numbers must be current on every visit, not cached from a build.
export const dynamic = "force-dynamic";

export default async function HomePage() {
  const currentUser = await getCurrentUser();

  // The dashboard degrades to empty state rather than erroring when the API is
  // unreachable or the visitor is not signed in.
  const [status, projects] = await Promise.all([
    serverApiFetch<PlatformStatusResponse>("/status").catch(() => null),
    currentUser
      ? serverApiFetch<ProjectListResponse>("/projects").catch(() => ({ items: [] }))
      : Promise.resolve({ items: [] }),
  ]);

  return <HomeDashboard currentUser={currentUser} projects={projects.items} status={status} />;
}
