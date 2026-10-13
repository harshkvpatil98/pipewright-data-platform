import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { parseMarkdown, type Block, type Inline } from "@/lib/help/markdown";
import { HELP_SLUGS, helpLinkFor } from "@/lib/help/pages";
import { AREAS } from "@/lib/navigation";
import { RETIRED, US_SPELLING } from "@/lib/voice";

/*
 * The help (A6, W2) stays whole: every page in docs/user/ is listed, every
 * link inside it lands on a page and a section that exist, every tab's
 * "Read more" does too, and the prose keeps the product's voice. Code and
 * web addresses are left out of the voice checks: an API path says
 * "pipelines" because that is its name.
 */

const FOLDER = fileURLToPath(new URL("../../../../../docs/user/", import.meta.url));

const pages = new Map(
  readdirSync(FOLDER)
    .filter((file) => file.endsWith(".md"))
    .map((file) => [file.replace(/\.md$/, ""), parseMarkdown(readFileSync(FOLDER + file, "utf8"))] as const),
);

function anchors(blocks: Block[]): Set<string> {
  return new Set(blocks.flatMap((block) => (block.kind === "heading" ? [block.id] : [])));
}

function inlines(blocks: Block[]): Inline[] {
  return blocks.flatMap((block) => {
    switch (block.kind) {
      case "paragraph":
      case "quote":
        return block.content;
      case "list":
        return block.items.flat();
      case "table":
        return [...block.header.flat(), ...block.rows.flat(2)];
      default:
        return [];
    }
  });
}

/** What a reader reads as prose: headings and text, without code. */
function prose(blocks: Block[]): string[] {
  const headings = blocks.flatMap((block) => (block.kind === "heading" ? [block.text] : []));
  const text = inlines(blocks).flatMap((part) => (part.kind === "code" ? [] : [part.text]));
  return [...headings, ...text];
}

/** "/help/data#sources" as [slug, anchor]. */
function target(href: string): [string, string | undefined] {
  const [path, anchor] = href.split("#");
  const slug = path === "/help" ? "index" : path.replace(/^\/help\//, "");
  return [slug, anchor];
}

describe("the help", () => {
  it("lists every page in docs/user, and only those", () => {
    expect([...pages.keys()].sort()).toEqual([...HELP_SLUGS].sort());
  });

  it("starts every page with one title", () => {
    for (const [slug, blocks] of pages) {
      expect(blocks[0], slug).toMatchObject({ kind: "heading", level: 1 });
      expect(blocks.filter((block) => block.kind === "heading" && block.level === 1), slug).toHaveLength(1);
    }
  });

  it("links only to pages and sections that exist", () => {
    const broken: string[] = [];
    for (const [slug, blocks] of pages) {
      for (const part of inlines(blocks)) {
        if (part.kind !== "link" || !/^(\/help|#)/.test(part.href)) continue;
        const [page, anchor] = part.href.startsWith("#") ? [slug, part.href.slice(1)] : target(part.href);
        const found = pages.get(page);
        if (!found || (anchor && !anchors(found).has(anchor))) broken.push(`${slug}: ${part.text} → ${part.href}`);
      }
    }
    expect(broken).toEqual([]);
  });

  it("has a section for every tab's Read more", () => {
    const missing: string[] = [];
    for (const area of AREAS) {
      for (const tab of area.tabs) {
        const link = helpLinkFor(area, tab);
        const found = pages.get(link.slug);
        if (!found || !anchors(found).has(link.anchor)) missing.push(`${area.label} › ${tab.label} → ${link.href}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("writes in the product's voice", () => {
    const hits: string[] = [];
    for (const [slug, blocks] of pages) {
      for (const text of prose(blocks)) {
        if (/\S\s*—\s*\S/.test(text)) hits.push(`${slug}: em-dash in "${text}"`);
        if (/\w\(s\)/.test(text)) hits.push(`${slug}: "(s)" in "${text}"`);
        if (US_SPELLING.test(text)) hits.push(`${slug}: US spelling in "${text}"`);
        for (const [pattern, instead] of RETIRED) {
          if (pattern.test(text)) hits.push(`${slug}: "${text.match(pattern)?.[0]}" (say: ${instead})`);
        }
      }
    }
    expect(hits).toEqual([]);
  });
});
