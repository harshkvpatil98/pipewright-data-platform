/**
 * The one navigation tree.
 *
 * The rail, the tab strip under the top bar, the breadcrumb and the command
 * palette all read this file, so the product has one taxonomy instead of the
 * three it grew (rail sections, the Workspace menu, page eyebrows). The tree
 * is specified in docs/plans/adoption-readiness-workflow.md, "A0
 * specification", S3; change it there first.
 *
 * Shape: the rail lists *areas*; each area has *tabs*; every page in the app
 * belongs to exactly one tab, either as the tab itself or as something inside
 * it (a dataset belongs to Data → Datasets). `navigation.test.ts` walks every
 * route in `src/app` and fails if one is left out.
 */

import type { IconName } from "@/components/ui/icon";

export type Persona = "data owner" | "operator" | "administrator";

export type AreaId =
  | "overview"
  | "data"
  | "build"
  | "automate"
  | "trust"
  | "share"
  | "admin"
  | "workspace";

export type NavTab = {
  id: string;
  label: string;
  icon: IconName;
  /**
   * For a project area, the path after `/projects/{id}` ("" is the project's
   * own page). For a global area, the absolute path.
   */
  path: string;
  /**
   * Other routes that belong to this tab, written like the path with `*` for
   * one segment and a trailing `**` for anything deeper.
   */
  also?: string[];
  /** Who the page is for; its copy talks to this person. */
  persona: Persona;
  /** One line, shown in the palette and as the tab's tooltip. */
  description: string;
  /** Extra words the palette should find this by. */
  keywords?: string;
  adminOnly?: boolean;
};

export type NavArea = {
  id: AreaId;
  label: string;
  icon: IconName;
  scope: "project" | "global";
  description: string;
  /** Shown in the rail. The workspace area is reached from the product mark. */
  inRail: boolean;
  adminOnly?: boolean;
  tabs: NavTab[];
};

