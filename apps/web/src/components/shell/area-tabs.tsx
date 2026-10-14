"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { helpLinkFor } from "@/lib/help/pages";
import { tabHref, visibleTabs, type NavArea, type NavTab } from "@/lib/navigation";
import { cx } from "@/lib/utils";
import { Icon } from "@platform/shared-ui";
import { t } from "@/lib/i18n";

type AreaTabsProps = {
  area: NavArea;
  activeTabId: string;
  projectId: string | null;
  isAdmin: boolean;
};

/**
 * The pages of the current area, side by side under the top bar. Every page
 * in an area shows them, detail pages included, so "where am I and what is
 * next to this" is always answered on screen rather than in a menu. On the
 * right, "About this page" says what the page is for, for anyone who has
 * landed somewhere unfamiliar.
 */
export function AreaTabs({ area, activeTabId, projectId, isAdmin }: AreaTabsProps) {
  const tabs = visibleTabs(area, isAdmin);
  const active = tabs.find((tab) => tab.id === activeTabId) ?? null;

  return (
    <div className="flex h-11 shrink-0 items-stretch border-b border-line bg-[color:var(--panel)] px-4 lg:px-6">
      {tabs.length > 1 ? (
        <nav
          data-tour="area-tabs"
          aria-label={t("shell.tabs.pages", { area: area.label })}
          className="flex min-w-0 flex-1 items-end gap-1 overflow-x-auto"
        >
          {tabs.map((tab) => {
            const href = tabHref(area, tab, projectId);
            const isActive = tab.id === activeTabId;
            // Below 1280px wide the icons go and the padding tightens, so an
            // area's every tab still shows on a small laptop (A7: Trust's
            // seven tabs were cut off at 1024px).
            const className = cx(
              "relative flex h-full shrink-0 items-center gap-2 px-2.5 text-[13.5px] transition xl:px-3",
              isActive ? "font-medium text-ink" : "text-ink-3 hover:text-ink",
            );
            const body = (
              <>
                <Icon
                  name={tab.icon}
                  size={15}
                  className={cx("hidden xl:block", isActive && "text-[color:var(--accent-muted)]")}
                />
                {tab.label}
                {isActive ? (
                  <span
                    className="absolute inset-x-2 bottom-0 h-[2px] rounded-full bg-[color:var(--accent)]"
                    aria-hidden="true"
                  />
                ) : null}
              </>
            );
            return href ? (
              <Link
                key={tab.id}
                href={href}
                title={tab.description}
                aria-current={isActive ? "page" : undefined}
                className={className}
              >
                {body}
              </Link>
            ) : (
              <span key={tab.id} className={cx(className, "opacity-50")}>
                {body}
              </span>
            );
          })}
        </nav>
      ) : (
        <div className="flex-1" />
      )}
      {active ? <AboutThisPage area={area} tab={active} /> : null}
    </div>
  );
}

function AboutThisPage({ area, tab }: { area: NavArea; tab: NavTab }) {
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

  return (
    <div ref={ref} className="relative flex shrink-0 items-center pl-2">
      <button
        type="button"
        data-tour="about-page"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-controls="about-this-page"
        aria-label={t("shell.tabs.aboutThisPage")}
        title={t("shell.tabs.aboutThisPage")}
        className={cx(
          "flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px] transition",
          open ? "bg-surface-2 text-ink" : "text-ink-3 hover:bg-surface-2 hover:text-ink",
        )}
      >
        <Icon name="help" size={15} />
        <span className="hidden 2xl:inline">{t("shell.tabs.aboutThisPage")}</span>
      </button>
      {open ? (
        <div
          id="about-this-page"
          role="region"
          aria-label={t("shell.tabs.about", { tab: tab.label })}
          className="animate-fade-up absolute right-0 top-10 z-40 w-80 rounded-xl border border-line bg-[color:var(--panel-strong)] p-4 shadow-[var(--shadow-lg)]"
        >
          <div className="flex items-center gap-2">
            <Icon name={tab.icon} size={16} className="text-[color:var(--accent-muted)]" />
            <h2 className="text-[15px] font-semibold text-ink">{tab.label}</h2>
          </div>
          <p className="mt-1.5 text-[13.5px] leading-5 text-ink-2">{tab.description}</p>
          <ul className="mt-3 space-y-2">
            {tab.help.map((sentence) => (
              <li key={sentence} className="flex gap-2 text-[13px] leading-5 text-ink-3">
                <span
                  className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-[color:var(--accent-muted)]"
                  aria-hidden="true"
                />
                {sentence}
              </li>
            ))}
          </ul>
          <Link
            href={helpLinkFor(area, tab).href}
            onClick={() => setOpen(false)}
            className="mt-3 inline-flex items-center gap-1.5 text-[13px] font-medium text-accent hover:underline"
          >
            <Icon name="book" size={14} />
            {t("shell.tabs.readMore")}
          </Link>
        </div>
      ) : null}
    </div>
  );
}
