import { type IconName } from "@platform/shared-ui";
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
        help: [
          "Follow the checklist to get a project working, one step at a time.",
          "See the newest data and the last few runs.",
          "Add data from here at any time.",
        ],
        keywords: "project home start checklist getting started",
      },
      {
        id: "people",
        label: "People",
        icon: "users",
        path: "/members",
        persona: "administrator",
        description: "Who can see and change this project.",
        help: [
          "Add people who already have an account, and choose what each can do.",
          "Viewers can look, operators can run things, editors can change them, admins can manage people.",
          "Removing someone takes away their access to this project only.",
        ],
        keywords: "members access roles invite team share",
      },
      {
        id: "alerts",
        label: "Alerts",
        icon: "bell",
        path: "/notification-targets",
        persona: "operator",
        description: "Where failures and reports are sent: email, Slack or a webhook.",
        help: [
          "Send failures and finished reports to an email address, a Slack channel or your own systems.",
          "Everything already appears in the bell at the top; this adds other places.",
          "Use Send a test to check one works before relying on it.",
        ],
        keywords: "notification targets slack email webhook",
      },
      {
        id: "settings",
        label: "Settings",
        icon: "settings",
        path: "/settings",
        persona: "administrator",
        description: "Rename, move, archive or delete this project.",
        help: [
          "Rename the project or describe what it is for.",
          "Move its recipes, checks, charts and workflows to another project with a bundle.",
          "Archive it when it is no longer used, or delete it when you are sure.",
        ],
        keywords: "project settings rename archive delete export import bundle move copy",
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
        help: [
          "Upload a file: Pipewright shows how it will read it before anything is saved.",
          "Connect a database, browse its tables and import the ones you need.",
          "Set imports to bring in only new rows, so each run is quick.",
        ],
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
        help: [
          "Every table of data in this project, one row per name.",
          "Open one to see its rows and columns, clean it in Studio, or send it somewhere.",
          "Filter by where the data came from, or find one by name.",
        ],
        keywords: "tables data files",
      },
      {
        id: "catalog",
        label: "Catalog",
        icon: "search",
        path: "/catalog",
        persona: "data owner",
        description: "Search datasets by name, column or tag, and keep the glossary.",
        help: [
          "Search datasets by name, by column or by what someone wrote about them.",
          "Keep a glossary so a word like “active customer” means one thing.",
          "Owners and certified datasets show here once people mark them.",
        ],
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
        help: [
          "Pick a dataset and add steps: filter rows, fix text, add columns and more.",
          "Click a step to change it. Right-click a column for steps that suit it.",
          "Every change shows in the preview straight away, and undo takes it back.",
          "Your original data is never changed; save the steps as a recipe to reuse them.",
        ],
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
        help: [
          "Recipes are saved sets of steps that turn one dataset into another.",
          "Open one to change its steps in the Studio, or run it to make a fresh result.",
          "Put a recipe on a schedule so it runs by itself.",
        ],
        keywords: "pipelines saved transformations",
      },
      {
        id: "sql",
        label: "SQL",
        icon: "sigma",
        path: "/workbench",
        persona: "data owner",
        description: "Write SQL against a connected database.",
        help: [
          "Write SQL against a connected database and see the results.",
          "It reads by default; writing needs an administrator.",
          "Save queries you use often.",
        ],
        keywords: "workbench query editor sql",
      },
      {
        id: "notebooks",
        label: "Notebooks",
        icon: "file",
        path: "/notebooks",
        persona: "data owner",
        description: "SQL, recipe and note cells that run top to bottom.",
        help: [
          "Mix SQL, recipe and text cells that run from top to bottom.",
          "Each cell can use the result of the cells above it.",
          "Save a notebook to run it again later.",
        ],
        keywords: "notebook python cells",
      },
      {
        id: "table-editor",
        label: "Table editor",
        icon: "table",
        path: "/table-editor",
        persona: "data owner",
        description: "Edit rows in a connected database table, with a preview before saving.",
        help: [
          "Change rows in a connected database table directly.",
          "You see every change, and how many rows it affects, before it is saved.",
          "Only tables with a clear way to identify each row can be edited.",
        ],
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
        help: [
          "Chain tasks in order: import, clean, check, deliver.",
          "If a check fails, the tasks after it stop, so bad data goes nowhere.",
          "Run a workflow by hand or on a timetable.",
        ],
        keywords: "dag orchestration tasks backfill",
      },
      {
        id: "schedules",
        label: "Schedules",
        icon: "clock",
        path: "/schedules",
        persona: "operator",
        description: "Run recipes and deliveries at set times.",
        help: [
          "Run a recipe or a delivery by itself at the times you choose.",
          "Pause a schedule without losing it.",
          "Run now tries it straight away without changing its timetable.",
        ],
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
        help: [
          "Everything that has run in this project, newest first.",
          "Filter to failed runs to see what needs attention.",
          "Open a run to see exactly what it did.",
        ],
        keywords: "history jobs failures audit",
      },
      {
        id: "destinations",
        label: "Destinations",
        icon: "send",
        path: "/destinations",
        persona: "operator",
        description: "Databases and file stores that receive your data.",
        help: [
          "Databases and file stores your data can be delivered to.",
          "Test a destination before sending data to it.",
          "Deliveries can run by hand, on a schedule or in a workflow.",
        ],
        keywords: "publish export deliver postgres s3",
      },
      {
        id: "bi-tools",
        label: "BI tools",
        icon: "barChart",
        path: "/bi-connections",
        persona: "operator",
        description: "Send datasets to Power BI or Tableau.",
        help: [
          "Connect Power BI or Tableau.",
          "Send a dataset to them from the dataset’s Send to menu.",
          "Test the connection before relying on it.",
        ],
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
        help: [
          "Checks are rules your data must pass, such as “every order has an email”.",
          "Run them on a dataset to see which rows fail.",
          "Failing rows can be set aside in their own dataset while the rest carries on.",
        ],
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
        help: [
          "Saved statistical comparisons between two datasets.",
          "Run one again after the data changes to see if it still holds.",
        ],
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
        help: [
          "Problems that need a person: failed checks, late data, unusual numbers.",
          "Acknowledge one to show someone is on it; resolve it when fixed.",
          "Incidents close by themselves when the problem clears.",
        ],
        keywords: "alerts problems freshness anomalies",
      },
      {
        id: "schema-changes",
        label: "Schema changes",
        icon: "drift",
        path: "/schema-drift",
        persona: "operator",
        description: "Columns added, removed or retyped at a source.",
        help: [
          "Columns added, removed or retyped at a source since the last import.",
          "Breaking changes are marked, because they can stop recipes working.",
          "Acknowledge a change once you have dealt with it.",
        ],
        keywords: "drift schema columns breaking",
      },
      {
        id: "policies",
        label: "Policies",
        icon: "shield",
        path: "/governance",
        persona: "administrator",
        description: "Who sees which rows and columns, and how long data is kept.",
        help: [
          "Hide rows or columns from some people, or mask sensitive values.",
          "Decide how long old runs and history are kept.",
          "Handle requests to correct or erase someone’s personal data.",
        ],
        keywords: "governance security masking retention erasure gdpr",
      },
      {
        id: "approvals",
        label: "Approvals",
        icon: "checkCircle",
        path: "/changes",
        persona: "administrator",
        description: "Changes waiting for someone to approve them.",
        help: [
          "In projects that need approval, changes wait here for someone to accept them.",
          "Running things is never blocked; only changing what they are.",
          "Comment on a change before approving or rejecting it.",
        ],
        keywords: "change requests review approve",
      },
      {
        id: "audit",
        label: "Audit log",
        icon: "list",
        path: "/audit-log",
        persona: "administrator",
        description: "Who changed what in this project, and when.",
        help: [
          "Who changed what in this project, and when.",
          "Refused attempts are recorded too.",
          "Filter by person or by what happened.",
        ],
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
        help: [
          "Pages of charts that answer one question together.",
          "Share a dashboard by link, or have it emailed on a schedule.",
          "Embed it in another site, such as a customer portal.",
          "Filters at the top apply to every chart on it.",
        ],
        keywords: "dashboard bi share link embed iframe portal",
      },
      {
        id: "charts",
        label: "Charts",
        icon: "barChart",
        path: "/charts",
        persona: "data owner",
        description: "Ask a question of a dataset and save the answer as a chart.",
        help: [
          "Pick a dataset, what to group by and what to add up.",
          "The preview updates as you change it.",
          "Save a chart, then put it on a dashboard.",
        ],
        keywords: "chart graph visualise visualize plot",
      },
      {
        id: "reports",
        label: "Reports",
        icon: "download",
        path: "/reports",
        persona: "data owner",
        description: "Files sent by email or Slack on a schedule.",
        help: [
          "Send a dataset, chart or dashboard as a file on a timetable.",
          "Excel, CSV, PDF or a web page, by email or Slack.",
          "Each report keeps a history of what was sent.",
        ],
        keywords: "scheduled reports export excel pdf csv email",
      },
      {
        id: "metrics",
        label: "Metrics",
        icon: "sigma",
        path: "/metrics",
        persona: "data owner",
        description: "Numbers defined once, so every chart agrees.",
        help: [
          "Define an important number once, such as net revenue.",
          "Charts and reports built on a metric always agree.",
          "Changing a definition keeps a history of the old ones.",
        ],
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
        // "Accounts", not "People": the project's own People tab is who can
        // open one project; this is everyone who can sign in at all.
        id: "accounts",
        label: "Accounts",
        icon: "users",
        path: "/people",
        adminOnly: true,
        persona: "administrator",
        description: "Everyone who can sign in: invite, reset, deactivate.",
        help: [
          "Everyone who can sign in to this platform.",
          "Invite someone, reset a password, or turn an account off.",
          "Project access is set inside each project, under People.",
        ],
        keywords: "users people invite admin sign in",
      },
      {
        id: "organisations",
        label: "Organisations",
        icon: "grid",
        path: "/organisations",
        adminOnly: true,
        persona: "administrator",
        description: "Separate groups of people and projects.",
        help: [
          "Keep separate groups of people and projects apart.",
          "A small team usually needs none.",
        ],
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
        help: [
          "Every change in every project, in one place.",
          "Filter it, and export it for an auditor.",
        ],
        keywords: "audit center export compliance",
      },
      {
        id: "connectors",
        label: "Connectors",
        icon: "link",
        path: "/connectors",
        persona: "administrator",
        description: "Every kind of source the platform can connect to.",
        help: [
          "Every kind of source Pipewright can connect to.",
          "Each shows how well it is tested, so you know what to expect.",
        ],
        keywords: "connector catalogue integrations saas",
      },
      {
        id: "status",
        label: "System status",
        icon: "activity",
        path: "/system-status",
        persona: "administrator",
        description: "Whether the platform and its background work are healthy.",
        help: [
          "Whether the platform and its background work are running.",
          "Check here first when runs or schedules seem stuck.",
        ],
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
        help: [
          "What needs attention across your projects.",
          "Jump back into a project, or start a new one.",
        ],
        keywords: "start dashboard welcome",
      },
      {
        id: "projects",
        label: "Projects",
        icon: "folder",
        path: "/projects",
        persona: "data owner",
        description: "All projects you can open, and a new one.",
        help: [
          "Every project you can open.",
          "Start a new project for a new team or subject.",
        ],
        keywords: "workspaces new project",
      },
      {
        id: "runs",
        label: "All runs",
        icon: "activity",
        path: "/runs",
        persona: "operator",
        description: "Recent runs across every project.",
        help: [
          "Recent runs across every project you can open.",
          "Filter to failures to see what needs attention anywhere.",
        ],
        keywords: "history failures",
      },
      {
        id: "datasets",
        label: "Find a dataset",
        icon: "search",
        path: "/datasets",
        persona: "data owner",
        description: "Search datasets across every project.",
        help: [
          "Find a dataset by name across every project you can open.",
        ],
        keywords: "search tables",
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
    label: "Help",
    icon: "book",
    description: "How to use Pipewright: getting started, each area, the glossary and the API.",
    also: ["/help/*"],
  },
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
