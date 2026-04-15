import { describe, expect, it } from "vitest";

import { serviceHealthTone, toneClasses } from "@/features/system-status/system-status-helpers";

describe("serviceHealthTone", () => {
  it("maps gateway statuses", () => {
    expect(serviceHealthTone("healthy")).toBe("success");
    expect(serviceHealthTone("degraded")).toBe("warning");
    expect(serviceHealthTone("unhealthy")).toBe("danger");
  });
});

describe("toneClasses", () => {
  it("returns non-empty classes", () => {
    expect(toneClasses("success").length).toBeGreaterThan(10);
  });
});
