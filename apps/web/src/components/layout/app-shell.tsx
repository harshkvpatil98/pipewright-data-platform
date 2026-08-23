"use client";

import { usePathname } from "next/navigation";
import { useMemo } from "react";

import type { AuthUser } from "@platform/shared-types";

import { AppFrame } from "@/components/shell/app-frame";
import type { Crumb } from "@/components/shell/top-bar";
import type { RibbonGroup } from "@/components/shell/ribbon";
import type { StatusItem } from "@/components/shell/status-bar";

type AppShellProps = {
  title: string;
  subtitle: string;
  eyebrow?: string;
  actions?: React.ReactNode;
  meta?: React.ReactNode;
  currentUser?: AuthUser | null;
  /** Optional contextual ribbon; pages without one simply get more canvas. */
  ribbon?: RibbonGroup[];
  statusItems?: StatusItem[];
  children: React.ReactNode;
};

/**
 * Page wrapper on top of the product frame.
 *
 * Pages describe themselves with a title and subtitle; this derives the
 * breadcrumb trail from the route so every screen gets consistent chrome
 * without each page hand-maintaining its own crumbs.
 */
export function AppShell({
  title,
  subtitle,
  eyebrow,
  actions,
  meta,
  currentUser,
  ribbon,
  statusItems,
  children,
}: AppShellProps) {
  const pathname = usePathname();

  const crumbs = useMemo<Crumb[]>(() => {
    const segments = pathname.split("/").filter(Boolean);
    if (segments.length === 0) return [{ label: "Home" }];

    // /projects/<id>/<section> -> Projects / Workspace / <Title>
    if (segments[0] === "projects" && segments.length >= 2) {
      const projectId = segments[1];
      const trail: Crumb[] = [
        { label: "Projects", href: "/projects" },
        { label: "Workspace", href: `/projects/${projectId}` },
      ];
      if (segments.length > 2) trail.push({ label: title });
      else trail[1] = { label: title, href: `/projects/${projectId}` };
      return trail;
    }

    return [{ label: title }];
  }, [pathname, title]);

  return (
    <AppFrame
      currentUser={currentUser}
      crumbs={crumbs}
      ribbon={ribbon}
      statusItems={statusItems}
    >
      <div className="px-6 py-6 lg:px-8">
        <header className="mb-6 max-w-4xl">
          {eyebrow ? (
            <div className="mb-2 text-[11px] font-medium uppercase tracking-[0.2em] text-[color:var(--accent-muted)]">
              {eyebrow}
            </div>
          ) : null}
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <h1 className="text-[26px] font-semibold tracking-tight text-ink">{title}</h1>
              <p className="mt-2 text-[13px] leading-6 text-ink-3">{subtitle}</p>
            </div>
            {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
          </div>
          {meta ? <div className="mt-4">{meta}</div> : null}
        </header>

        <div className="space-y-5">{children}</div>
      </div>
    </AppFrame>
  );
}
