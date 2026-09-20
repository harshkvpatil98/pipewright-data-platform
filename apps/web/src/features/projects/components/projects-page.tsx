"use client";

import { useMemo, useState } from "react";

import type { AuthUser, ProjectSummary } from "@platform/shared-types";
import { Button, EmptyState, Input, SectionPanel, StatCard } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { CreateProjectModal } from "@/features/projects/components/create-project-modal";
import { ProjectCard } from "@/features/projects/components/project-card";

type ProjectsPageViewProps = {
  currentUser: AuthUser;
  projects: ProjectSummary[];
};

export function ProjectsPageView({ currentUser, projects: initialProjects }: ProjectsPageViewProps) {
  const [query, setQuery] = useState("");
  const [isCreateOpen, setIsCreateOpen] = useState(false);
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

  const activeProjects = projects.filter((project) => project.status === "active").length;
  const totalSources = projects.reduce((sum, project) => sum + project.source_count, 0);
  const totalDatasets = projects.reduce((sum, project) => sum + project.dataset_count, 0);

  return (
    <>
      <AppShell
        currentUser={currentUser}
        eyebrow="Workspace management"
        title="Projects"
        subtitle="Create and manage the operational workspaces that you own, including registered sources, datasets, and run history."
        actions={<Button onClick={() => setIsCreateOpen(true)}>New project</Button>}
        meta={
          <>
            <span className="rounded-full border border-line bg-surface px-3 py-1 text-xs uppercase tracking-[0.18em] text-ink-2">
              User-owned scope
            </span>
            <span className="rounded-full border border-line bg-surface px-3 py-1 text-xs uppercase tracking-[0.18em] text-ink-2">
              Signed in as {currentUser.username}
            </span>
          </>
        }
      >
        <section className="grid gap-4 md:grid-cols-3">
          <StatCard label="Your projects" value={String(projects.length)} caption="Only workspaces you own are visible here." />
          <StatCard label="Active projects" value={String(activeProjects)} caption="Owned projects with active operational status." />
          <StatCard label="Registered assets" value={String(totalSources + totalDatasets)} caption={`${totalSources} sources and ${totalDatasets} datasets across your scope.`} />
        </section>

        <SectionPanel
          title="Project portfolio"
          description="Browse your current workspaces, search by name or slug, and move directly into owned source, dataset, and run management."
          actions={
            <div className="w-full min-w-[260px] lg:w-[320px]">
              <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search your projects by name, slug, or description" />
            </div>
          }
        >
          {filteredProjects.length === 0 ? (
            <EmptyState
              title={projects.length === 0 ? "No projects in your scope" : "No matching projects"}
              description={
                projects.length === 0
                  ? "Create your first owned project so sources, datasets, and pipeline runs have a secure workspace boundary."
                  : "Try a different search term or create a new project in your scope."
              }
              action={<Button onClick={() => setIsCreateOpen(true)}>Create project</Button>}
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
