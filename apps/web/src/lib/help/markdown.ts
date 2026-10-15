/**
 * A small Markdown reader for the help pages (A6, W2).
 *
 * The help is written in plain Markdown in `docs/user/` and rendered into the
 * app at build time. It needs headings, paragraphs, lists, tables, quotes,
 * code, links and pictures of the screen (A9, Z2: a line of its own,
 * `![what it shows](images/name.png)`), nothing more, so this parses exactly that into blocks a
 * React component draws. Keeping it in-house avoids a dependency for a page
 * of text, and keeps the output in the product's own styles.
 */

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "strong"; text: string }
  | { kind: "code"; text: string }
  | { kind: "link"; text: string; href: string };

export type Block =
  | { kind: "heading"; level: 1 | 2 | 3; text: string; id: string }
  | { kind: "paragraph"; content: Inline[] }
  | { kind: "list"; ordered: boolean; items: Inline[][] }
  | { kind: "quote"; content: Inline[] }
  | { kind: "code"; language: string; text: string }
  | { kind: "table"; header: Inline[][]; rows: Inline[][][] }
  | { kind: "image"; alt: string; src: string };

/** A picture beside the help is served from `/help/images/`; anything else as written. */
export function imageSrc(src: string): string {
  return /^images\/[\w-]+\.png$/.test(src) ? `/help/${src}` : src;
}

/** "Add a check" becomes "add-a-check": the anchor a heading can be linked by. */
export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .trim()
    .replace(/\s+/g, "-");
}

/** A link inside the help ("data.md#sources") points at the help page for it. */
export function helpHref(href: string): string {
  if (/^(https?:|mailto:|\/|#)/.test(href)) return href;
  const [file, anchor] = href.split("#");
  const slug = (file ?? "").replace(/^\.\//, "").replace(/\.md$/, "");
  const base = !slug || slug === "index" ? "/help" : `/help/${slug}`;
  return anchor ? `${base}#${anchor}` : base;
}

export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\[[^\]]+\]\([^)]+\))/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    const at = match.index ?? 0;
    if (at > last) out.push({ kind: "text", text: text.slice(last, at) });
    const token = match[0];
    if (token.startsWith("`")) out.push({ kind: "code", text: token.slice(1, -1) });
    else if (token.startsWith("**")) out.push({ kind: "strong", text: token.slice(2, -2) });
    else {
      const [, label, href] = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token) ?? [];
      out.push({ kind: "link", text: label ?? token, href: helpHref(href ?? "") });
    }
    last = at + token.length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}

function cells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

export function parseMarkdown(source: string): Block[] {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    if (heading) {
      const text = heading[2].trim();
      blocks.push({ kind: "heading", level: heading[1].length as 1 | 2 | 3, text, id: slugify(text) });
      index += 1;
      continue;
    }
    const image = /^!\[([^\]]*)\]\(([^)\s]+)\)\s*$/.exec(line.trim());
    if (image) {
      blocks.push({ kind: "image", alt: image[1].trim(), src: imageSrc(image[2]) });
      index += 1;
      continue;
    }
    if (line.startsWith("```")) {
      const language = line.slice(3).trim();
      const body: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) body.push(lines[index++]);
      index += 1;
      blocks.push({ kind: "code", language, text: body.join("\n") });
      continue;
    }
    if (line.trim().startsWith("|")) {
      const rows: string[][] = [];
      while (index < lines.length && lines[index].trim().startsWith("|")) rows.push(cells(lines[index++]));
      const body = rows.filter((row, at) => !(at === 1 && row.every((cell) => /^:?-+:?$/.test(cell))));
      const [header, ...rest] = body;
      blocks.push({
        kind: "table",
        header: (header ?? []).map(parseInline),
        rows: rest.map((row) => row.map(parseInline)),
      });
      continue;
    }
    if (line.startsWith(">")) {
      const body: string[] = [];
      while (index < lines.length && lines[index].startsWith(">")) body.push(lines[index++].replace(/^>\s?/, ""));
      blocks.push({ kind: "quote", content: parseInline(body.join(" ")) });
      continue;
    }
    const bullet = /^(\s*)([-*]|\d+\.)\s+(.*)$/;
    if (bullet.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items: string[] = [];
      while (index < lines.length && lines[index].trim()) {
        const item = bullet.exec(lines[index]);
        if (item) items.push(item[3]);
        else if (items.length) items[items.length - 1] += ` ${lines[index].trim()}`;
        index += 1;
      }
      blocks.push({ kind: "list", ordered, items: items.map(parseInline) });
      continue;
    }
    const paragraph: string[] = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^(#{1,3}\s|```|>|\s*([-*]|\d+\.)\s|\||!\[)/.test(lines[index])
    ) {
      paragraph.push(lines[index++].trim());
    }
    blocks.push({ kind: "paragraph", content: parseInline(paragraph.join(" ")) });
  }
  return blocks;
}

/** The page's title (its first heading) and the first paragraph after it, as plain text. */
export function summarise(blocks: Block[]): { title: string; summary: string } {
  const heading = blocks.find((block) => block.kind === "heading");
  const paragraph = blocks.find((block) => block.kind === "paragraph");
  const plain = (content: Inline[]) => content.map((part) => part.text).join("");
  return {
    title: heading && heading.kind === "heading" ? heading.text : "Help",
    summary: paragraph && paragraph.kind === "paragraph" ? plain(paragraph.content) : "",
  };
}
