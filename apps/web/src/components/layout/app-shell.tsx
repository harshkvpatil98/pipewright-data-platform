import type { AuthUser } from "@platform/shared-types";
import { PageHeader } from "@platform/shared-ui";

import { AppSidebar } from "@/components/layout/app-sidebar";

type AppShellProps = {
  title: string;
  subtitle: string;
  eyebrow?: string;
  actions?: React.ReactNode;
  meta?: React.ReactNode;
  currentUser?: AuthUser | null;
  children: React.ReactNode;
};

export function AppShell({
  title,
  subtitle,
  eyebrow,
  actions,
  meta,
  currentUser,
  children,
}: AppShellProps) {
  return (
    <div className="min-h-screen bg-transparent text-slate-100">
      <div className="mx-auto grid min-h-screen max-w-[1680px] lg:grid-cols-[280px_1fr]">
        <AppSidebar currentUser={currentUser ?? null} />
        <main className="flex min-h-screen flex-col border-l border-white/8 bg-[radial-gradient(circle_at_top,_rgba(99,102,241,0.07),_transparent_26%),linear-gradient(180deg,rgba(255,255,255,0.02),rgba(255,255,255,0))]">
          <PageHeader
            eyebrow={eyebrow}
            title={title}
            description={subtitle}
            actions={actions}
            meta={meta}
          />
          <div className="flex-1 space-y-7 px-6 py-6 lg:px-10 lg:py-8">{children}</div>
        </main>
      </div>
    </div>
  );
}
