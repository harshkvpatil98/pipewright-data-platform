"use client";

import type { AuthUser } from "@platform/shared-types";

import { AppFrame } from "@/components/shell/app-frame";
import type { RibbonGroup } from "@/components/shell/ribbon";
import type { StatusItem } from "@/components/shell/status-bar";

type AppShellProps = {
  title: string;
  /** One sentence saying what the page is for (A0 voice guide: 15 words at most). */
  subtitle: string;
  actions?: React.ReactNode;
  meta?: React.ReactNode;
  currentUser?: AuthUser | null;
  /** Optional contextual ribbon; pages without one simply get more canvas. */
  ribbon?: RibbonGroup[];
  statusItems?: StatusItem[];
  children: React.ReactNode;
};

/**
 * The list, detail and settings page template (A0 specification, S4): the
 * frame, then a header with the page's name, its one-line purpose and its
 * actions, then the content. Where the page sits (area, tab, breadcrumb) comes
 * from the navigation tree, so pages describe only themselves.
 */
export function AppShell({
  title,
  subtitle,
  actions,
  meta,
  currentUser,
  ribbon,
  statusItems,
  children,
}: AppShellProps) {
  return (
    <AppFrame currentUser={currentUser} title={title} ribbon={ribbon} statusItems={statusItems}>
      <div className="px-6 py-6 lg:px-8">
        <header className="mb-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0 max-w-3xl">
              <h1 className="text-[26px] font-semibold tracking-tight text-ink">{title}</h1>
              <p className="mt-1.5 text-[14px] leading-6 text-ink-3">{subtitle}</p>
            </div>
            {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
          </div>
          {meta ? <div className="mt-4 flex flex-wrap items-center gap-2">{meta}</div> : null}
        </header>

        <div className="space-y-5">{children}</div>
      </div>
    </AppFrame>
  );
}
