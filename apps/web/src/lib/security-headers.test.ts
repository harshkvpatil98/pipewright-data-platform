import { describe, expect, it } from "vitest";

import nextConfig, { FRAME_HEADERS, FRAMED_EVERYWHERE_BUT_EMBEDS, SECURITY_HEADERS } from "../../next.config";

/* The security page in the help says these are sent (A6, W7); this holds it to that. */
describe("security headers", () => {
  it("are sent with every page", async () => {
    const rules = (await nextConfig.headers?.()) ?? [];
    const everyPage = rules.find((rule) => rule.source === "/:path*");
    expect(everyPage?.headers).toEqual(SECURITY_HEADERS);
    const names = SECURITY_HEADERS.map((header) => header.key);
    expect(names).toEqual(expect.arrayContaining(["X-Content-Type-Options", "Referrer-Policy"]));
  });

  it("refuse framing everywhere but an embedded dashboard (A8, Y4)", async () => {
    const rules = (await nextConfig.headers?.()) ?? [];
    const framing = rules.find((rule) => rule.source === FRAMED_EVERYWHERE_BUT_EMBEDS);
    expect(framing?.headers).toEqual(FRAME_HEADERS);
    // The same pattern Next matches the source with, without its leading "/:path".
    const pattern = new RegExp(`^/${FRAMED_EVERYWHERE_BUT_EMBEDS.slice("/:path".length)}$`);
    for (const page of ["/", "/projects/abc", "/shared/dashboards/xyz", "/embedded", "/login"]) {
      expect(pattern.test(page)).toBe(true);
    }
    expect(pattern.test("/embed/a.b.c")).toBe(false);
  });
});

/* The retired recipe pages' addresses still open the recipe (E1). */
describe("old recipe addresses", () => {
  it("redirect to the Studio, a new recipe before an existing one", async () => {
    const rules = (await nextConfig.redirects?.()) ?? [];
    const sources = rules.map((rule) => rule.source);
    const newRecipe = sources.indexOf("/projects/:projectId/pipelines/new");
    const recipeSource = "/projects/:projectId/pipelines/:pipelineId([0-9a-fA-F-]{36})";
    const recipe = sources.indexOf(recipeSource);
    expect(newRecipe).toBeGreaterThan(-1);
    expect(newRecipe).toBeLessThan(recipe);
    const byDataset = rules.find(
      (rule) => rule.source === "/projects/:projectId/datasets/:datasetId/pipelines/:pipelineId([0-9a-fA-F-]{36})",
    );
    expect(byDataset?.destination).toBe("/projects/:projectId/studio?recipe=:pipelineId");
    expect(rules.find((rule) => rule.source === recipeSource)?.destination).toBe(
      "/projects/:projectId/studio?recipe=:pipelineId",
    );
  });

  it("leave the pages under /pipelines that are not a recipe, such as Bring work in (E2)", async () => {
    // The matcher Next.js itself reads a redirect's source with.
    // @ts-expect-error -- Next's own copy has no declarations.
    const { pathToRegexp } = (await import("next/dist/compiled/path-to-regexp")) as {
      pathToRegexp: (source: string) => RegExp;
    };
    const rules = (await nextConfig.redirects?.()) ?? [];
    const recipe = rules.find((rule) => rule.destination === "/projects/:projectId/studio?recipe=:pipelineId" &&
      !rule.source.includes("datasets"));
    const matches = pathToRegexp(recipe?.source ?? "");
    expect(matches.test("/projects/p1/pipelines/3f2a6c1e-9b7d-4e2f-8a1c-0d5e6f7a8b9c")).toBe(true);
    expect(matches.test("/projects/p1/pipelines/convert")).toBe(false);
  });
});
