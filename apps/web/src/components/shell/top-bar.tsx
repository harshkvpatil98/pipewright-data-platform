"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import type { AuthUser } from "@platform/shared-types";
import { LogoMark } from "@platform/shared-ui";

import { ProjectSwitcher } from "@/components/shell/project-switcher";
import { Icon } from "@/components/ui/icon";
import { Tooltip } from "@/components/ui/tooltip";
import { ThemeToggle } from "@/features/preferences/components/appearance-controls";
import { brand } from "@/lib/brand";
import { clearAccessToken } from "@/lib/auth/session";
import { cx } from "@/lib/utils";

export type Crumb = { label: string; href?: string };

type TopBarProps = {
  crumbs: Crumb[];
  currentUser?: AuthUser | null;
  onOpenCommand: () => void;
  onReplayTour: () => void;
  isMac: boolean;
  projectSwitcher: React.ComponentProps<typeof ProjectSwitcher>;
};

export function TopBar({
  crumbs,
  currentUser,
  onOpenCommand,
  onReplayTour,
  isMac,
  projectSwitcher,
}: TopBarProps) {
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const helpRef = useRef<HTMLDivElement>(null);

  // Close either popover on an outside click or Escape.
  useEffect(() => {
    if (!menuOpen && !helpOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (menuRef.current && !menuRef.current.contains(target)) setMenuOpen(false);
      if (helpRef.current && !helpRef.current.contains(target)) setHelpOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
        setHelpOpen(false);
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen, helpOpen]);

  const logout = () => {
    clearAccessToken();
    router.push("/login");
    router.refresh();
  };

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-[color:var(--panel-strong)] px-3">
      <Link href="/" className="flex shrink-0 items-center gap-2.5 rounded-lg px-1 py-1">
        <LogoMark size={26} title={brand.name} />
        <span className="hidden text-[15px] font-semibold tracking-tight text-ink sm:block">
          {brand.name}
        </span>
      </Link>

      <div className="h-5 w-px bg-surface-2" aria-hidden="true" />

      <ProjectSwitcher {...projectSwitcher} />

      <nav
        aria-label="Breadcrumb"
        className="hidden min-w-0 flex-1 items-center gap-1.5 overflow-hidden lg:flex"
      >
        {crumbs.map((crumb, index) => (
          <span key={`${crumb.label}-${index}`} className="flex min-w-0 items-center gap-1.5">
            {index > 0 ? (
              <Icon name="chevronRight" size={12} className="shrink-0 text-muted" />
            ) : null}
            {crumb.href && index < crumbs.length - 1 ? (
              <Link
                href={crumb.href}
                className="truncate text-[13px] text-ink-3 transition hover:text-ink"
              >
                {crumb.label}
              </Link>
            ) : (
              <span
                className={cx(
                  "truncate text-[13px]",
                  index === crumbs.length - 1 ? "font-medium text-ink" : "text-ink-3",
                )}
              >
                {crumb.label}
              </span>
            )}
          </span>
        ))}
      </nav>

      {/* Keeps the right-hand controls anchored when breadcrumbs are hidden. */}
      <div className="flex-1 lg:hidden" aria-hidden="true" />

      <button
        type="button"
        data-tour="command-trigger"
        onClick={onOpenCommand}
        className="group hidden h-9 min-w-[220px] items-center gap-2.5 rounded-xl border border-line bg-surface px-3 text-left transition duration-[var(--duration-fast)] hover:border-line-strong hover:bg-surface-2 md:flex"
      >
        <Icon name="search" size={15} className="text-muted transition group-hover:text-ink-2" />
        <span className="flex-1 text-[13px] text-muted">Search…</span>
        <kbd className="rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[10px] text-ink-3">
          {isMac ? "⌘K" : "Ctrl K"}
        </kbd>
      </button>

      <Tooltip label="Search" shortcut={isMac ? "⌘K" : "Ctrl K"} side="bottom">
        <button
          type="button"
          onClick={onOpenCommand}
          aria-label="Search"
          className="flex h-9 w-9 items-center justify-center rounded-xl text-ink-3 transition hover:bg-surface-2 hover:text-ink md:hidden"
        >
          <Icon name="search" size={17} />
        </button>
      </Tooltip>

      <ThemeToggle />

      <Tooltip label="Notifications" side="bottom">
        <Link
          href="/notifications"
          aria-label="Notifications"
          className="flex h-9 w-9 items-center justify-center rounded-xl text-ink-3 transition hover:bg-surface-2 hover:text-ink"
        >
          <Icon name="bell" size={17} />
        </Link>
      </Tooltip>

      <div ref={helpRef} className="relative">
        <Tooltip label="Help and tours" side="bottom">
          <button
            type="button"
            data-tour="help-trigger"
            onClick={() => setHelpOpen((open) => !open)}
            aria-label="Help"
            aria-expanded={helpOpen}
            className={cx(
              "flex h-9 w-9 items-center justify-center rounded-xl transition",
              helpOpen ? "bg-surface-2 text-ink" : "text-ink-3 hover:bg-surface-2 hover:text-ink",
            )}
          >
            <Icon name="help" size={17} />
          </button>
        </Tooltip>
        {helpOpen ? (
          <div className="animate-fade-up absolute right-0 top-11 z-50 w-56 overflow-hidden rounded-xl border border-line bg-[color:var(--panel-strong)] p-1.5 shadow-[var(--shadow-lg)] backdrop-blur-xl">
            <button
              type="button"
              onClick={() => {
                setHelpOpen(false);
                onReplayTour();
              }}
              className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] text-ink transition hover:bg-surface-2"
            >
              <Icon name="sparkles" size={15} className="text-[color:var(--accent-muted)]" />
              Replay product tour
            </button>
            <Link
              href="/demo"
              onClick={() => setHelpOpen(false)}
              className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] text-ink transition hover:bg-surface-2"
            >
              <Icon name="book" size={15} className="text-ink-3" />
              Guided walkthrough
            </Link>
            <Link
              href="/system-status"
              onClick={() => setHelpOpen(false)}
              className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] text-ink transition hover:bg-surface-2"
            >
              <Icon name="activity" size={15} className="text-ink-3" />
              System status
            </Link>
          </div>
        ) : null}
      </div>

      <div ref={menuRef} className="relative">
        <button
          type="button"
          onClick={() => setMenuOpen((open) => !open)}
          aria-label="Account"
          aria-expanded={menuOpen}
          className="flex h-9 items-center gap-2 rounded-xl border border-line bg-surface pl-1 pr-2.5 transition hover:border-line-strong hover:bg-surface-2"
        >
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-[color:var(--brand-gradient-from)] to-[color:var(--brand-gradient-to)] text-[11px] font-semibold uppercase text-accent-ink">
            {(currentUser?.username ?? "?").slice(0, 2)}
          </span>
          <Icon name="chevronDown" size={12} className="text-muted" />
        </button>
        {menuOpen ? (
          <div className="animate-fade-up absolute right-0 top-11 z-50 w-56 overflow-hidden rounded-xl border border-line bg-[color:var(--panel-strong)] shadow-[var(--shadow-lg)] backdrop-blur-xl">
            <div className="border-b border-line px-3 py-2.5">
              <div className="truncate text-[13px] font-medium text-ink">
                {currentUser?.username ?? "Not signed in"}
              </div>
              {currentUser ? (
                <div className="mt-0.5 text-[11px] uppercase tracking-[0.14em] text-muted">
                  {currentUser.role}
                </div>
              ) : null}
            </div>
            <div className="p-1.5">
              <Link
                href="/settings"
                onClick={() => setMenuOpen(false)}
                className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] text-ink transition hover:bg-surface-2"
              >
                <Icon name="settings" size={15} className="text-ink-3" />
                Settings
              </Link>
              <button
                type="button"
                onClick={logout}
                className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] text-danger transition hover:bg-danger-soft"
              >
                <Icon name="close" size={15} />
                Sign out
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </header>
  );
}
