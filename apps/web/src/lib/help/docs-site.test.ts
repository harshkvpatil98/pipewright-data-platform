import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// @ts-expect-error -- a plain script, built and run by Node as it is.
import { buildSite, siteHref } from "../../../scripts/build-docs-site.mjs";

/*
 * The help as a static site (A9, Z3): every page is written, and every link
 * and picture on it lands on something that exists.
 */
describe("the docs site", () => {
  it("turns help addresses into file addresses", () => {
    expect(siteHref("/help")).toBe("index.html");
    expect(siteHref("/help/trust#checks")).toBe("trust.html#checks");
    expect(siteHref("/help/images/alerts.png")).toBe("images/alerts.png");
    expect(siteHref("https://example.com")).toBe("https://example.com");
  });

  it("writes every page, and every link and picture on it resolves", () => {
    const out = mkdtempSync(join(tmpdir(), "docs-site-"));
    const pages: string[] = buildSite(out);
    expect(pages).toContain("index.html");
    expect(existsSync(join(out, "style.css"))).toBe(true);
    const ids = new Map(
      pages.map((page) => [page, new Set([...readFileSync(join(out, page), "utf8").matchAll(/ id="([^"]+)"/g)].map((match) => match[1]))]),
    );
    const broken: string[] = [];
    for (const page of pages) {
      const html = readFileSync(join(out, page), "utf8");
      for (const [, href] of html.matchAll(/ href="([^"#]*\.html)(?:#([^"]*))?"/g).map((match) => [match[0], match[1], match[2]])) {
        if (!existsSync(join(out, href))) broken.push(`${page} → ${href}`);
      }
      for (const match of html.matchAll(/ href="([^"#]*\.html)#([^"]+)"/g)) {
        if (!ids.get(match[1])?.has(match[2])) broken.push(`${page} → ${match[1]}#${match[2]}`);
      }
      for (const match of html.matchAll(/ src="([^"]+)"/g)) {
        if (!existsSync(join(out, match[1]))) broken.push(`${page} → ${match[1]}`);
      }
    }
    expect(broken).toEqual([]);
  });
});
