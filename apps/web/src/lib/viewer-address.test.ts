import { describe, expect, it } from "vitest";

import { viewerAddress } from "./viewer-address";

describe("viewer address", () => {
  it("is read as the API reads it", () => {
    expect(viewerAddress("203.0.113.7", 1)).toBe("203.0.113.7");
    // A viewer can add entries of their own; only the trusted proxies' count.
    expect(viewerAddress("10.9.9.9, 203.0.113.7", 1)).toBe("203.0.113.7");
    expect(viewerAddress("10.9.9.9, 203.0.113.7, 10.0.0.2", 2)).toBe("203.0.113.7");
    expect(viewerAddress("203.0.113.7", 3)).toBe("203.0.113.7");
  });

  it("is not passed on when no proxy is trusted", () => {
    expect(viewerAddress("203.0.113.7", 0)).toBeNull();
    expect(viewerAddress(null, 1)).toBeNull();
    expect(viewerAddress(" , ", 1)).toBeNull();
  });
});
