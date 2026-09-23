"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Icon } from "@/components/ui/icon";

type WorkspaceMenuProps = {
  projectId: string;
};

/**
 * Every project destination, grouped by what you are trying to do rather than
 * dumped as a flat wall of chips. The wall was the review's "feature buffet":
 * twelve equal-weight links with no path through them. Here the four things a
 * person actually thinks in — build, govern, operate, publish — organise the
 * same links behind one "Workspace" button.
 */
export function WorkspaceMenu({ projectId }: WorkspaceMenuProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("mousedown", onClick);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onClick);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const p = (suffix: string) => `/projects/${projectId}${suffix}`;
  const groups: { label: string; items: { label: string; href: string }[] }[] = [
    {
      label: "Build",
      items: [
        { label: "Studio", href: p("/studio") },
        { label: "Table editor", href: p("/table-editor") },
        { label: "SQL workbench", href: p("/workbench") },
        { label: "Notebooks", href: p("/notebooks") },
        { label: "Workflows", href: p("/workflows") },
      ],
    },
    {
      label: "Govern",
      items: [
        { label: "Data quality", href: p("/data-quality") },
        { label: "Schema drift", href: p("/schema-drift") },
        { label: "Incidents", href: p("/incidents") },
        { label: "Catalog", href: p("/catalog") },
        { label: "Saved tests", href: p("/tests/saved") },
        { label: "Governance", href: p("/governance") },
      ],
    },
    {
      label: "Operate",
      items: [
        { label: "Extraction", href: p("/extraction") },
        { label: "Schedules", href: p("/schedules") },
        { label: "Notification targets", href: p("/notification-targets") },
      ],
    },
    {
      label: "Publish",
      items: [
        { label: "Destinations", href: p("/destinations") },
        { label: "BI connections", href: p("/bi-connections") },
        { label: "Charts", href: p("/charts") },
        { label: "Metrics", href: p("/metrics") },
        { label: "Dashboards", href: p("/dashboards") },
        { label: "Reports", href: p("/reports") },
      ],
    },
  ];

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-ink transition hover:border-line-strong"
      >
        Workspace
        <Icon name={open ? "chevronDown" : "chevronRight"} size={12} />
      </button>
      {open ? (
        <div className="absolute left-0 top-full z-30 mt-2 w-[min(560px,calc(100vw-3rem))] rounded-2xl border border-line bg-[color:var(--panel-strong)] p-4 shadow-[var(--shadow-lg)]">
          <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
            {groups.map((group) => (
              <div key={group.label}>
                <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted">
                  {group.label}
                </div>
                <ul className="flex flex-col gap-0.5">
                  {group.items.map((item) => (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        onClick={() => setOpen(false)}
                        className="block rounded-lg px-2 py-1.5 text-[12.5px] text-ink-2 transition hover:bg-surface-2 hover:text-ink"
                      >
                        {item.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
