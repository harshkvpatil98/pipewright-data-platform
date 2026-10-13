import { describe, expect, it } from "vitest";

import { RENEW_WITHIN_SECONDS, shouldRenew, tokenExpiry } from "@/lib/auth/renewal";

const tokenWith = (claims: Record<string, unknown>) =>
  `header.${btoa(JSON.stringify(claims)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")}.signature`;

describe("session renewal timing", () => {
  it("reads the expiry of a sign-in token", () => {
    expect(tokenExpiry(tokenWith({ exp: 1_800_000_000, sub: "u" }))).toBe(1_800_000_000);
    expect(tokenExpiry("pw_api_token")).toBeNull();
    expect(tokenExpiry("a.not-base64!.c")).toBeNull();
  });

  it("renews only in the last stretch of a still-valid token", () => {
    const now = 1_000_000;
    expect(shouldRenew(tokenWith({ exp: now + RENEW_WITHIN_SECONDS + 60 }), now)).toBe(false);
    expect(shouldRenew(tokenWith({ exp: now + 120 }), now)).toBe(true);
    expect(shouldRenew(tokenWith({ exp: now - 1 }), now)).toBe(false);
    expect(shouldRenew("pw_api_token", now)).toBe(false);
  });
});
