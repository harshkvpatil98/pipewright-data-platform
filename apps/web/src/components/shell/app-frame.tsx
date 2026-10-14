"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";

import type { AuthUser } from "@platform/shared-types";

import { AreaTabs } from "@/components/shell/area-tabs";
import { CommandPalette, type Command } from "@/components/shell/command-palette";
import { NavRail } from "@/components/shell/nav-rail";
import { Ribbon, type RibbonGroup } from "@/components/shell/ribbon";
import { Inspector, StatusBar, type StatusItem } from "@/components/shell/status-bar";
import { TopBar } from "@/components/shell/top-bar";
import { useTour } from "@/components/tour/tour-provider";
import { WELCOME_TOUR_ID, welcomeTour } from "@/components/tour/tours";
import {
  AREAS,
  STANDALONE_PAGES,
  breadcrumbsFor,
  locate,
  railAreas,
  tabHref,
  visibleTabs,
  type Crumb,
} from "@/lib/navigation";
import { readRecent, recordRecent } from "@/lib/recent";
import { useActiveProject } from "@/lib/use-active-project";

const RAIL_STORAGE_KEY = "pipewright.rail.expanded";
const INSPECTOR_STORAGE_KEY = "pipewright.inspector.open";

type AppFrameProps = {
  currentUser?: AuthUser | null;
  /**
   * The page's own name. On something inside a tab (a dataset, a dashboard)
   * it becomes the last breadcrumb and is remembered for Search's "Recent".
   */
  title?: string;
  /** Overrides the breadcrumb the navigation tree would derive. Rarely needed. */
  crumbs?: Crumb[];
  /** Contextual ribbon for the current page. Omit for pages with no actions. */
  ribbon?: RibbonGroup[];
  statusItems?: StatusItem[];
  health?: { label: string; healthy: boolean; href?: string };
  inspector?: { title: string; content: React.ReactNode };
  /** Page-specific palette entries, merged with global navigation. */
  commands?: Command[];
  /** Suppress the first-run tour on pages where it would be confusing. */
  disableWelcomeTour?: boolean;
  /**
   * The page's heading for screen readers, on editors whose name sits in a
   * toolbar rather than a page header, so every page has one `h1`.
   */
  heading?: string;
  children: React.ReactNode;
};

