"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";

import type { AuthUser } from "@platform/shared-types";
import { Button } from "@platform/shared-ui";

import { clearAccessToken } from "@/lib/auth/session";
import { NotificationsNavLink } from "@/components/layout/notifications-nav";
import { navigationItems } from "@/lib/navigation";
import { cx } from "@/lib/utils";

type AppSidebarProps = {
  currentUser?: AuthUser | null;
};

export function AppSidebar({ currentUser = null }: AppSidebarProps) {
  const pathname = usePathname();
  const router = useRouter();

  const handleLogout = () => {
    clearAccessToken();
    router.push("/login");
    router.refresh();
  };

  return (
    <aside className="border-b border-white/8 bg-[color:var(--sidebar)] px-5 py-6 backdrop-blur lg:border-b-0 lg:px-6">
      <div className="mb-8 rounded-[24px] border border-white/10 bg-white/[0.04] p-5">
        <div className="text-[11px] uppercase tracking-[0.28em] text-[color:var(--accent-muted)]">
          Intelligent Data Platform
        </div>
        <div className="mt-3 text-2xl font-semibold text-white">Operations Hub</div>
        <p className="mt-2 text-sm leading-6 text-slate-400">
          Projects, registered sources, datasets, and future data-quality workflows in one control surface.
        </p>
      </div>

      <nav className="space-y-2">
        {navigationItems.map((item) => {
          const isActive = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cx(
                "flex items-center justify-between rounded-2xl border px-4 py-3 text-sm transition",
                isActive
                  ? "border-[color:var(--accent-soft)] bg-[color:var(--accent-faint)] text-white shadow-[0_12px_30px_rgba(79,70,229,0.14)]"
                  : "border-white/5 text-slate-300 hover:border-white/12 hover:bg-white/[0.05] hover:text-white",
              )}
            >
              <span>{item.label}</span>
              <span className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{item.badge}</span>
            </Link>
          );
        })}
        <NotificationsNavLink />
      </nav>

      <div className="mt-8 rounded-[24px] border border-white/10 bg-white/[0.04] p-4">
        {currentUser ? (
          <>
            <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Signed in</div>
            <div className="mt-3 text-sm font-semibold text-white">{currentUser.username}</div>
            <div className="mt-1 text-xs uppercase tracking-[0.18em] text-slate-400">{currentUser.role}</div>
            <Button variant="secondary" size="sm" className="mt-4 w-full" onClick={handleLogout}>
              Logout
            </Button>
          </>
        ) : (
          <>
            <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Session</div>
            <div className="mt-3 text-sm text-slate-300">Sign in to access your owned projects and run history.</div>
            <Link href="/login" className="mt-4 inline-flex w-full">
              <Button size="sm" className="w-full">Sign in</Button>
            </Link>
          </>
        )}
      </div>
    </aside>
  );
}
