/**
 * The help as a static website (adoption-readiness A9, Z3).
 *
 *   node apps/web/scripts/build-docs-site.mjs [output folder]   # default: docs-site/
 *
 * Every page of `docs/user/` is read with the same Markdown reader `/help`
 * uses (`src/lib/help/markdown.ts`), in the same order (`groups.ts`), so the
 * site and the help inside the product cannot say different things. Links
 * between pages become links between files, pictures are copied beside them,
 * and the result is plain HTML and one stylesheet: it can be served from any
 * static host. `.github/workflows/docs-site.yml` publishes it when the owner
 * runs it.
 */
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { HELP_GROUPS, HELP_SLUGS } from "../src/lib/help/groups.ts";
import { parseMarkdown, summarise } from "../src/lib/help/markdown.ts";

const DOCS = fileURLToPath(new URL("../../../docs/user/", import.meta.url));

const escape = (text) =>
  String(text).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");

/** "/help/data#sources" becomes "data.html#sources"; other addresses are left as they are. */
export function siteHref(href) {
  if (href === "/help" || href.startsWith("/help#")) return `index.html${href.slice(5)}`;
  const page = /^\/help\/([\w-]+)(#.*)?$/.exec(href);
  if (page) return `${page[1]}.html${page[2] ?? ""}`;
  const image = /^\/help\/images\/([\w-]+\.png)$/.exec(href);
  if (image) return `images/${image[1]}`;
  return href;
}

function inline(parts) {
  return parts
    .map((part) => {
      if (part.kind === "strong") return `<strong>${escape(part.text)}</strong>`;
      if (part.kind === "code") return `<code>${escape(part.text)}</code>`;
      if (part.kind === "link") {
        const outside = /^https?:/.test(part.href);
        return `<a href="${escape(siteHref(part.href))}"${outside ? ' rel="noreferrer"' : ""}>${escape(part.text)}</a>`;
      }
      return escape(part.text);
    })
    .join("");
}

function block(item) {
  switch (item.kind) {
    case "heading":
      return `<h${item.level} id="${escape(item.id)}">${escape(item.text)}</h${item.level}>`;
    case "paragraph":
      return `<p>${inline(item.content)}</p>`;
    case "list": {
      const tag = item.ordered ? "ol" : "ul";
      return `<${tag}>${item.items.map((entry) => `<li>${inline(entry)}</li>`).join("")}</${tag}>`;
    }
    case "quote":
      return `<aside>${inline(item.content)}</aside>`;
    case "code":
      return `<pre><code>${escape(item.text)}</code></pre>`;
    case "table":
      return `<table><thead><tr>${item.header.map((cell) => `<th>${inline(cell)}</th>`).join("")}</tr></thead><tbody>${item.rows
        .map((row) => `<tr>${row.map((cell) => `<td>${inline(cell)}</td>`).join("")}</tr>`)
        .join("")}</tbody></table>`;
    case "image":
      return `<figure><img src="${escape(siteHref(item.src))}" alt="${escape(item.alt)}" loading="lazy"><figcaption>${escape(item.alt)}</figcaption></figure>`;
    default:
      return "";
  }
}

const STYLE = `:root{--ink:#16201f;--ink-2:#3b4746;--ink-3:#5d6968;--line:#dfe5e3;--surface:#f6f8f7;--accent:#0f766e;--panel:#fff}
@media (prefers-color-scheme:dark){:root{--ink:#e7eeec;--ink-2:#c3cdca;--ink-3:#97a3a0;--line:#2b3533;--surface:#141a19;--accent:#2dd4bf;--panel:#0f1413}}
*{box-sizing:border-box}body{margin:0;background:var(--panel);color:var(--ink-2);font:15px/1.7 system-ui,-apple-system,"Segoe UI",sans-serif}
.layout{display:grid;grid-template-columns:240px minmax(0,1fr);max-width:1180px;margin:0 auto;gap:40px;padding:32px 20px}
nav{position:sticky;top:24px;align-self:start;font-size:14px}nav h2{font-size:12px;color:var(--ink-3);margin:20px 0 6px;font-weight:600}
nav a{display:block;padding:4px 8px;border-radius:8px;color:var(--ink-2);text-decoration:none}nav a[aria-current]{background:var(--surface);color:var(--ink);font-weight:600}
.brand{font-weight:700;color:var(--ink);font-size:16px;text-decoration:none}
main{max-width:760px}h1{font-size:28px;color:var(--ink);margin:0 0 8px}h2{font-size:20px;color:var(--ink);margin-top:36px;padding-top:24px;border-top:1px solid var(--line)}
h3{font-size:16px;color:var(--ink)}a{color:var(--accent)}code{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:1px 5px;font-size:13px}
pre{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 16px;overflow-x:auto}pre code{border:0;padding:0;background:none}
aside{border:1px solid var(--line);background:var(--surface);border-radius:12px;padding:12px 16px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
figure{margin:20px 0}img{max-width:100%;border:1px solid var(--line);border-radius:12px}figcaption{font-size:13px;color:var(--ink-3);margin-top:6px}
@media (max-width:820px){.layout{grid-template-columns:1fr}nav{position:static}}`;

function pageHtml(slug, title, body) {
  const nav = HELP_GROUPS.map(
    (group) =>
      `<h2>${escape(group.label)}</h2>${group.slugs
        .map((each) => `<a href="${each}.html"${each === slug ? ' aria-current="page"' : ""}>${escape(titles.get(each))}</a>`)
        .join("")}`,
  ).join("");
  return `<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escape(title)} · Pipewright help</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<div class="layout">
<nav aria-label="Help pages"><a class="brand" href="index.html">Pipewright help</a>${nav}</nav>
<main>${body}</main>
</div>
</body>
</html>
`;
}

const titles = new Map();
const parsed = new Map();
for (const slug of HELP_SLUGS) {
  const blocks = parseMarkdown(readFileSync(join(DOCS, `${slug}.md`), "utf8"));
  parsed.set(slug, blocks);
  titles.set(slug, summarise(blocks).title);
}

export function buildSite(out) {
  mkdirSync(join(out, "images"), { recursive: true });
  for (const slug of HELP_SLUGS) {
    writeFileSync(join(out, `${slug}.html`), pageHtml(slug, titles.get(slug), parsed.get(slug).map(block).join("\n")));
  }
  if (existsSync(join(DOCS, "images"))) {
    for (const file of readdirSync(join(DOCS, "images")).filter((name) => name.endsWith(".png"))) {
      copyFileSync(join(DOCS, "images", file), join(out, "images", file));
    }
  }
  writeFileSync(join(out, "style.css"), STYLE);
  return HELP_SLUGS.map((slug) => `${slug}.html`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const out = resolve(process.argv[2] ?? "docs-site");
  const written = buildSite(out);
  console.log(`Wrote ${written.length} pages to ${out}`);
}
