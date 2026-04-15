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
      className="group flex h-full flex-col rounded-[24px] border border-white/8 bg-[color:var(--panel)] p-5 transition duration-200 hover:-translate-y-0.5 hover:border-white/15 hover:bg-white/[0.05] hover:shadow-[0_24px_60px_rgba(2,6,23,0.28)]"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">{project.slug}</div>
          <h3 className="mt-3 text-xl font-semibold text-white transition group-hover:text-indigo-100">
            {project.name}
          </h3>
        </div>
        <StatusBadge value={project.status} />
      </div>
      <p className="mt-4 line-clamp-3 text-sm leading-6 text-slate-400">
        {project.description ?? "No description yet. Add one to capture the purpose of this workspace."}
      </p>
      <div className="mt-6 grid grid-cols-2 gap-3">
        <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-3">
          <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Sources</div>
          <div className="mt-2 text-2xl font-semibold text-white">{project.source_count}</div>
        </div>
        <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-3">
          <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Datasets</div>
          <div className="mt-2 text-2xl font-semibold text-white">{project.dataset_count}</div>
        </div>
      </div>
      <div className="mt-6 flex items-center justify-between text-sm text-slate-500">
        <span>Updated {formatDate(project.updated_at)}</span>
        <span className="transition group-hover:translate-x-0.5 group-hover:text-slate-200">Open →</span>
      </div>
    </Link>
  );
}
