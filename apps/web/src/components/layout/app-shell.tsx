"use client";

import type { AuthUser } from "@platform/shared-types";
import { PageHeader } from "@platform/shared-ui";

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
        <PageHeader title={title} subtitle={subtitle} actions={actions} meta={meta} />

        <div className="space-y-5">{children}</div>
      </div>
    </AppFrame>
  );
}
