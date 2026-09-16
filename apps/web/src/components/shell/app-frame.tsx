"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { AuthUser } from "@platform/shared-types";

import { CommandPalette, type Command } from "@/components/shell/command-palette";
import { NavRail, type RailSection } from "@/components/shell/nav-rail";
import { Ribbon, type RibbonGroup } from "@/components/shell/ribbon";
import { Inspector, StatusBar, type StatusItem } from "@/components/shell/status-bar";
import { TopBar, type Crumb } from "@/components/shell/top-bar";
import { useTour } from "@/components/tour/tour-provider";
import { WELCOME_TOUR_ID, welcomeTour } from "@/components/tour/tours";
import { useActiveProject } from "@/lib/use-active-project";

const RAIL_STORAGE_KEY = "pipewright.rail.expanded";
const INSPECTOR_STORAGE_KEY = "pipewright.inspector.open";

type AppFrameProps = {
  currentUser?: AuthUser | null;
  crumbs: Crumb[];
  /** Contextual ribbon for the current page. Omit for pages with no actions. */
  ribbon?: RibbonGroup[];
  statusItems?: StatusItem[];
  health?: { label: string; healthy: boolean };
  inspector?: { title: string; content: React.ReactNode };
  /** Page-specific palette entries, merged with global navigation. */
  commands?: Command[];
  /** Suppress the first-run tour on pages where it would be confusing. */
  disableWelcomeTour?: boolean;
  children: React.ReactNode;
};

/**
 * Rail contents depend on whether a project is open.
 *
 * Project-scoped destinations are omitted entirely when there is no project,
 * because pointing them all at the project list would put several identical
 * links in the rail.
 */
function buildRailSections(projectId?: string, projectName?: string): RailSection[] {
  const sections: RailSection[] = [
    {
      id: "workspace",
      label: "Workspace",
      items: [
        { id: "home", label: "Home", icon: "home", href: "/" },
        { id: "projects", label: "Projects", icon: "grid", href: "/projects", exact: true },
      ],
    },
  ];

  if (projectId) {
    const scoped = (suffix: string) => `/projects/${projectId}${suffix}`;
    sections.push({
      id: "project",
      label: projectName ?? "Project",
      items: [
        { id: "overview", label: "Overview", icon: "book", href: `/projects/${projectId}`, exact: true },
        { id: "sources", label: "Sources", icon: "database", href: scoped("/extraction") },
        { id: "studio", label: "Studio", icon: "transform", href: scoped("/studio") },
        { id: "table-editor", label: "Table editor", icon: "table", href: scoped("/table-editor") },
        { id: "workbench", label: "SQL workbench", icon: "sigma", href: scoped("/workbench") },
        { id: "notebooks", label: "Notebooks", icon: "book", href: scoped("/notebooks") },
        { id: "workflows", label: "Workflows", icon: "merge", href: scoped("/workflows") },
        { id: "quality", label: "Data quality", icon: "shield", href: scoped("/data-quality") },
        { id: "charts", label: "Charts", icon: "sigma", href: scoped("/charts") },
        { id: "catalog", label: "Catalog", icon: "search", href: scoped("/catalog") },
        { id: "reports", label: "Reports", icon: "download", href: scoped("/reports") },
        { id: "drift", label: "Schema drift", icon: "drift", href: scoped("/schema-drift") },
        { id: "incidents", label: "Incidents", icon: "warning", href: scoped("/incidents") },
        { id: "members", label: "People", icon: "grid", href: scoped("/members") },
        { id: "changes", label: "Changes", icon: "check", href: scoped("/changes") },
        { id: "audit", label: "Audit log", icon: "book", href: scoped("/audit-log") },
        { id: "governance", label: "Governance", icon: "shield", href: scoped("/governance") },
        { id: "schedules", label: "Schedules", icon: "clock", href: scoped("/schedules") },
        { id: "destinations", label: "Destinations", icon: "send", href: scoped("/destinations") },
      ],
    });
  }

  sections.push({
    id: "platform",
    label: "Platform",
    items: [
      { id: "connectors", label: "Connectors", icon: "database", href: "/connectors" },
      { id: "notifications", label: "Notifications", icon: "bell", href: "/notifications" },
      { id: "status", label: "System status", icon: "activity", href: "/system-status" },
      { id: "settings", label: "Settings", icon: "settings", href: "/settings" },
    ],
  });

  return sections;
}

export function AppFrame({
  currentUser,
  crumbs,
  ribbon = [],
  statusItems = [],
  health,
  inspector,
  commands = [],
  disableWelcomeTour = false,
  children,
}: AppFrameProps) {
  const [railExpanded, setRailExpanded] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [isMac, setIsMac] = useState(true);
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

  const { active: activeProject, projects, loading: projectsLoading, ensureLoaded } =
    useActiveProject();

  const railSections = useMemo(
    () => buildRailSections(activeProject?.id, activeProject?.name),
    [activeProject],
  );

  const railItems = useMemo(
    () => railSections.flatMap((section) => section.items),
    [railSections],
  );

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

  const allCommands = useMemo<Command[]>(
    () => [
      ...commands,
      ...railItems.map((item) => ({
        id: `nav-${item.id}`,
        label: item.label,
        group: "Navigate",
        icon: item.icon,
        href: item.href,
      })),
      ...projects.map((project) => ({
        id: `project-${project.id}`,
        label: project.name,
        group: "Open project",
        icon: "grid" as const,
        href: `/projects/${project.id}`,
      })),
      {
        id: "action-tour",
        label: "Replay product tour",
        group: "Help",
        icon: "sparkles" as const,
        run: () => start(welcomeTour, WELCOME_TOUR_ID),
      },
      {
        id: "action-toggle-rail",
        label: railExpanded ? "Collapse navigation" : "Expand navigation",
        group: "View",
        icon: "menu" as const,
        run: toggleRail,
      },
      {
        id: "action-toggle-inspector",
        label: inspectorOpen ? "Hide inspector" : "Show inspector",
        group: "View",
        icon: "panelRight" as const,
        run: toggleInspector,
      },
    ],
    [
      commands,
      railItems,
      projects,
      railExpanded,
      inspectorOpen,
      start,
      toggleRail,
      toggleInspector,
    ],
  );

  // The palette can search projects, so its data must be there when it opens.
  useEffect(() => {
    if (paletteOpen) ensureLoaded();
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
        crumbs={crumbs}
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
        <NavRail sections={railSections} expanded={railExpanded} onToggle={toggleRail} />

        <main className="flex min-w-0 flex-1 flex-col">
          {ribbon.length > 0 ? <Ribbon groups={ribbon} /> : null}
          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        </main>

        {inspector ? (
          <Inspector open={inspectorOpen} onToggle={toggleInspector} title={inspector.title}>
            {inspector.content}
          </Inspector>
        ) : null}
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