export const AREAS: NavArea[] = [
  {
    id: "overview",
    label: "Overview",
    icon: "home",
    scope: "project",
    inRail: true,
    description: "This project at a glance, and who is in it.",
    tabs: [
      {
        id: "overview",
        label: "Overview",
        icon: "home",
        path: "",
        persona: "data owner",
        description: "What to do next, recent data and recent runs.",
        keywords: "project home start checklist getting started",
      },
      {
        id: "people",
        label: "People",
        icon: "users",
        path: "/members",
        persona: "administrator",
        description: "Who can see and change this project.",
        keywords: "members access roles invite team share",
      },
      {
        id: "alerts",
        label: "Alerts",
        icon: "bell",
        path: "/notification-targets",
        persona: "operator",
        description: "Where failures and reports are sent: email or Slack.",
        keywords: "notification targets slack email webhook",
      },
      {
        id: "settings",
        label: "Settings",
        icon: "settings",
        path: "/settings",
        persona: "administrator",
        description: "Rename, archive or delete this project.",
        keywords: "project settings rename archive delete",
      },
    ],
  },
  {
    id: "data",
    label: "Data",
    icon: "database",
    scope: "project",
    inRail: true,
    description: "Bring data in and find what is already here.",
    tabs: [
      {
        id: "sources",
        label: "Sources",
        icon: "database",
        path: "/sources",
        persona: "data owner",
        description: "Upload files, connect databases and receive live data.",
        keywords: "connect database connection import extraction upload file stream webhook cdc",
      },
      {
        id: "datasets",
        label: "Datasets",
        icon: "table",
        path: "/datasets",
        also: ["/datasets/*", "/datasets/*/**"],
        persona: "data owner",
        description: "Every table of data in this project.",
        keywords: "tables data files",
      },
      {
        id: "catalog",
        label: "Catalog",
        icon: "search",
        path: "/catalog",
        persona: "data owner",
        description: "Search datasets by name, column or tag, and keep the glossary.",
        keywords: "catalogue glossary search find tags owner certified",
      },
    ],
  },
  {
    id: "build",
    label: "Build",
    icon: "wrench",
    scope: "project",
    inRail: true,
    description: "Clean, combine and reshape data.",
    tabs: [
      {
        id: "studio",
        label: "Studio",
        icon: "transform",
        path: "/studio",
        persona: "data owner",
        description: "Clean and reshape a dataset step by step, seeing the result as you go.",
        keywords: "transform clean shape recipe grid spreadsheet steps",
      },
      {
        id: "recipes",
        label: "Recipes",
        icon: "book",
        path: "/pipelines",
        also: ["/pipelines/**", "/datasets/*/pipelines/*"],
        persona: "data owner",
        description: "Saved recipes: the steps that turn one dataset into another.",
        keywords: "pipelines saved transformations",
      },
      {
        id: "sql",
        label: "SQL",
        icon: "sigma",
        path: "/workbench",
        persona: "data owner",
        description: "Write SQL against a connected database.",
        keywords: "workbench query editor sql",
      },
      {
        id: "notebooks",
        label: "Notebooks",
        icon: "file",
        path: "/notebooks",
        persona: "data owner",
        description: "SQL, recipe and note cells that run top to bottom.",
        keywords: "notebook python cells",
      },
      {
        id: "table-editor",
        label: "Table editor",
        icon: "table",
        path: "/table-editor",
        persona: "data owner",
        description: "Edit rows in a connected database table, with a preview before saving.",
        keywords: "write back edit rows database table",
      },
    ],
  },
  {
    id: "automate",
    label: "Automate",
    icon: "zap",
    scope: "project",
    inRail: true,
    description: "Run work on a schedule and deliver the results.",
    tabs: [
      {
        id: "workflows",
        label: "Workflows",
        icon: "merge",
        path: "/workflows",
        also: ["/workflows/*"],
        persona: "operator",
        description: "Tasks that run in order, by hand or on a schedule.",
        keywords: "dag orchestration tasks backfill",
      },
      {
        id: "schedules",
        label: "Schedules",
        icon: "clock",
        path: "/schedules",
        persona: "operator",
        description: "Run recipes and deliveries at set times.",
        keywords: "cron recurring daily hourly",
      },
      {
        id: "runs",
        label: "Runs",
        icon: "activity",
        path: "/runs",
        also: ["/runs/*/**"],
        persona: "operator",
        description: "Everything that has run in this project, newest first.",
        keywords: "history jobs failures audit",
      },
      {
        id: "destinations",
        label: "Destinations",
        icon: "send",
        path: "/destinations",
        persona: "operator",
        description: "Databases and file stores that receive your data.",
        keywords: "publish export deliver postgres s3",
      },
      {
        id: "bi-tools",
        label: "BI tools",
        icon: "barChart",
        path: "/bi-connections",
        persona: "operator",
        description: "Send datasets to Power BI or Tableau.",
        keywords: "bi connections power bi tableau publish",
      },
    ],
  },
  {
    id: "trust",
    label: "Trust",
    icon: "shieldCheck",
    scope: "project",
    inRail: true,
    description: "Check the data, act on problems and control access.",
    tabs: [
      {
        id: "checks",
        label: "Checks",
        icon: "check",
        path: "/checks",
        persona: "data owner",
        description: "Rules your data must pass, and their results.",
        keywords: "data quality rules tests validation quarantine",
      },
      {
        id: "comparisons",
        label: "Comparisons",
        icon: "columns",
        path: "/tests/saved",
        also: ["/tests/saved/*", "/datasets/*/compare/*"],
        persona: "data owner",
        description: "Saved statistical comparisons between two datasets.",
        keywords: "saved tests statistical compare testing",
      },
      {
        id: "incidents",
        label: "Incidents",
        icon: "warning",
        path: "/incidents",
        also: ["/incidents/*"],
        persona: "operator",
        description: "Problems that need a person, from failed checks to late data.",
        keywords: "alerts problems freshness anomalies",
      },
      {
        id: "schema-changes",
        label: "Schema changes",
        icon: "drift",
        path: "/schema-drift",
        persona: "operator",
        description: "Columns added, removed or retyped at a source.",
        keywords: "drift schema columns breaking",
      },
      {
        id: "policies",
        label: "Policies",
        icon: "shield",
        path: "/governance",
        persona: "administrator",
        description: "Who sees which rows and columns, and how long data is kept.",
        keywords: "governance security masking retention erasure gdpr",
      },
      {
        id: "approvals",
        label: "Approvals",
        icon: "checkCircle",
        path: "/changes",
        persona: "administrator",
        description: "Changes waiting for someone to approve them.",
        keywords: "change requests review approve",
      },
      {
        id: "audit",
        label: "Audit log",
        icon: "list",
        path: "/audit-log",
        persona: "administrator",
        description: "Who changed what in this project, and when.",
        keywords: "audit history activity log",
      },
    ],
  },
  {
    id: "share",
    label: "Share",
    icon: "share",
    scope: "project",
    inRail: true,
    description: "Charts, dashboards and reports for everyone else.",
    tabs: [
      {
        id: "dashboards",
        label: "Dashboards",
        icon: "grid",
        path: "/dashboards",
        also: ["/dashboards/*"],
        persona: "data owner",
        description: "Pages of charts you can share by link or by email.",
        keywords: "dashboard bi share link",
      },
      {
        id: "charts",
        label: "Charts",
        icon: "barChart",
        path: "/charts",
        persona: "data owner",
        description: "Ask a question of a dataset and save the answer as a chart.",
        keywords: "chart graph visualise visualize plot",
      },
      {
        id: "reports",
        label: "Reports",
        icon: "download",
        path: "/reports",
        persona: "data owner",
        description: "Files sent by email or Slack on a schedule.",
        keywords: "scheduled reports export excel pdf csv email",
      },
      {
        id: "metrics",
        label: "Metrics",
        icon: "sigma",
        path: "/metrics",
        persona: "data owner",
        description: "Numbers defined once, so every chart agrees.",
        keywords: "semantic layer measures kpi definitions",
      },
    ],
  },
  {
    id: "admin",
    label: "Admin",
    icon: "key",
    scope: "global",
    inRail: true,
    adminOnly: true,
    description: "People, organisations and the platform itself.",
    tabs: [
      {
        id: "people",
        label: "People",
        icon: "users",
        path: "/people",
        adminOnly: true,
        persona: "administrator",
        description: "Every account on this platform: invite, reset, deactivate.",
        keywords: "users accounts invite admin",
      },
      {
        id: "organisations",
        label: "Organisations",
        icon: "grid",
        path: "/organisations",
        adminOnly: true,
        persona: "administrator",
        description: "Separate groups of people and projects.",
        keywords: "organizations tenants tenancy",
      },
      {
        id: "audit",
        label: "Audit (all projects)",
        icon: "list",
        path: "/audits",
        adminOnly: true,
        persona: "administrator",
        description: "Every change across every project, with export.",
        keywords: "audit center export compliance",
      },
      {
        id: "connectors",
        label: "Connectors",
        icon: "link",
        path: "/connectors",
        persona: "administrator",
        description: "Every kind of source the platform can connect to.",
        keywords: "connector catalogue integrations saas",
      },
      {
        id: "status",
        label: "System status",
        icon: "activity",
        path: "/system-status",
        persona: "administrator",
        description: "Whether the platform and its background work are healthy.",
        keywords: "health status workers uptime",
      },
    ],
  },
  {
    id: "workspace",
    label: "Home",
    icon: "home",
    scope: "global",
    inRail: false,
    description: "Everything you can see, across projects.",
    tabs: [
      {
        id: "home",
        label: "Home",
        icon: "home",
        path: "/",
        persona: "data owner",
        description: "What needs attention, and where you left off.",
        keywords: "start dashboard welcome",
      },
      {
        id: "projects",
        label: "Projects",
        icon: "folder",
        path: "/projects",
        persona: "data owner",
        description: "All projects you can open, and a new one.",
        keywords: "workspaces new project",
      },
      {
        id: "runs",
        label: "All runs",
        icon: "activity",
        path: "/runs",
        persona: "operator",
        description: "Recent runs across every project.",
        keywords: "history failures",
      },
      {
        id: "datasets",
        label: "Find a dataset",
        icon: "search",
        path: "/datasets",
        persona: "data owner",
        description: "Search datasets across every project.",
        keywords: "search tables",
      },
    ],
  },
];

