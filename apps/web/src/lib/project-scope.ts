import "server-only";

import { redirect } from "next/navigation";

import { serverApiFetch } from "@/lib/api/server";
import type { ProjectListResponse } from "@platform/shared-types";

/**
 * Send a top-level route into its project-scoped equivalent.
 *
 * The real feature surfaces all live inside a project, so a bare `/studio`
 * has no meaning on its own. Rather than showing a dead-end placeholder, land
 * the user in their most recent project, or at the project list if they have
 * none yet.
 */
export async function redirectToProjectScope(suffix: string): Promise<never> {
  let projects: ProjectListResponse = { items: [] };
  try {
    projects = await serverApiFetch<ProjectListResponse>("/projects");
  } catch {
    redirect("/projects");
  }

  const target = projects.items[0];
  redirect(target ? `/projects/${target.id}${suffix}` : "/projects");
}
