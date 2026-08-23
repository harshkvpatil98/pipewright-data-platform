"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";

import type { AuthUser } from "@platform/shared-types";
import { Button, Logo } from "@platform/shared-ui";

import { clearAccessToken } from "@/lib/auth/session";
import { NotificationsNavLink } from "@/components/layout/notifications-nav";
import { brand } from "@/lib/brand";
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
    <aside className="border-b border-line bg-[color:var(--sidebar)] px-5 py-6 backdrop-blur lg:border-b-0 lg:px-6">
      <Link
        href="/"
        className="mb-8 block rounded-[24px] border border-line bg-surface p-5 transition duration-[var(--duration-base)] ease-[var(--ease-out)] hover:border-line-strong hover:bg-surface-2"
      >
        <Logo name={brand.name} tagline={brand.tagline} size={30} />
        <p className="mt-3 text-sm leading-6 text-ink-3">{brand.shortDescription}</p>
      </Link>

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
                  ? "border-[color:var(--accent-soft)] bg-[color:var(--accent-faint)] text-ink shadow-[var(--shadow-glow)]"
                  : "border-line text-ink-2 hover:border-line hover:bg-surface hover:text-ink",
              )}
            >
              <span>{item.label}</span>
              <span className="text-[11px] uppercase tracking-[0.18em] text-muted">{item.badge}</span>
            </Link>
          );
        })}
        <NotificationsNavLink />
      </nav>

      <div className="mt-8 rounded-[24px] border border-line bg-surface p-4">
        {currentUser ? (
          <>
            <div className="text-xs uppercase tracking-[0.22em] text-muted">Signed in</div>
            <div className="mt-3 text-sm font-semibold text-ink">{currentUser.username}</div>
            <div className="mt-1 text-xs uppercase tracking-[0.18em] text-ink-3">{currentUser.role}</div>
            <Button variant="secondary" size="sm" className="mt-4 w-full" onClick={handleLogout}>
              Logout
            </Button>
          </>
        ) : (
          <>
            <div className="text-xs uppercase tracking-[0.22em] text-muted">Session</div>
            <div className="mt-3 text-sm text-ink-2">Sign in to access your owned projects and run history.</div>
            <Link href="/login" className="mt-4 inline-flex w-full">
              <Button size="sm" className="w-full">Sign in</Button>
            </Link>
          </>
        )}
      </div>
    </aside>
  );
}
