"use client";

import { useMemo, useState } from "react";

import type { AuthUser, ProjectSummary } from "@platform/shared-types";
import { Button, EmptyState, Input, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { CreateProjectModal } from "@/features/projects/components/create-project-modal";
import { ProjectCard } from "@/features/projects/components/project-card";

type ProjectsPageViewProps = {
  currentUser: AuthUser;
  projects: ProjectSummary[];
  /** Open the new-project dialog straight away (`/projects?new=1`). */
  startCreating?: boolean;
};

export function ProjectsPageView({
  currentUser,
  projects: initialProjects,
  startCreating = false,
}: ProjectsPageViewProps) {
  const [query, setQuery] = useState("");
  const [isCreateOpen, setIsCreateOpen] = useState(startCreating);
  // The server component hands these down once. Holding them in state lets a
  // deleted card leave immediately, rather than sitting there until a reload.
  const [projects, setProjects] = useState(initialProjects);

  const filteredProjects = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) {
      return projects;
    }
    return projects.filter((project) =>
      [project.name, project.slug, project.description ?? ""].some((value) =>
        value.toLowerCase().includes(normalizedQuery),
      ),
    );
  }, [projects, query]);

  return (
    <>
      <AppShell
        currentUser={currentUser}
        title="Projects"
        subtitle="Each project holds the data, recipes and dashboards for one team or subject."
        actions={<Button onClick={() => setIsCreateOpen(true)}>New project</Button>}
      >
        <SectionPanel
          title={`${projects.length} project${projects.length === 1 ? "" : "s"}`}
          description="Open one to work in it. Everything in the left-hand menu then belongs to that project."
          actions={
            projects.length > 3 ? (
              <div className="w-full min-w-[260px] lg:w-[320px]">
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Find a project"
                  aria-label="Find a project"
                />
              </div>
            ) : null
          }
        >
          {filteredProjects.length === 0 ? (
            <EmptyState
              title={projects.length === 0 ? "No projects yet" : "No project matches that"}
              description={
                projects.length === 0
                  ? "A project keeps one team's or one subject's data together. Start one to add your first data."
                  : "Try another word, or start a new project."
              }
              action={<Button onClick={() => setIsCreateOpen(true)}>New project</Button>}
            />
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {filteredProjects.map((project) => (
                <ProjectCard
                  key={project.id}
                  project={project}
                  onDeleted={(projectId) =>
                    setProjects((current) => current.filter((row) => row.id !== projectId))
                  }
                />
              ))}
            </div>
          )}
        </SectionPanel>
      </AppShell>
      <CreateProjectModal open={isCreateOpen} onClose={() => setIsCreateOpen(false)} />
    </>
  );
}
