import { describe, expect, it } from "vitest";

import { frameAncestors, parseEmbedOrigins } from "./embed-origins";

describe("embed origins", () => {
  it("keeps sites' addresses and names what it ignores", () => {
    const origins = parseEmbedOrigins(
      "https://portal.example.com, https://*.partner.io  http://localhost:8080 https://Portal.example.com/ " +
        "portal.example.com http://insecure.example.com https://a.example.com/path 'none' https://x.com;script-src",
    );
    expect(origins.allowed).toEqual(["https://portal.example.com", "https://*.partner.io", "http://localhost:8080"]);
    expect(origins.ignored).toEqual([
      "portal.example.com",
      "http://insecure.example.com",
      "https://a.example.com/path",
      "'none'",
      "https://x.com;script-src",
    ]);
  });

  it("lets only this site frame an embed when none are listed", () => {
    expect(frameAncestors(parseEmbedOrigins(undefined))).toBe("'self'");
    expect(frameAncestors(parseEmbedOrigins("https://portal.example.com"))).toBe("'self' https://portal.example.com");
  });
});
