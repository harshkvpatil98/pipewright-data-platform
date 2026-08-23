import Link from "next/link";

import { StatusBadge } from "@platform/shared-ui";
import { formatDate } from "@/lib/format";
import type { ProjectSummary } from "@platform/shared-types";

type ProjectCardProps = {
  project: ProjectSummary;
};

export function ProjectCard({ project }: ProjectCardProps) {
  return (
    <Link
      href={`/projects/${project.id}`}
      className="group flex h-full flex-col rounded-[24px] border border-line bg-[color:var(--panel)] p-5 transition duration-200 hover:-translate-y-0.5 hover:border-line-strong hover:bg-surface hover:shadow-[var(--shadow-lg)]"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.22em] text-muted">{project.slug}</div>
          <h3 className="mt-3 text-xl font-semibold text-ink transition group-hover:text-accent">
            {project.name}
          </h3>
        </div>
        <StatusBadge value={project.status} />
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
    </Link>
  );
}