/** Pages outside every area: reached from the top bar. */
export const STANDALONE_PAGES: { path: string; label: string; icon: IconName; description: string }[] = [
  {
    path: "/notifications",
    label: "Notifications",
    icon: "bell",
    description: "Messages about your runs, reports and mentions.",
  },
  {
    path: "/settings",
    label: "Your settings",
    icon: "settings",
    description: "Appearance, password, two-factor sign-in and API tokens.",
  },
];

// ------------------------------------------------------------------ matching

function segments(path: string): string[] {
  return path.split("/").filter(Boolean);
}

/** Whether `path` fits `pattern`; `*` is one segment, a trailing `**` any depth. */
export function matchesPattern(pattern: string, path: string): boolean {
  const want = segments(pattern);
  const have = segments(path);
  for (let index = 0; index < want.length; index += 1) {
    const part = want[index];
    if (part === "**") return index === want.length - 1 && have.length > index;
    if (index >= have.length) return false;
    if (part !== "*" && part !== have[index]) return false;
  }
  return want.length === have.length;
}

/** Literal segments in a pattern: the more, the more specific the match. */
function specificity(pattern: string): number {
  return segments(pattern).filter((part) => part !== "*" && part !== "**").length;
}

export type Location = {
  area: NavArea;
  tab: NavTab;
  projectId: string | null;
  /** True on the tab's own page, false on something inside it. */
  isTabRoot: boolean;
};

