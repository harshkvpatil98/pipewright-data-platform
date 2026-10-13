import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  AREAS,
  STANDALONE_PAGES,
  areaHref,
  breadcrumbsFor,
  locate,
  matchesPattern,
  railAreas,
  tabHref,
} from "@/lib/navigation";

const APP_DIR = fileURLToPath(new URL("../app", import.meta.url));

/** Every page route in src/app, with each [param] replaced by "x". */
function appRoutes(): { route: string; file: string }[] {
  const found: { route: string; file: string }[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const path = join(dir, entry);
      if (statSync(path).isDirectory()) walk(path);
      else if (entry === "page.tsx") {
        const folder = relative(APP_DIR, dir).split(sep).filter(Boolean);
        const route = `/${folder.map((part) => (part.startsWith("[") ? "x" : part)).join("/")}`;
        found.push({ route: route === "/" ? "/" : route.replace(/\/$/, ""), file: path });
      }
    }
  };
  walk(APP_DIR);
  return found;
}

/** Pages with no frame at all: signing in and public share links. */
const FRAMELESS = new Set(["/login", "/sign-in", "/shared/dashboards/x"]);

function isRedirectOnly(file: string): boolean {
  const source = readFileSync(file, "utf8");
  return /redirectToProjectScope|^\s*redirect\(/m.test(source) && !/return\s*\(?\s*</.test(source);
}

describe("the navigation tree", () => {
  const routes = appRoutes();

  it("finds the app's routes", () => {
    expect(routes.length).toBeGreaterThan(40);
  });

  it("places every page in exactly one area, or names why it is outside", () => {
    const standalone = new Set(STANDALONE_PAGES.map((page) => page.path));
    const orphans = routes
      .filter(({ route, file }) => {
        if (FRAMELESS.has(route) || standalone.has(route) || isRedirectOnly(file)) return false;
        return locate(route) === null;
      })
      .map(({ route }) => route);
    expect(orphans).toEqual([]);
  });

  it("points every tab at a page that exists", () => {
    const known = new Set(routes.map(({ route }) => route));
    const missing: string[] = [];
    for (const area of AREAS) {
      for (const tab of area.tabs) {
        const href = tabHref(area, tab, "x");
        if (href && !known.has(href === "/projects/x" ? "/projects/x" : href)) missing.push(href);
      }
    }
    expect(missing).toEqual([]);
  });

  it("keeps the rail to seven items, admin included", () => {
    expect(railAreas(true).length).toBeLessThanOrEqual(7);
    expect(railAreas(false).map((area) => area.id)).not.toContain("admin");
  });

  it("gives each tab a label that is unique within its area", () => {
    for (const area of AREAS) {
      const labels = area.tabs.map((tab) => tab.label);
      expect(new Set(labels).size).toBe(labels.length);
    }
  });

  it("explains every page in a few short sentences", () => {
    for (const area of AREAS) {
      for (const tab of area.tabs) {
        expect(tab.help.length, `${area.id}/${tab.id}`).toBeGreaterThan(0);
        expect(tab.help.length, `${area.id}/${tab.id}`).toBeLessThanOrEqual(4);
        for (const sentence of tab.help) {
          expect(sentence.split(/\s+/).length, sentence).toBeLessThanOrEqual(20);
          expect(sentence, sentence).not.toMatch(/—/);
        }
      }
    }
  });

  it("uses a different icon for every rail area", () => {
    const icons = railAreas(true).map((area) => area.icon);
    expect(new Set(icons).size).toBe(icons.length);
  });

  it("resolves the pages people actually open", () => {
    const where = (path: string) => {
      const location = locate(path);
      return location ? `${location.area.id}/${location.tab.id}` : null;
    };
    expect(where("/")).toBe("workspace/home");
    expect(where("/projects")).toBe("workspace/projects");
    expect(where("/projects/p1")).toBe("overview/overview");
    expect(where("/projects/p1/sources")).toBe("data/sources");
    expect(where("/projects/p1/datasets/d1")).toBe("data/datasets");
    expect(where("/projects/p1/datasets/d1/lineage")).toBe("data/datasets");
    // More specific patterns win over the dataset's catch-all.
    expect(where("/projects/p1/datasets/d1/pipelines/r1")).toBe("build/recipes");
    expect(where("/projects/p1/datasets/d1/compare/d2")).toBe("trust/comparisons");
    expect(where("/projects/p1/runs")).toBe("automate/runs");
    expect(where("/projects/p1/runs/r1/audit")).toBe("automate/runs");
    expect(where("/runs")).toBe("workspace/runs");
    expect(where("/projects/p1/dashboards/b1")).toBe("share/dashboards");
    expect(where("/audits")).toBe("admin/audit");
    expect(where("/notifications")).toBeNull();
  });

  it("knows a tab's own page from something inside it", () => {
    expect(locate("/projects/p1/datasets")?.isTabRoot).toBe(true);
    expect(locate("/projects/p1/datasets/d1")?.isTabRoot).toBe(false);
  });

  it("sends a project area to the project list when no project is open", () => {
    const data = AREAS.find((area) => area.id === "data")!;
    expect(areaHref(data, null)).toBe("/projects");
    expect(areaHref(data, "p1")).toBe("/projects/p1/sources");
  });
});

describe("matchesPattern", () => {
  it("matches one segment with * and any depth with a trailing **", () => {
    expect(matchesPattern("/datasets/*", "/datasets/abc")).toBe(true);
    expect(matchesPattern("/datasets/*", "/datasets/abc/lineage")).toBe(false);
    expect(matchesPattern("/datasets/*/**", "/datasets/abc/lineage")).toBe(true);
    expect(matchesPattern("/datasets/*/**", "/datasets/abc")).toBe(false);
  });
});

describe("breadcrumbsFor", () => {
  it("reads area, tab, then the object", () => {
    expect(breadcrumbsFor("/projects/p1/datasets/d1", "orders")).toEqual([
      { label: "Data", href: "/projects/p1/sources" },
      { label: "Datasets", href: "/projects/p1/datasets" },
      { label: "orders" },
    ]);
  });

  it("does not repeat a tab that shares its area's name", () => {
    expect(breadcrumbsFor("/projects/p1", "Acme")).toEqual([
      { label: "Overview", href: "/projects/p1" },
    ]);
  });

  it("names pages outside the tree by their own title", () => {
    expect(breadcrumbsFor("/notifications", "Notifications")).toEqual([
      { label: "Notifications" },
    ]);
  });
});
