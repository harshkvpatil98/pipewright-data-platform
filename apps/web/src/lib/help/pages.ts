import { slugify } from "@/lib/help/markdown";
import type { AreaId, NavArea, NavTab } from "@/lib/navigation";

export { HELP_GROUPS, HELP_SLUGS } from "./groups";

/** The page's address in the app: `index` is the help's front page. */
export function helpPath(slug: string, anchor?: string): string {
  const base = slug === "index" ? "/help" : `/help/${slug}`;
  return anchor ? `${base}#${anchor}` : base;
}

/** Which help page explains each area. */
const AREA_PAGES: Record<AreaId, string> = {
  overview: "overview",
  data: "data",
  build: "build",
  automate: "automate",
  trust: "trust",
  share: "share",
  admin: "admin",
  workspace: "index",
};

/** Tabs whose section in the help is headed differently from the tab's label. */
const TAB_SECTIONS: Partial<Record<string, string>> = {
  "admin/audit": "audit",
  "workspace/home": "finding-your-way",
  "workspace/projects": "finding-your-way",
  "workspace/runs": "finding-your-way",
  "workspace/datasets": "finding-your-way",
};

/** Where "Read more" in a tab's "About this page" goes: its area's page, at its own section. */
export function helpLinkFor(area: Pick<NavArea, "id">, tab: Pick<NavTab, "id" | "label">): {
  slug: string;
  anchor: string;
  href: string;
} {
  const slug = AREA_PAGES[area.id];
  const anchor = TAB_SECTIONS[`${area.id}/${tab.id}`] ?? slugify(tab.label);
  return { slug, anchor, href: helpPath(slug, anchor) };
}
