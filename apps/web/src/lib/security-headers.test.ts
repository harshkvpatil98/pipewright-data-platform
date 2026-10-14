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
