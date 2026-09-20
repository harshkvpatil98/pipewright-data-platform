"use client";

import Link from "next/link";
import { useState } from "react";

import { StatusBadge } from "@platform/shared-ui";
import { ConfirmDeleteDialog } from "@/components/ui/confirm-delete-dialog";
import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { formatDate } from "@/lib/format";
import type { ProjectSummary } from "@platform/shared-types";

type ProjectCardProps = {
  project: ProjectSummary;
  onDeleted?: (projectId: string) => void;
};

export function ProjectCard({ project, onDeleted }: ProjectCardProps) {
  const [confirming, setConfirming] = useState(false);

  const holdings = [
    project.dataset_count ? `${project.dataset_count} dataset(s)` : null,
    project.source_count ? `${project.source_count} source(s)` : null,
  ].filter(Boolean) as string[];

  return (
    <>
      {/*
        The card was a single <Link> wrapping everything, which left nowhere to
        put an action: a <button> inside an <a> is invalid, and nesting one
        makes the whole card's click target ambiguous. So the link is an
        overlay covering the card, the content sits above it but transparent to
        the pointer, and only the action buttons take clicks back.
      */}
      <div className="group relative flex h-full flex-col rounded-[24px] border border-line bg-[color:var(--panel)] p-5 transition duration-200 hover:-translate-y-0.5 hover:border-line-strong hover:bg-surface hover:shadow-[var(--shadow-lg)]">
        <Link
          href={`/projects/${project.id}`}
          aria-label={`Open ${project.name}`}
          className="absolute inset-0 z-0 rounded-[24px]"
        />
        <div className="pointer-events-none relative z-10 flex h-full flex-col">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-[11px] uppercase tracking-[0.22em] text-muted">{project.slug}</div>
              <h3 className="mt-3 text-xl font-semibold text-ink transition group-hover:text-accent">
                {project.name}
              </h3>
            </div>
            <div className="flex items-center gap-2">
              <StatusBadge value={project.status} />
              <button
                type="button"
                onClick={() => setConfirming(true)}
                aria-label={`Delete ${project.name}`}
                className="pointer-events-auto rounded-lg border border-line p-1.5 text-muted transition hover:border-danger-line hover:text-danger"
              >
                <Icon name="trash" size={12} />
              </button>
            </div>
          </div>
          <p className="mt-4 line-clamp-3 text-sm leading-6 text-ink-3">
            {project.description ?? "No description yet. Add one to capture the purpose of this workspace."}
          </p>
          <div className="mt-6 grid grid-cols-2 gap-3">
            <div className="rounded-2xl border border-line bg-sunken px-4 py-3">
              <div className="text-xs uppercase tracking-[0.2em] text-muted">Sources</div>
              <div className="mt-2 text-2xl font-semibold text-ink">{project.source_count}</div>
            </div>
            <div className="rounded-2xl border border-line bg-sunken px-4 py-3">
              <div className="text-xs uppercase tracking-[0.2em] text-muted">Datasets</div>
              <div className="mt-2 text-2xl font-semibold text-ink">{project.dataset_count}</div>
            </div>
          </div>
          <div className="mt-6 flex items-center justify-between text-sm text-muted">
            <span>Updated {formatDate(project.updated_at)}</span>
            <span className="transition group-hover:translate-x-0.5 group-hover:text-ink">Open →</span>
          </div>
        </div>
      </div>

      <ConfirmDeleteDialog
        open={confirming}
        name={project.name}
        kind="project"
        requireTypedName
        consequences={[
          holdings.length
            ? `Everything inside it goes too: ${holdings.join(" and ")}, plus their runs, pipelines and history.`
            : "Everything inside it goes too, including its runs, pipelines and history.",
          "Anyone you shared this project with loses access to it.",
        ]}
        onConfirm={() => apiFetch(`/projects/${project.id}`, { method: "DELETE" })}
        onDeleted={() => onDeleted?.(project.id)}
        onClose={() => setConfirming(false)}
      />
    </>
  );
}
