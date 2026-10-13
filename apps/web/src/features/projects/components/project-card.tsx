"use client";

import Link from "next/link";
import { useState } from "react";

import { Icon, StatusBadge } from "@platform/shared-ui";
import { ConfirmDeleteDialog } from "@/components/ui/confirm-delete-dialog";
import { apiFetch } from "@/lib/api/client";
import { countOf, formatDate } from "@/lib/format";
import type { ProjectSummary } from "@platform/shared-types";

type ProjectCardProps = {
  project: ProjectSummary;
  onDeleted?: (projectId: string) => void;
};

export function ProjectCard({ project, onDeleted }: ProjectCardProps) {
  const [confirming, setConfirming] = useState(false);

  const holdings = [
    project.dataset_count ? countOf(project.dataset_count, "dataset") : null,
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
            <div className="min-w-0">
              <h3 className="text-lg font-semibold text-ink transition group-hover:text-accent">
                {project.name}
              </h3>
            </div>
            <div className="flex items-center gap-2">
              {project.status !== "active" ? <StatusBadge value={project.status} /> : null}
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
            {project.description ?? "No description yet."}
          </p>
          <div className="mt-auto flex items-center justify-between pt-5 text-[13px] text-muted">
            <span>
              {project.dataset_count === 0
                ? "No data yet"
                : `${project.dataset_count} dataset${project.dataset_count === 1 ? "" : "s"}`}{" "}
              · updated {formatDate(project.updated_at)}
            </span>
            <span className="transition group-hover:translate-x-0.5 group-hover:text-ink">Open</span>
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
            ? `Everything inside it goes too: ${holdings.join(" and ")}, plus their runs, recipes and history.`
            : "Everything inside it goes too, including its runs, recipes and history.",
          "Anyone you shared this project with loses access to it.",
        ]}
        onConfirm={() => apiFetch(`/projects/${project.id}`, { method: "DELETE" })}
        onDeleted={() => onDeleted?.(project.id)}
        onClose={() => setConfirming(false)}
      />
    </>
  );
}
