import { type IconName } from "@platform/shared-ui";

import { t, tList } from "@/lib/i18n";
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
  /**
   * What someone can do on this page, two to four short sentences, shown by
   * "About this page". Written for a person who has never seen it.
   */
  help: string[];
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
    label: t("nav.areas.overview.label"),
    icon: "home",
    scope: "project",
    inRail: true,
    description: t("nav.areas.overview.description"),
    tabs: [
      {
        id: "overview",
        label: t("nav.tabs.overview.overview.label"),
        icon: "home",
        path: "",
        persona: "data owner",
        description: t("nav.tabs.overview.overview.description"),
        help: tList("nav.tabs.overview.overview.help"),
        keywords: t("nav.tabs.overview.overview.keywords"),
      },
      {
        id: "activity",
        label: t("nav.tabs.overview.activity.label"),
        icon: "activity",
        path: "/activity",
        persona: "data owner",
        description: t("nav.tabs.overview.activity.description"),
        help: tList("nav.tabs.overview.activity.help"),
        keywords: t("nav.tabs.overview.activity.keywords"),
      },
      {
        id: "people",
        label: t("nav.tabs.overview.people.label"),
        icon: "users",
        path: "/members",
        persona: "administrator",
        description: t("nav.tabs.overview.people.description"),
        help: tList("nav.tabs.overview.people.help"),
        keywords: t("nav.tabs.overview.people.keywords"),
      },
      {
        id: "alerts",
        label: t("nav.tabs.overview.alerts.label"),
        icon: "bell",
        path: "/notification-targets",
        persona: "operator",
        description: t("nav.tabs.overview.alerts.description"),
        help: tList("nav.tabs.overview.alerts.help"),
        keywords: t("nav.tabs.overview.alerts.keywords"),
      },
      {
        id: "settings",
        label: t("nav.tabs.overview.settings.label"),
        icon: "settings",
        path: "/settings",
        persona: "administrator",
        description: t("nav.tabs.overview.settings.description"),
        help: tList("nav.tabs.overview.settings.help"),
        keywords: t("nav.tabs.overview.settings.keywords"),
      },
    ],
  },
  {
    id: "data",
    label: t("nav.areas.data.label"),
    icon: "database",
    scope: "project",
    inRail: true,
    description: t("nav.areas.data.description"),
    tabs: [
      {
        id: "sources",
        label: t("nav.tabs.data.sources.label"),
        icon: "database",
        path: "/sources",
        persona: "data owner",
        description: t("nav.tabs.data.sources.description"),
        help: tList("nav.tabs.data.sources.help"),
        keywords: t("nav.tabs.data.sources.keywords"),
      },
      {
        id: "live",
        label: t("nav.tabs.data.live.label"),
        icon: "zap",
        path: "/live",
        also: ["/live/*"],
        persona: "data owner",
        description: t("nav.tabs.data.live.description"),
        help: tList("nav.tabs.data.live.help"),
        keywords: t("nav.tabs.data.live.keywords"),
      },
      {
        id: "datasets",
        label: t("nav.tabs.data.datasets.label"),
        icon: "table",
        path: "/datasets",
        also: ["/datasets/*", "/datasets/*/**"],
        persona: "data owner",
        description: t("nav.tabs.data.datasets.description"),
        help: tList("nav.tabs.data.datasets.help"),
        keywords: t("nav.tabs.data.datasets.keywords"),
      },
      {
        id: "catalog",
        label: t("nav.tabs.data.catalog.label"),
        icon: "search",
        path: "/catalog",
        persona: "data owner",
        description: t("nav.tabs.data.catalog.description"),
        help: tList("nav.tabs.data.catalog.help"),
        keywords: t("nav.tabs.data.catalog.keywords"),
      },
    ],
  },
  {
    id: "build",
    label: t("nav.areas.build.label"),
    icon: "wrench",
    scope: "project",
    inRail: true,
    description: t("nav.areas.build.description"),
    tabs: [
      {
        id: "studio",
        label: t("nav.tabs.build.studio.label"),
        icon: "transform",
        path: "/studio",
        persona: "data owner",
        description: t("nav.tabs.build.studio.description"),
        help: tList("nav.tabs.build.studio.help"),
        keywords: t("nav.tabs.build.studio.keywords"),
      },
      {
        id: "recipes",
        label: t("nav.tabs.build.recipes.label"),
        icon: "book",
        path: "/pipelines",
        also: ["/pipelines/**", "/datasets/*/pipelines/*"],
        persona: "data owner",
        description: t("nav.tabs.build.recipes.description"),
        help: tList("nav.tabs.build.recipes.help"),
        keywords: t("nav.tabs.build.recipes.keywords"),
      },
      {
        id: "sql",
        label: t("nav.tabs.build.sql.label"),
        icon: "sigma",
        path: "/workbench",
        persona: "data owner",
        description: t("nav.tabs.build.sql.description"),
        help: tList("nav.tabs.build.sql.help"),
        keywords: t("nav.tabs.build.sql.keywords"),
      },
      {
        id: "notebooks",
        label: t("nav.tabs.build.notebooks.label"),
        icon: "file",
        path: "/notebooks",
        persona: "data owner",
        description: t("nav.tabs.build.notebooks.description"),
        help: tList("nav.tabs.build.notebooks.help"),
        keywords: t("nav.tabs.build.notebooks.keywords"),
      },
      {
        id: "table-editor",
        label: t("nav.tabs.build.table-editor.label"),
        icon: "table",
        path: "/table-editor",
        persona: "data owner",
        description: t("nav.tabs.build.table-editor.description"),
        help: tList("nav.tabs.build.table-editor.help"),
        keywords: t("nav.tabs.build.table-editor.keywords"),
      },
    ],
  },
  {
    id: "automate",
    label: t("nav.areas.automate.label"),
    icon: "zap",
    scope: "project",
    inRail: true,
    description: t("nav.areas.automate.description"),
    tabs: [
      {
        id: "workflows",
        label: t("nav.tabs.automate.workflows.label"),
        icon: "merge",
        path: "/workflows",
        also: ["/workflows/*"],
        persona: "operator",
        description: t("nav.tabs.automate.workflows.description"),
        help: tList("nav.tabs.automate.workflows.help"),
        keywords: t("nav.tabs.automate.workflows.keywords"),
      },
      {
        id: "schedules",
        label: t("nav.tabs.automate.schedules.label"),
        icon: "clock",
        path: "/schedules",
        persona: "operator",
        description: t("nav.tabs.automate.schedules.description"),
        help: tList("nav.tabs.automate.schedules.help"),
        keywords: t("nav.tabs.automate.schedules.keywords"),
      },
      {
        id: "runs",
        label: t("nav.tabs.automate.runs.label"),
        icon: "activity",
        path: "/runs",
        also: ["/runs/*/**"],
        persona: "operator",
        description: t("nav.tabs.automate.runs.description"),
        help: tList("nav.tabs.automate.runs.help"),
        keywords: t("nav.tabs.automate.runs.keywords"),
      },
      {
        id: "destinations",
        label: t("nav.tabs.automate.destinations.label"),
        icon: "send",
        path: "/destinations",
        persona: "operator",
        description: t("nav.tabs.automate.destinations.description"),
        help: tList("nav.tabs.automate.destinations.help"),
        keywords: t("nav.tabs.automate.destinations.keywords"),
      },
      {
        id: "bi-tools",
        label: t("nav.tabs.automate.bi-tools.label"),
        icon: "barChart",
        path: "/bi-connections",
        persona: "operator",
        description: t("nav.tabs.automate.bi-tools.description"),
        help: tList("nav.tabs.automate.bi-tools.help"),
        keywords: t("nav.tabs.automate.bi-tools.keywords"),
      },
    ],
  },
  {
    id: "trust",
    label: t("nav.areas.trust.label"),
    icon: "shieldCheck",
    scope: "project",
    inRail: true,
    description: t("nav.areas.trust.description"),
    tabs: [
      {
        id: "checks",
        label: t("nav.tabs.trust.checks.label"),
        icon: "check",
        path: "/checks",
        persona: "data owner",
        description: t("nav.tabs.trust.checks.description"),
        help: tList("nav.tabs.trust.checks.help"),
        keywords: t("nav.tabs.trust.checks.keywords"),
      },
      {
        id: "comparisons",
        label: t("nav.tabs.trust.comparisons.label"),
        icon: "columns",
        path: "/tests/saved",
        also: ["/tests/saved/*", "/datasets/*/compare/*"],
        persona: "data owner",
        description: t("nav.tabs.trust.comparisons.description"),
        help: tList("nav.tabs.trust.comparisons.help"),
        keywords: t("nav.tabs.trust.comparisons.keywords"),
      },
      {
        id: "incidents",
        label: t("nav.tabs.trust.incidents.label"),
        icon: "warning",
        path: "/incidents",
        also: ["/incidents/*"],
        persona: "operator",
        description: t("nav.tabs.trust.incidents.description"),
        help: tList("nav.tabs.trust.incidents.help"),
        keywords: t("nav.tabs.trust.incidents.keywords"),
      },
      {
        id: "schema-changes",
        label: t("nav.tabs.trust.schema-changes.label"),
        icon: "drift",
        path: "/schema-drift",
        persona: "operator",
        description: t("nav.tabs.trust.schema-changes.description"),
        help: tList("nav.tabs.trust.schema-changes.help"),
        keywords: t("nav.tabs.trust.schema-changes.keywords"),
      },
      {
        id: "contracts",
        label: t("nav.tabs.trust.contracts.label"),
        icon: "contract",
        path: "/contracts",
        persona: "data owner",
        description: t("nav.tabs.trust.contracts.description"),
        help: tList("nav.tabs.trust.contracts.help"),
        keywords: t("nav.tabs.trust.contracts.keywords"),
      },
      {
        id: "policies",
        label: t("nav.tabs.trust.policies.label"),
        icon: "shield",
        path: "/governance",
        persona: "administrator",
        description: t("nav.tabs.trust.policies.description"),
        help: tList("nav.tabs.trust.policies.help"),
        keywords: t("nav.tabs.trust.policies.keywords"),
      },
      {
        id: "approvals",
        label: t("nav.tabs.trust.approvals.label"),
        icon: "checkCircle",
        path: "/changes",
        persona: "administrator",
        description: t("nav.tabs.trust.approvals.description"),
        help: tList("nav.tabs.trust.approvals.help"),
        keywords: t("nav.tabs.trust.approvals.keywords"),
      },
      {
        id: "audit",
        label: t("nav.tabs.trust.audit.label"),
        icon: "list",
        path: "/audit-log",
        persona: "administrator",
        description: t("nav.tabs.trust.audit.description"),
        help: tList("nav.tabs.trust.audit.help"),
        keywords: t("nav.tabs.trust.audit.keywords"),
      },
    ],
  },
  {
    id: "share",
    label: t("nav.areas.share.label"),
    icon: "share",
    scope: "project",
    inRail: true,
    description: t("nav.areas.share.description"),
    tabs: [
      {
        id: "dashboards",
        label: t("nav.tabs.share.dashboards.label"),
        icon: "grid",
        path: "/dashboards",
        also: ["/dashboards/*"],
        persona: "data owner",
        description: t("nav.tabs.share.dashboards.description"),
        help: tList("nav.tabs.share.dashboards.help"),
        keywords: t("nav.tabs.share.dashboards.keywords"),
      },
      {
        id: "charts",
        label: t("nav.tabs.share.charts.label"),
        icon: "barChart",
        path: "/charts",
        persona: "data owner",
        description: t("nav.tabs.share.charts.description"),
        help: tList("nav.tabs.share.charts.help"),
        keywords: t("nav.tabs.share.charts.keywords"),
      },
      {
        id: "reports",
        label: t("nav.tabs.share.reports.label"),
        icon: "download",
        path: "/reports",
        persona: "data owner",
        description: t("nav.tabs.share.reports.description"),
        help: tList("nav.tabs.share.reports.help"),
        keywords: t("nav.tabs.share.reports.keywords"),
      },
      {
        id: "metrics",
        label: t("nav.tabs.share.metrics.label"),
        icon: "sigma",
        path: "/metrics",
        persona: "data owner",
        description: t("nav.tabs.share.metrics.description"),
        help: tList("nav.tabs.share.metrics.help"),
        keywords: t("nav.tabs.share.metrics.keywords"),
      },
    ],
  },
  {
    id: "admin",
    label: t("nav.areas.admin.label"),
    icon: "key",
    scope: "global",
    inRail: true,
    adminOnly: true,
    description: t("nav.areas.admin.description"),
    tabs: [
      {
        // "Accounts", not "People": the project's own People tab is who can
        // open one project; this is everyone who can sign in at all.
        id: "accounts",
        label: t("nav.tabs.admin.accounts.label"),
        icon: "users",
        path: "/people",
        adminOnly: true,
        persona: "administrator",
        description: t("nav.tabs.admin.accounts.description"),
        help: tList("nav.tabs.admin.accounts.help"),
        keywords: t("nav.tabs.admin.accounts.keywords"),
      },
      {
        id: "organisations",
        label: t("nav.tabs.admin.organisations.label"),
        icon: "grid",
        path: "/organisations",
        adminOnly: true,
        persona: "administrator",
        description: t("nav.tabs.admin.organisations.description"),
        help: tList("nav.tabs.admin.organisations.help"),
        keywords: t("nav.tabs.admin.organisations.keywords"),
      },
      {
        id: "audit",
        label: t("nav.tabs.admin.audit.label"),
        icon: "list",
        path: "/audits",
        adminOnly: true,
        persona: "administrator",
        description: t("nav.tabs.admin.audit.description"),
        help: tList("nav.tabs.admin.audit.help"),
        keywords: t("nav.tabs.admin.audit.keywords"),
      },
      {
        id: "connectors",
        label: t("nav.tabs.admin.connectors.label"),
        icon: "link",
        path: "/connectors",
        persona: "administrator",
        description: t("nav.tabs.admin.connectors.description"),
        help: tList("nav.tabs.admin.connectors.help"),
        keywords: t("nav.tabs.admin.connectors.keywords"),
      },
      {
        id: "status",
        label: t("nav.tabs.admin.status.label"),
        icon: "activity",
        path: "/system-status",
        persona: "administrator",
        description: t("nav.tabs.admin.status.description"),
        help: tList("nav.tabs.admin.status.help"),
        keywords: t("nav.tabs.admin.status.keywords"),
      },
    ],
  },
  {
    id: "workspace",
    label: t("nav.areas.workspace.label"),
    icon: "home",
    scope: "global",
    inRail: false,
    description: t("nav.areas.workspace.description"),
    tabs: [
      {
        id: "home",
        label: t("nav.tabs.workspace.home.label"),
        icon: "home",
        path: "/",
        persona: "data owner",
        description: t("nav.tabs.workspace.home.description"),
        help: tList("nav.tabs.workspace.home.help"),
        keywords: t("nav.tabs.workspace.home.keywords"),
      },
      {
        id: "projects",
        label: t("nav.tabs.workspace.projects.label"),
        icon: "folder",
        path: "/projects",
        persona: "data owner",
        description: t("nav.tabs.workspace.projects.description"),
        help: tList("nav.tabs.workspace.projects.help"),
        keywords: t("nav.tabs.workspace.projects.keywords"),
      },
      {
        id: "runs",
        label: t("nav.tabs.workspace.runs.label"),
        icon: "activity",
        path: "/runs",
        persona: "operator",
        description: t("nav.tabs.workspace.runs.description"),
        help: tList("nav.tabs.workspace.runs.help"),
        keywords: t("nav.tabs.workspace.runs.keywords"),
      },
      {
        id: "datasets",
        label: t("nav.tabs.workspace.datasets.label"),
        icon: "search",
        path: "/datasets",
        persona: "data owner",
        description: t("nav.tabs.workspace.datasets.description"),
        help: tList("nav.tabs.workspace.datasets.help"),
        keywords: t("nav.tabs.workspace.datasets.keywords"),
      },
    ],
  },
];

/** Pages outside every area: reached from the top bar. */
export const STANDALONE_PAGES: {
  path: string;
  label: string;
  icon: IconName;
  description: string;
  /** Pages inside this one, written like a tab's `also`. */
  also?: string[];
}[] = [
  {
    path: "/help",
    label: t("nav.pages.help.label"),
    icon: "book",
    description: t("nav.pages.help.description"),
    also: ["/help/*"],
  },
  {
    path: "/notifications",
    label: t("nav.pages.notifications.label"),
    icon: "bell",
    description: t("nav.pages.notifications.description"),
  },
  {
    path: "/settings",
    label: t("nav.pages.settings.label"),
    icon: "settings",
    description: t("nav.pages.settings.description"),
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

/** A recipe opens in the Studio, wherever it is linked from. */
export function recipeHref(projectId: string, recipeId: string): string {
  return `/projects/${projectId}/studio?recipe=${recipeId}`;
}

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
    if (page) return [{ label: page.label }];
    const parent = STANDALONE_PAGES.find((candidate) =>
      (candidate.also ?? []).some((pattern) => matchesPattern(pattern, pathname)),
    );
    return parent ? [{ label: parent.label, href: parent.path }, { label: title }] : [{ label: title }];
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
