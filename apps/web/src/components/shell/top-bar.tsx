"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import type { AuthUser, SupportContact } from "@platform/shared-types";
import { Icon, type IconName, LogoMark, Modal } from "@platform/shared-ui";

import { ProjectSwitcher } from "@/components/shell/project-switcher";
import { Tooltip } from "@/components/ui/tooltip";
import { ThemeToggle } from "@/features/preferences/components/appearance-controls";
import { brand } from "@/lib/brand";
import { apiFetch } from "@/lib/api/client";
import { clearAccessToken } from "@/lib/auth/session";
import { appConfig } from "@/lib/config";
import { platformRoleLabel } from "@/lib/labels";
import type { Crumb } from "@/lib/navigation";
import { cx } from "@/lib/utils";
import { t } from "@/lib/i18n";

export type { Crumb };

type TopBarProps = {
  crumbs: Crumb[];
  currentUser?: AuthUser | null;
  onOpenCommand: () => void;
  onReplayTour: () => void;
  isMac: boolean;
  projectSwitcher: React.ComponentProps<typeof ProjectSwitcher>;
};

/** The interactive API reference lives on the gateway, beside the API. */
function apiReferenceUrl(): string {
  return `${appConfig.apiBaseUrl.replace(/\/v\d+\/?$/, "")}/docs`;
}

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
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [support, setSupport] = useState<SupportContact | null>(null);
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

  // Where to get help is asked for the first time the Help menu opens.
  useEffect(() => {
    if (!helpOpen || support) return;
    let cancelled = false;
    apiFetch<SupportContact>("/status/support")
      .then((found) => {
        if (!cancelled) setSupport(found);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [helpOpen, support]);

  const logout = () => {
    clearAccessToken();
    router.push("/login");
    router.refresh();
  };

  const mod = isMac ? "⌘" : t("shell.keys.ctrl");
  const displayName = currentUser?.display_name?.trim() || currentUser?.username;
  const initials = (displayName ?? "?")
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-[color:var(--panel-strong)] px-3">
      <Tooltip label="Home: all your projects" side="bottom">
        <Link href="/" className="flex shrink-0 items-center gap-2.5 rounded-lg px-1 py-1">
          <LogoMark size={26} title={brand.name} />
          <span className="hidden text-[15px] font-semibold tracking-tight text-ink sm:block">
            {brand.name}
          </span>
        </Link>
      </Tooltip>

      <div className="h-5 w-px bg-line" aria-hidden="true" />

      <ProjectSwitcher {...projectSwitcher} />

      <nav
        aria-label={t("shell.topBar.breadcrumb")}
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
                aria-current={index === crumbs.length - 1 ? "page" : undefined}
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
        <span className="flex-1 text-[13px] text-muted">{t("shell.topBar.searchPlaceholder")}</span>
        <kbd className="rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[12px] text-ink-3">
          {mod}K
        </kbd>
      </button>

      <Tooltip label={t("shell.topBar.search")} shortcut={`${mod} K`} side="bottom">
        <button
          type="button"
          onClick={onOpenCommand}
          aria-label={t("shell.topBar.search")}
          className="flex h-9 w-9 items-center justify-center rounded-xl text-ink-3 transition hover:bg-surface-2 hover:text-ink md:hidden"
        >
          <Icon name="search" size={17} />
        </button>
      </Tooltip>

      <ThemeToggle />

      <Tooltip label={t("shell.topBar.notifications")} side="bottom">
        <Link
          href="/notifications"
          aria-label={t("shell.topBar.notifications")}
          className="flex h-9 w-9 items-center justify-center rounded-xl text-ink-3 transition hover:bg-surface-2 hover:text-ink"
        >
          <Icon name="bell" size={17} />
        </Link>
      </Tooltip>

      <div ref={helpRef} className="relative">
        <Tooltip label={t("shell.topBar.help")} side="bottom">
          <button
            type="button"
            data-tour="help-trigger"
            onClick={() => setHelpOpen((open) => !open)}
            aria-label={t("shell.topBar.help")}
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
          <div className="animate-fade-up absolute right-0 top-11 z-50 w-64 overflow-hidden rounded-xl border border-line bg-[color:var(--panel-strong)] p-1.5 shadow-[var(--shadow-lg)] backdrop-blur-xl">
            <Link href="/help" onClick={() => setHelpOpen(false)} className={MENU_ITEM}>
              <Icon name="book" size={15} className="text-[color:var(--accent-muted)]" />
              {t("shell.topBar.documentation")}
            </Link>
            <Link href="/help/whats-new" onClick={() => setHelpOpen(false)} className={MENU_ITEM}>
              <Icon name="sparkles" size={15} className="text-[color:var(--accent-muted)]" />
              {t("shell.topBar.whatsNew")}
            </Link>
            <MenuButton
              icon="compass"
              onClick={() => {
                setHelpOpen(false);
                onReplayTour();
              }}
            >
              {t("shell.topBar.showMeAround")}
            </MenuButton>
            <MenuButton
              icon="keyboard"
              onClick={() => {
                setHelpOpen(false);
                setShortcutsOpen(true);
              }}
            >
              {t("shell.topBar.keyboardShortcuts")}
            </MenuButton>
            <div className="my-1 border-t border-line" />
            <a
              href={apiReferenceUrl()}
              target="_blank"
              rel="noreferrer"
              onClick={() => setHelpOpen(false)}
              className={MENU_ITEM}
            >
              <Icon name="code" size={15} className="text-[color:var(--accent-muted)]" />
              <span className="flex-1">{t("shell.topBar.apiReference")}</span>
              <Icon name="external" size={13} className="text-muted" />
            </a>
            <Link href="/system-status" onClick={() => setHelpOpen(false)} className={MENU_ITEM}>
              <Icon name="activity" size={15} className="text-[color:var(--accent-muted)]" />
              {t("shell.topBar.systemStatus")}
            </Link>
            {support?.href ? (
              <a
                href={support.href}
                target="_blank"
                rel="noreferrer"
                onClick={() => setHelpOpen(false)}
                className={MENU_ITEM}
              >
                <Icon name="mail" size={15} className="text-[color:var(--accent-muted)]" />
                <span className="min-w-0 flex-1">
                  {t("shell.topBar.contactSupport")}
                  <span className="block truncate text-[12px] text-ink-3">{support.contact}</span>
                </span>
              </a>
            ) : (
              <Link href="/help#getting-help" onClick={() => setHelpOpen(false)} className={MENU_ITEM}>
                <Icon name="mail" size={15} className="text-[color:var(--accent-muted)]" />
                {t("shell.topBar.contactSupport")}
              </Link>
            )}
          </div>
        ) : null}
      </div>

      <div ref={menuRef} className="relative">
        <button
          type="button"
          onClick={() => setMenuOpen((open) => !open)}
          aria-label={t("shell.topBar.yourAccount")}
          aria-expanded={menuOpen}
          className="flex h-9 items-center gap-2 rounded-xl border border-line bg-surface pl-1 pr-2.5 transition hover:border-line-strong hover:bg-surface-2"
        >
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-[color:var(--brand-gradient-from)] to-[color:var(--brand-gradient-to)] text-[12px] font-semibold text-accent-ink">
            {initials}
          </span>
          <Icon name="chevronDown" size={12} className="text-muted" />
        </button>
        {menuOpen ? (
          <div className="animate-fade-up absolute right-0 top-11 z-50 w-60 overflow-hidden rounded-xl border border-line bg-[color:var(--panel-strong)] shadow-[var(--shadow-lg)] backdrop-blur-xl">
            <div className="border-b border-line px-3 py-2.5">
              <div className="truncate text-[13px] font-medium text-ink">
                {displayName ?? t("shell.topBar.notSignedIn")}
              </div>
              {currentUser ? (
                <div className="mt-0.5 truncate text-[12px] text-muted">
                  {currentUser.username} · {platformRoleLabel(currentUser.role)}
                </div>
              ) : null}
            </div>
            <div className="p-1.5">
              {currentUser ? (
                <>
                  <Link href="/settings" onClick={() => setMenuOpen(false)} className={MENU_ITEM}>
                    <Icon name="settings" size={15} className="text-ink-3" />
                    {t("shell.topBar.yourSettings")}
                  </Link>
                  <button
                    type="button"
                    onClick={logout}
                    className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] text-danger transition hover:bg-danger-soft"
                  >
                    <Icon name="close" size={15} />
                    {t("shell.topBar.signOut")}
                  </button>
                </>
              ) : (
                <Link href="/login" onClick={() => setMenuOpen(false)} className={MENU_ITEM}>
                  <Icon name="arrowRight" size={15} className="text-ink-3" />
                  {t("shell.topBar.signIn")}
                </Link>
              )}
            </div>
          </div>
        ) : null}
      </div>

      <Modal
        open={shortcutsOpen}
        title={t("shell.topBar.keyboardShortcuts")}
        onClose={() => setShortcutsOpen(false)}
        widthClassName="max-w-md"
      >
        <dl className="space-y-2.5 text-[14px]">
          {[
            [`${mod} K`, t("shell.topBar.shortcutSearch")],
            [`${mod} \\`, t("shell.topBar.shortcutLabels")],
            ["?", t("shell.topBar.showMeAround")],
            [t("shell.keys.esc"), t("shell.topBar.shortcutClose")],
          ].map(([keys, what]) => (
            <div key={keys} className="flex items-center justify-between gap-4">
              <dt className="text-ink-2">{what}</dt>
              <dd>
                <kbd className="rounded border border-line bg-surface px-2 py-0.5 font-mono text-[12px] text-ink">
                  {keys}
                </kbd>
              </dd>
            </div>
          ))}
        </dl>
      </Modal>
    </header>
  );
}

const MENU_ITEM =
  "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] text-ink transition hover:bg-surface-2";

function MenuButton({
  icon,
  onClick,
  children,
}: {
  icon: IconName;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button type="button" onClick={onClick} className={MENU_ITEM}>
      <Icon name={icon} size={15} className="text-[color:var(--accent-muted)]" />
      {children}
    </button>
  );
}