export function AppFrame({
  currentUser,
  title,
  crumbs,
  ribbon = [],
  statusItems = [],
  health,
  inspector,
  commands = [],
  disableWelcomeTour = false,
  heading,
  children,
}: AppFrameProps) {
  const pathname = usePathname();
  // Labels visible by default: an icon-only rail is a memory test.
  const [railExpanded, setRailExpanded] = useState(true);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [isMac, setIsMac] = useState(true);
  const [recent, setRecent] = useState(() => [] as ReturnType<typeof readRecent>);
  const { start, startIfUnseen } = useTour();

  // Restore layout preferences after mount so the server render stays stable.
  useEffect(() => {
    setIsMac(/Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent));
    try {
      const rail = window.localStorage.getItem(RAIL_STORAGE_KEY);
      if (rail !== null) setRailExpanded(rail === "true");
      const pane = window.localStorage.getItem(INSPECTOR_STORAGE_KEY);
      if (pane !== null) setInspectorOpen(pane === "true");
    } catch {
      /* storage unavailable: fall back to defaults */
    }
  }, []);

  const isAdmin = currentUser?.role === "admin";
  const location = useMemo(() => locate(pathname), [pathname]);
  const { active: activeProject, projects, loading: projectsLoading, ensureLoaded } =
    useActiveProject();
  const projectId = location?.projectId ?? activeProject?.id ?? null;

  const breadcrumb = useMemo(
    () => crumbs ?? breadcrumbsFor(pathname, title ?? "", isAdmin),
    [crumbs, pathname, title, isAdmin],
  );

  // Remember objects (not tab pages) for Search's "Recent" group.
  useEffect(() => {
    if (!location || location.isTabRoot || !title) return;
    recordRecent({ href: pathname, label: title, where: location.tab.label });
  }, [location, pathname, title]);

  const toggleRail = useCallback(() => {
    setRailExpanded((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(RAIL_STORAGE_KEY, String(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const toggleInspector = useCallback(() => {
    setInspectorOpen((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(INSPECTOR_STORAGE_KEY, String(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const allCommands = useMemo<Command[]>(() => {
    const navigation: Command[] = [];
    for (const area of [...railAreas(isAdmin), ...AREAS.filter((candidate) => !candidate.inRail)]) {
      for (const tab of visibleTabs(area, isAdmin)) {
        const href = tabHref(area, tab, area.scope === "project" ? projectId : null);
        if (!href) continue;
        navigation.push({
          id: `nav-${area.id}-${tab.id}`,
          label: tab.label === area.label ? area.label : tab.label,
          group: area.label,
          icon: tab.icon,
          href,
          description: tab.description,
          keywords: `${area.label} ${tab.description} ${tab.keywords ?? ""}`,
        });
      }
    }
    for (const page of STANDALONE_PAGES) {
      navigation.push({
        id: `nav-${page.path}`,
        label: page.label,
        group: "Go to",
        icon: page.icon,
        href: page.path,
        description: page.description,
      });
    }
    return [
      ...commands,
      ...recent
        .filter((item) => item.href !== pathname)
        .map((item) => ({
          id: `recent-${item.href}`,
          label: item.label,
          group: `Recent · ${item.where}`,
          icon: "clock" as const,
          href: item.href,
        })),
      ...navigation,
      ...projects.map((project) => ({
        id: `project-${project.id}`,
        label: project.name,
        group: "Open project",
        icon: "folder" as const,
        href: `/projects/${project.id}`,
      })),
      {
        id: "action-new-project",
        label: "New project",
        group: "Actions",
        icon: "plus" as const,
        href: "/projects?new=1",
      },
      {
        id: "action-tour",
        label: "Show me around",
        group: "Help",
        icon: "sparkles" as const,
        keywords: "tour help guide",
        run: () => start(welcomeTour, WELCOME_TOUR_ID),
      },
      {
        id: "action-toggle-rail",
        label: railExpanded ? "Hide navigation labels" : "Show navigation labels",
        group: "View",
        icon: "menu" as const,
        run: toggleRail,
      },
      ...(inspector
        ? [
            {
              id: "action-toggle-inspector",
              label: inspectorOpen ? "Hide the side panel" : "Show the side panel",
              group: "View",
              icon: "panelRight" as const,
              run: toggleInspector,
            },
          ]
        : []),
    ];
  }, [
    commands,
    recent,
    pathname,
    isAdmin,
    projectId,
    projects,
    railExpanded,
    inspector,
    inspectorOpen,
    start,
    toggleRail,
    toggleInspector,
  ]);

  // The palette searches projects and recent items, so load them as it opens.
  useEffect(() => {
    if (!paletteOpen) return;
    ensureLoaded();
    setRecent(readRecent());
  }, [paletteOpen, ensureLoaded]);

  // Global shortcuts. Ignored while typing so they never eat real input.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.tagName === "SELECT" ||
        target?.isContentEditable;

      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
        return;
      }
      if (typing) return;
      if ((event.metaKey || event.ctrlKey) && event.key === "\\") {
        event.preventDefault();
        toggleRail();
      }
      if (event.key === "?" && event.shiftKey) {
        event.preventDefault();
        start(welcomeTour, WELCOME_TOUR_ID);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleRail, start]);

  // First visit gets the tour automatically; afterwards it is opt-in.
  useEffect(() => {
    if (disableWelcomeTour) return;
    const timer = setTimeout(() => startIfUnseen(welcomeTour, WELCOME_TOUR_ID), 900);
    return () => clearTimeout(timer);
  }, [disableWelcomeTour, startIfUnseen]);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-transparent text-ink">
      <TopBar
        crumbs={breadcrumb}
        currentUser={currentUser}
        onOpenCommand={() => setPaletteOpen(true)}
        onReplayTour={() => start(welcomeTour, WELCOME_TOUR_ID)}
        isMac={isMac}
        projectSwitcher={{
          active: activeProject,
          projects,
          loading: projectsLoading,
          onOpen: ensureLoaded,
        }}
      />

      <div className="flex min-h-0 flex-1">
        <NavRail
          areas={railAreas(isAdmin)}
          activeAreaId={location?.area.id}
          projectId={activeProject?.id ?? null}
          projectName={activeProject?.name}
          isAdmin={isAdmin}
          expanded={railExpanded}
          onToggle={toggleRail}
        />

        {/* The tabs span the side panel too, so a page with one never
            squeezes its neighbours' names off the strip. */}
        <div className="flex min-w-0 flex-1 flex-col">
          {location ? (
            <AreaTabs
              area={location.area}
              activeTabId={location.tab.id}
              projectId={location.area.scope === "project" ? projectId : null}
              isAdmin={isAdmin}
            />
          ) : null}
          <div className="flex min-h-0 flex-1">
            <main className="flex min-w-0 flex-1 flex-col">
              {heading ? <h1 className="sr-only">{heading}</h1> : null}
              {ribbon.length > 0 ? <Ribbon groups={ribbon} /> : null}
              <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
            </main>

            {inspector ? (
              <Inspector open={inspectorOpen} onToggle={toggleInspector} title={inspector.title}>
                {inspector.content}
              </Inspector>
            ) : null}
          </div>
        </div>
      </div>

      <StatusBar items={statusItems} health={health} />

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        commands={allCommands}
      />
    </div>
  );
}
