"use client";

import Link from "next/link";

import { Icon } from "@/components/ui/icon";
import { Tooltip } from "@/components/ui/tooltip";
import { areaHref, type AreaId, type NavArea } from "@/lib/navigation";
import { cx } from "@/lib/utils";

type NavRailProps = {
  areas: NavArea[];
  activeAreaId?: AreaId;
  /** The open project, which every project area links into. */
  projectId: string | null;
  projectName?: string;
  isAdmin: boolean;
  expanded: boolean;
  onToggle: () => void;
};

/**
 * The rail is the open project: one item per area, in the order data moves
 * (bring it in, build with it, automate it, trust it, share it), and Admin
 * last for platform administrators. It never changes shape; with no project
 * open, a project area leads to the project list instead of a dead page.
 * Each area's pages are tabs under the top bar, not more rail items.
 */
export function NavRail({
  areas,
  activeAreaId,
  projectId,
  projectName,
  isAdmin,
  expanded,
  onToggle,
}: NavRailProps) {
  const projectAreas = areas.filter((area) => area.scope === "project");
  const otherAreas = areas.filter((area) => area.scope !== "project");

  const renderItem = (area: NavArea) => {
    const active = area.id === activeAreaId;
    const href = areaHref(area, area.scope === "project" ? projectId : null, isAdmin);
    const link = (
      <Link
        href={href}
        aria-current={active ? "page" : undefined}
        className={cx(
          "relative flex items-center rounded-xl transition duration-[var(--duration-fast)] ease-[var(--ease-out)]",
          expanded ? "w-full gap-3 px-3 py-2.5" : "h-10 w-10 justify-center",
          active
            ? "bg-[color:var(--accent-faint)] font-medium text-ink"
            : "text-ink-3 hover:bg-surface-2 hover:text-ink",
        )}
      >
        {active ? (
          <span
            className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-[color:var(--accent)]"
            aria-hidden="true"
          />
        ) : null}
        <Icon name={area.icon} size={18} />
        {expanded ? <span className="truncate text-[14px]">{area.label}</span> : null}
      </Link>
    );
    return (
      <li key={area.id} className="w-full">
        {expanded ? (
          link
        ) : (
          <Tooltip label={`${area.label}: ${area.description}`} side="right">
            {link}
          </Tooltip>
        )}
      </li>
    );
  };

  return (
    <nav
      data-tour="nav-rail"
      aria-label="Primary"
      className={cx(
        "flex shrink-0 flex-col overflow-y-auto border-r border-line bg-[color:var(--sidebar)] py-3 transition-[width] duration-[var(--duration-base)] ease-[var(--ease-out)]",
        expanded ? "w-[208px] px-3" : "w-[60px] items-center px-2",
      )}
    >
      {expanded ? (
        <div className="mb-2 px-3" title={projectName}>
          <div className="text-[12px] text-muted">Project</div>
          <div className="truncate text-[13px] font-medium text-ink-2">
            {projectName ?? "None open"}
          </div>
        </div>
      ) : null}

      <ul className="flex w-full flex-col gap-1">{projectAreas.map(renderItem)}</ul>

      {otherAreas.length > 0 ? (
        <>
          <div className={cx("my-3 h-px bg-line", expanded ? "mx-3" : "mx-2 w-8")} aria-hidden="true" />
          <ul className="flex w-full flex-col gap-1">{otherAreas.map(renderItem)}</ul>
        </>
      ) : null}

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
