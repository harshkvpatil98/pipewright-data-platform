"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";

import type { ProjectSummary } from "@platform/shared-types";

import { Icon, type IconName } from "@/components/ui/icon";
import { locate } from "@/lib/navigation";
import type { ActiveProject } from "@/lib/use-active-project";
import { cx } from "@/lib/utils";

type ProjectSwitcherProps = {
  active: ActiveProject | null;
  projects: ProjectSummary[];
  loading: boolean;
  onOpen: () => void;
};

/**
 * The open project, beside the product mark where Power BI and Figma put it.
 * The rail below is this project's areas; this is how you change which
 * project that is. Switching keeps you on the same page where that means
 * something, so comparing the same screen across projects is one click.
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

  // Keep the same page when switching (Studio to Studio), but not an object
  // page: dataset 123 does not exist in the other project, so a dataset page
  // becomes that project's Datasets tab.
  const location = locate(pathname);
  const sectionSuffix = location?.area.scope === "project" ? location.tab.path : "";

  return (
    <div ref={ref} className="relative shrink-0" data-tour="project-switcher">
      <button
        type="button"
        onClick={() => {
          onOpen();
          setOpen((current) => !current);
        }}
        aria-expanded={open}
        aria-label={active ? `Project: ${active.name}. Switch project` : "Choose a project"}
        className={cx(
          "flex h-9 max-w-[220px] items-center gap-2 rounded-lg border px-2.5 transition",
          open
            ? "border-line-strong bg-surface-2"
            : "border-line bg-surface hover:border-line-strong hover:bg-surface-2",
        )}
      >
        <Icon name="folder" size={15} className="shrink-0 text-muted" />
        <span className={cx("truncate text-[13px]", active ? "font-medium text-ink" : "text-ink-3")}>
          {active?.name ?? "Choose a project"}
        </span>
        <Icon name="chevronDown" size={12} className="shrink-0 text-muted" />
      </button>

      {open ? (
        <div className="animate-fade-up absolute left-0 top-11 z-50 w-72 overflow-hidden rounded-xl border border-line bg-[color:var(--panel-strong)] shadow-[var(--shadow-lg)] backdrop-blur-xl">
          <div className="border-b border-line px-3 py-2 text-[12px] font-medium text-ink-3">
            Switch project
          </div>
          <div className="max-h-72 overflow-y-auto p-1.5">
            {loading && projects.length === 0 ? (
              <p className="px-2.5 py-4 text-center text-[13px] text-muted">Loading…</p>
            ) : projects.length === 0 ? (
              <p className="px-2.5 py-4 text-center text-[13px] text-muted">
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
                  <Icon name="folder" size={14} className="shrink-0 opacity-70" />
                  <span className="min-w-0 flex-1 truncate text-[13px]">{project.name}</span>
                  {project.id === active?.id ? (
                    <Icon name="check" size={13} className="shrink-0" />
                  ) : null}
                </Link>
              ))
            )}
          </div>
          <div className="border-t border-line p-1.5">
            {active ? (
              <MenuLink href={`/projects/${active.id}/settings`} icon="settings" onClick={() => setOpen(false)}>
                Project settings
              </MenuLink>
            ) : null}
            <MenuLink href="/projects" icon="grid" onClick={() => setOpen(false)}>
              All projects
            </MenuLink>
            <MenuLink href="/projects?new=1" icon="plus" onClick={() => setOpen(false)}>
              New project
            </MenuLink>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function MenuLink({
  href,
  icon,
  onClick,
  children,
}: {
  href: string;
  icon: IconName;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      onClick={onClick}
      className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] text-ink-2 transition hover:bg-surface-2 hover:text-ink"
    >
      <Icon name={icon} size={14} className="opacity-70" />
      {children}
    </Link>
  );
}
