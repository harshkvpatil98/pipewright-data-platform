import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearAccessToken, getAccessToken, setAccessToken } from "@/lib/auth/session";

describe("auth session storage", () => {
  let mockStorage: Record<string, string>;

  beforeEach(() => {
    mockStorage = {};
    vi.stubGlobal(
      "window",
      {
        localStorage: {
          getItem: (key: string) => mockStorage[key] ?? null,
          setItem: (key: string, value: string) => {
            mockStorage[key] = value;
          },
          removeItem: (key: string) => {
            delete mockStorage[key];
          },
        },
      } as unknown as Window & typeof globalThis,
    );
    let cookie = "";
    vi.stubGlobal(
      "document",
      {
        set cookie(value: string) {
          cookie = value;
        },
        get cookie() {
          return cookie;
        },
      } as unknown as Document,
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("stores and clears access tokens", () => {
    setAccessToken("token-value");
    expect(getAccessToken()).toBe("token-value");
    expect(document.cookie).toContain("idp_access_token=token-value");
    clearAccessToken();
    expect(getAccessToken()).toBeNull();
  });
});
