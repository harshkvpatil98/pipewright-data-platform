"use client";

import Link from "next/link";

import { Icon } from "@/components/ui/icon";
import { tabHref, visibleTabs, type NavArea } from "@/lib/navigation";
import { cx } from "@/lib/utils";

type AreaTabsProps = {
  area: NavArea;
  activeTabId: string;
  projectId: string | null;
  isAdmin: boolean;
};

/**
 * The pages of the current area, side by side under the top bar. Every page
 * in an area shows them, detail pages included, so "where am I and what is
 * next to this" is always answered on screen rather than in a menu.
 */
export function AreaTabs({ area, activeTabId, projectId, isAdmin }: AreaTabsProps) {
  const tabs = visibleTabs(area, isAdmin);
  if (tabs.length < 2) return null;

  return (
    <nav
      data-tour="area-tabs"
      aria-label={`${area.label} pages`}
      className="flex h-11 shrink-0 items-end gap-1 overflow-x-auto border-b border-line bg-[color:var(--panel)] px-4 lg:px-6"
    >
      {tabs.map((tab) => {
        const href = tabHref(area, tab, projectId);
        const active = tab.id === activeTabId;
        const className = cx(
          "relative flex h-full shrink-0 items-center gap-2 px-3 text-[13.5px] transition",
          active ? "font-medium text-ink" : "text-ink-3 hover:text-ink",
        );
        const body = (
          <>
            <Icon name={tab.icon} size={15} className={active ? "text-[color:var(--accent-muted)]" : ""} />
            {tab.label}
            {active ? (
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
            aria-current={active ? "page" : undefined}
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
  );
}