/** Which area and tab a URL belongs to, or null for pages outside the tree. */
export function locate(pathname: string): Location | null {
  const clean = pathname.split("?")[0].replace(/\/+$/, "") || "/";
  const parts = segments(clean);

  let projectId: string | null = null;
  let scopedPath = clean;
  let scope: NavArea["scope"] = "global";
  if (parts[0] === "projects" && parts.length >= 2) {
    projectId = parts[1];
    scopedPath = `/${parts.slice(2).join("/")}`.replace(/\/$/, "") || "";
    scope = "project";
  }

  let best: { area: NavArea; tab: NavTab; isTabRoot: boolean; weight: number } | null = null;
  for (const area of AREAS) {
    if (area.scope !== scope) continue;
    for (const tab of area.tabs) {
      const candidates = [tab.path, ...(tab.also ?? [])];
      for (const pattern of candidates) {
        const fits =
          scope === "project" && pattern === ""
            ? scopedPath === ""
            : matchesPattern(pattern, scope === "project" ? scopedPath : clean);
        if (!fits) continue;
        // The tab's own path beats any `also` pattern of equal specificity.
        const weight = specificity(pattern) * 2 + (pattern === tab.path ? 1 : 0);
        if (!best || weight > best.weight) {
          best = { area, tab, isTabRoot: pattern === tab.path, weight };
        }
      }
    }
  }
  return best ? { area: best.area, tab: best.tab, isTabRoot: best.isTabRoot, projectId } : null;
}

// --------------------------------------------------------------------- hrefs

/** Where a tab lives; null when it needs a project and none is open. */
export function tabHref(area: NavArea, tab: NavTab, projectId: string | null): string | null {
  if (area.scope === "global") return tab.path;
  if (!projectId) return null;
  return `/projects/${projectId}${tab.path}`;
}

export function visibleTabs(area: NavArea, isAdmin: boolean): NavTab[] {
  return area.tabs.filter((tab) => isAdmin || !tab.adminOnly);
}

/**
 * Where clicking an area goes: its first tab. With no project open, a project
 * area sends you to the project list to choose one, never to a dead page.
 */
export function areaHref(area: NavArea, projectId: string | null, isAdmin = false): string {
  const first = visibleTabs(area, isAdmin)[0];
  return (first && tabHref(area, first, projectId)) ?? "/projects";
}

export function railAreas(isAdmin: boolean): NavArea[] {
  return AREAS.filter((area) => area.inRail && (isAdmin || !area.adminOnly));
}

export function areaById(id: AreaId): NavArea {
  const area = AREAS.find((candidate) => candidate.id === id);
  if (!area) throw new Error(`Unknown area ${id}`);
  return area;
}

// --------------------------------------------------------------- breadcrumbs

export type Crumb = { label: string; href?: string };

/**
 * Area › Tab › the page's own title when it is something inside the tab.
 * The project itself is not a crumb: the switcher beside the breadcrumb
 * already names it.
 */
export function breadcrumbsFor(pathname: string, title: string, isAdmin = false): Crumb[] {
  const location = locate(pathname);
  if (!location) {
    const page = STANDALONE_PAGES.find((candidate) => candidate.path === pathname);
    return [{ label: page?.label ?? title }];
  }
  const { area, tab, projectId, isTabRoot } = location;
  const crumbs: Crumb[] = [];
  const areaLink = areaHref(area, projectId, isAdmin);
  const tabLink = tabHref(area, tab, projectId) ?? undefined;
  // An area with one obvious first tab reads better as a single crumb:
  // "Overview", not "Overview › Overview".
  if (tab.label !== area.label) crumbs.push({ label: area.label, href: areaLink });
  crumbs.push({ label: tab.label, href: tabLink });
  if (!isTabRoot && title && title !== tab.label) crumbs.push({ label: title });
  return crumbs;
}
