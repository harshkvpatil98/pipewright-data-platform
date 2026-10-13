import "server-only";

import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { parseMarkdown, summarise, type Block } from "@/lib/help/markdown";
import { HELP_GROUPS, HELP_SLUGS } from "@/lib/help/pages";

/**
 * Reads the help from `docs/user/`, which ships with the app, so the help
 * always describes the version that is running. The web app runs from its
 * own folder in development and in the image, and from the repository root
 * in some tools; both are tried.
 */
function helpFolder(): string {
  const candidates = [resolve(process.cwd(), "docs/user"), resolve(process.cwd(), "../../docs/user")];
  return candidates.find((folder) => existsSync(join(folder, "index.md"))) ?? candidates[0];
}

export type HelpPage = { slug: string; title: string; summary: string; blocks: Block[] };

const cache = new Map<string, HelpPage>();

export function readHelpPage(slug: string): HelpPage | null {
  if (!HELP_SLUGS.includes(slug)) return null;
  const cached = cache.get(slug);
  if (cached && process.env.NODE_ENV === "production") return cached;
  const file = join(helpFolder(), `${slug}.md`);
  if (!existsSync(file)) return null;
  const blocks = parseMarkdown(readFileSync(file, "utf8"));
  const page = { slug, ...summarise(blocks), blocks };
  cache.set(slug, page);
  return page;
}

export type HelpContents = { label: string; pages: { slug: string; title: string }[] }[];

/** The side list: every help page's title, by group. */
export function helpContents(): HelpContents {
  return HELP_GROUPS.map((group) => ({
    label: group.label,
    pages: group.slugs.flatMap((slug) => {
      const page = readHelpPage(slug);
      return page ? [{ slug, title: page.title }] : [];
    }),
  }));
}
