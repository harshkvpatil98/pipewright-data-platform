"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";

import type { ProjectSummary } from "@platform/shared-types";

import { apiFetch } from "@/lib/api/client";

const LAST_PROJECT_KEY = "pipewright.lastProject";

export type ActiveProject = { id: string; name: string };

type UseActiveProjectResult = {
  /** The project the workspace is currently scoped to, if any. */
  active: ActiveProject | null;
  /** All projects, loaded lazily for the switcher. */
  projects: ProjectSummary[];
  loading: boolean;
  /** Fetch the project list; safe to call repeatedly. */
  ensureLoaded: () => void;
};

function readStored(): ActiveProject | null {
  try {
    const raw = window.localStorage.getItem(LAST_PROJECT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ActiveProject;
    return parsed?.id ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * Resolves which project the workspace is scoped to.
 *
 * The project-scoped destinations (sources, studio, quality, ...) are
 * meaningless without a project. Rather than pointing them all at the project
 * list, the current project is taken from the URL and remembered, so navigating
 * to a global page like Home keeps the workspace context rather than dropping
 * every scoped link onto the same page.
 */
export function useActiveProject(): UseActiveProjectResult {
  const pathname = usePathname();
  const [active, setActive] = useState<ActiveProject | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [requested, setRequested] = useState(false);

  const routeProjectId =
    pathname.startsWith("/projects/") ? pathname.split("/")[2] || null : null;

  // Restore the remembered project before the first paint of a global page.
  useEffect(() => {
    if (!routeProjectId) setActive(readStored());
  }, [routeProjectId]);

  const ensureLoaded = useCallback(() => {
    setRequested(true);
  }, []);

  // The project list is only needed for the switcher and for naming the project
  // in the URL, so it is fetched on demand rather than on every page load.
  //
  // The in-flight guard is a ref, not `loading` state: depending on state that
  // this effect itself sets would re-run the effect, and the cleanup would then
  // cancel its own request before the response could be applied.
  const fetchStarted = useRef(false);

  useEffect(() => {
    if (!requested && !routeProjectId) return;
    if (fetchStarted.current) return;

    fetchStarted.current = true;
    setLoading(true);
    apiFetch<{ items: ProjectSummary[] }>("/projects")
      .then((response) => setProjects(response.items))
      .catch(() => setProjects([]))
      .finally(() => setLoading(false));
  }, [requested, routeProjectId]);

  // Once names are known, resolve the id in the URL and remember it.
  useEffect(() => {
    if (!routeProjectId) return;
    const match = projects.find((project) => project.id === routeProjectId);
    const resolved: ActiveProject = {
      id: routeProjectId,
      name: match?.name ?? readStored()?.name ?? "Current project",
    };
    setActive(resolved);
    if (match) {
      try {
        window.localStorage.setItem(LAST_PROJECT_KEY, JSON.stringify(resolved));
      } catch {
        /* storage unavailable: context lasts for this page only */
      }
    }
  }, [routeProjectId, projects]);

  return { active, projects, loading, ensureLoaded };
}
