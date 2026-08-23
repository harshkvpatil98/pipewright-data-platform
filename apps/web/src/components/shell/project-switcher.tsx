"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";

import type { ProjectSummary } from "@platform/shared-types";

import { Icon } from "@/components/ui/icon";
import type { ActiveProject } from "@/lib/use-active-project";
import { cx } from "@/lib/utils";

type ProjectSwitcherProps = {
  active: ActiveProject | null;
  projects: ProjectSummary[];
  loading: boolean;
  onOpen: () => void;
};

/**
 * Workspace context control, in the position Power BI and Figma put it: next to
 * the product name. Switching keeps you on the same kind of page where that is
 * meaningful, so comparing the same screen across projects is one click.
 */
export function ProjectSwitcher({ active, projects, loading, onOpen }: ProjectSwitcherProps) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // Preserve the current section when switching, e.g. studio -> studio.
  const sectionSuffix = (() => {
    if (!pathname.startsWith("/projects/")) return "";
    const rest = pathname.split("/").slice(3);
    return rest.length > 0 ? `/${rest.join("/")}` : "";
  })();

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        onClick={() => {
          onOpen();
          setOpen((current) => !current);
        }}
        aria-expanded={open}
        aria-label="Switch project"
        className={cx(
          "flex h-8 max-w-[190px] items-center gap-2 rounded-lg border px-2.5 transition",
          open
            ? "border-line-strong bg-surface-2"
            : "border-line bg-surface hover:border-line-strong hover:bg-surface-2",
        )}
      >
        <Icon name="grid" size={13} className="shrink-0 text-muted" />
        <span className="truncate text-[12.5px] text-ink">
          {active?.name ?? "No project"}
        </span>
        <Icon name="chevronDown" size={11} className="shrink-0 text-muted" />
      </button>

      {open ? (
        <div className="animate-fade-up absolute left-0 top-10 z-50 w-64 overflow-hidden rounded-xl border border-line bg-[color:var(--panel-strong)] shadow-[var(--shadow-lg)] backdrop-blur-xl">
          <div className="border-b border-line px-3 py-2 text-[10px] font-medium uppercase tracking-[0.16em] text-muted">
            Switch project
          </div>
          <div className="max-h-64 overflow-y-auto p-1.5">
            {loading && projects.length === 0 ? (
              <p className="px-2.5 py-4 text-center text-[12px] text-muted">Loading…</p>
            ) : projects.length === 0 ? (
              <p className="px-2.5 py-4 text-center text-[12px] text-muted">
                No projects yet.
              </p>
            ) : (
              projects.map((project) => (
                <Link
                  key={project.id}
                  href={`/projects/${project.id}${sectionSuffix}`}
                  onClick={() => setOpen(false)}
                  className={cx(
                    "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition",
                    project.id === active?.id
                      ? "bg-[color:var(--accent-faint)] text-ink"
                      : "text-ink-2 hover:bg-surface-2",
                  )}
                >
                  <Icon name="grid" size={13} className="shrink-0 opacity-70" />
                  <span className="min-w-0 flex-1 truncate text-[12.5px]">{project.name}</span>
                  {project.id === active?.id ? (
                    <Icon name="check" size={12} className="shrink-0" />
                  ) : null}
                </Link>
              ))
            )}
          </div>
          <div className="border-t border-line p-1.5">
            <Link
              href="/projects"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[12.5px] text-ink-2 transition hover:bg-surface-2"
            >
              <Icon name="plus" size={13} className="opacity-70" />
              All projects
            </Link>
          </div>
        </div>
      ) : null}
    </div>
  );
}
