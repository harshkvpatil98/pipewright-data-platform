import { describe, expect, it } from "vitest";

import { chooseChartDefaults } from "@/features/reporting/chart-defaults";

describe("chooseChartDefaults", () => {
  it("groups by text and sums a real number, not the id", () => {
    expect(
      chooseChartDefaults(["id", "region", "amount"], { id: "int", region: "string", amount: "float" }),
    ).toEqual({ dimension: "region", measure: "amount", aggregation: "sum" });
  });

  it("counts rows when nothing can be summed, so the first chart still draws", () => {
    expect(
      chooseChartDefaults(["id", "name", "email"], { id: "string", name: "string", email: "string" }),
    ).toEqual({ dimension: "name", measure: "id", aggregation: "count" });
  });

  it("treats customer_id and orderId as identifiers", () => {
    const defaults = chooseChartDefaults(["customer_id", "orderId", "city"], {
      customer_id: "int",
      orderId: "int",
      city: "string",
    });
    expect(defaults.aggregation).toBe("count");
    expect(defaults.dimension).toBe("city");
  });

  it("copes before types are known", () => {
    expect(chooseChartDefaults(["a", "b"], {})).toEqual({
      dimension: "a",
      measure: "a",
      aggregation: "count",
    });
  });
});
