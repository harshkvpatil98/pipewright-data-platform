import { describe, expect, it } from "vitest";

import nextConfig, { SECURITY_HEADERS } from "../../next.config";

/* The security page in the help says these are sent (A6, W7); this holds it to that. */
describe("security headers", () => {
  it("are sent with every page", async () => {
    const rules = (await nextConfig.headers?.()) ?? [];
    const everyPage = rules.find((rule) => rule.source === "/:path*");
    expect(everyPage?.headers).toEqual(SECURITY_HEADERS);
    const names = SECURITY_HEADERS.map((header) => header.key);
    expect(names).toEqual(expect.arrayContaining(["X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy"]));
  });
});
