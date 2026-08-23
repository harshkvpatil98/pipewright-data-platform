"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Icon, type IconName } from "@/components/ui/icon";
import { Tooltip } from "@/components/ui/tooltip";
import { cx } from "@/lib/utils";

export type RailItem = {
  id: string;
  label: string;
  icon: IconName;
  href: string;
  badge?: number;
  /** Match only this exact path, for parents of deeper routes. */
  exact?: boolean;
};

export type RailSection = {
  id: string;
  /** Shown above the group when the rail is expanded. */
  label: string;
  items: RailItem[];
};

type NavRailProps = {
  sections: RailSection[];
  expanded: boolean;
  onToggle: () => void;
};

/**
 * Icon rail grouped by scope: global destinations, then the destinations that
 * belong to the open project, then platform-wide tools. Project-scoped items
 * only appear when a project is actually open, so no two entries can point at
 * the same page.
 */
export function NavRail({ sections, expanded, onToggle }: NavRailProps) {
  const pathname = usePathname();

  const isActive = (item: RailItem) => {
    if (item.exact) return pathname === item.href;
    if (item.href === "/") return pathname === "/";
    return pathname === item.href || pathname.startsWith(`${item.href}/`);
  };

  return (
    <nav
      data-tour="nav-rail"
      aria-label="Primary"
      className={cx(
        "flex shrink-0 flex-col overflow-y-auto border-r border-line bg-[color:var(--sidebar)] py-3 transition-[width] duration-[var(--duration-base)] ease-[var(--ease-out)]",
        expanded ? "w-[212px] px-3" : "w-[60px] items-center px-2",
      )}
    >
      {sections.map((section, sectionIndex) => (
        <div key={section.id} className="w-full">
          {sectionIndex > 0 ? (
            expanded ? (
              <div className="mb-1.5 mt-4 px-3 text-[10px] font-medium uppercase tracking-[0.16em] text-muted">
                {section.label}
              </div>
            ) : (
              <div className="mx-2 my-2 h-px bg-surface-2" aria-hidden="true" />
            )
          ) : expanded ? (
            <div className="mb-1.5 px-3 text-[10px] font-medium uppercase tracking-[0.16em] text-muted">
              {section.label}
            </div>
          ) : null}

          <ul className="flex w-full flex-col gap-1">
            {section.items.map((item) => {
              const active = isActive(item);
              const link = (
                <Link
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cx(
                    "relative flex items-center rounded-xl transition duration-[var(--duration-fast)] ease-[var(--ease-out)]",
                    expanded ? "w-full gap-3 px-3 py-2.5" : "h-10 w-10 justify-center",
                    active
                      ? "bg-[color:var(--accent-faint)] text-ink"
                      : "text-ink-3 hover:bg-surface-2 hover:text-ink",
                  )}
                >
                  {active ? (
                    <span
                      className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-[color:var(--accent)]"
                      aria-hidden="true"
                    />
                  ) : null}
                  <span className="relative flex items-center justify-center">
                    <Icon name={item.icon} size={18} />
                    {item.badge ? (
                      <span
                        className="absolute -right-1.5 -top-1.5 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-[color:var(--danger)] px-1 text-[9px] font-semibold text-ink"
                        aria-label={`${item.badge} needing attention`}
                      >
                        {item.badge > 9 ? "9+" : item.badge}
                      </span>
                    ) : null}
                  </span>
                  {expanded ? <span className="truncate text-[13px]">{item.label}</span> : null}
                </Link>
              );

              return (
                <li key={item.id} className="w-full">
                  {expanded ? (
                    link
                  ) : (
                    <Tooltip label={item.label} side="right">
                      {link}
                    </Tooltip>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ))}

      <div className="mt-auto w-full pt-3">
        <button
          type="button"
          onClick={onToggle}
          aria-label={expanded ? "Collapse navigation" : "Expand navigation"}
          className={cx(
            "flex items-center rounded-xl text-muted transition hover:bg-surface-2 hover:text-ink",
            expanded ? "w-full gap-3 px-3 py-2.5" : "h-10 w-10 justify-center",
          )}
        >
          <Icon name={expanded ? "chevronLeft" : "chevronRight"} size={17} />
          {expanded ? <span className="text-[13px]">Collapse</span> : null}
        </button>
      </div>
    </nav>
  );
}
