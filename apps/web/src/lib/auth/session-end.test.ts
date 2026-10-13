import { describe, expect, it } from "vitest";

import { safeNextPath, signInAgainHref } from "@/lib/auth/session-end";

describe("signInAgainHref", () => {
  it("comes back to the same page, query included", () => {
    expect(signInAgainHref("/projects/p1/studio?recipe=r1")).toBe(
      "/login?expired=1&next=%2Fprojects%2Fp1%2Fstudio%3Frecipe%3Dr1",
    );
  });
});

describe("safeNextPath", () => {
  it("keeps a path on this site", () => {
    expect(safeNextPath("/projects/p1/studio?recipe=r1")).toBe("/projects/p1/studio?recipe=r1");
  });

  it("refuses anywhere else", () => {
    expect(safeNextPath("https://example.com")).toBe("/projects");
    expect(safeNextPath("//example.com/x")).toBe("/projects");
    expect(safeNextPath("/\\example.com")).toBe("/projects");
    expect(safeNextPath("javascript:alert(1)")).toBe("/projects");
    expect(safeNextPath(null)).toBe("/projects");
  });
});
