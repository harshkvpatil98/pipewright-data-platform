import { describe, expect, it } from "vitest";

import { serviceLabel } from "@/lib/service-labels";

describe("serviceLabel", () => {
  it("names modules in words", () => {
    expect(serviceLabel("service-observability")).toBe("Monitoring");
    expect(serviceLabel("postgres")).toBe("Database");
  });

  it("still shows a module it does not know", () => {
    expect(serviceLabel("service-new-thing")).toBe("New thing");
  });
});
