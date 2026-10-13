import { describe, expect, it } from "vitest";

import { chartTitle, chooseChartDefaults } from "@/features/reporting/chart-defaults";

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

  it("groups by a text column before a date", () => {
    expect(
      chooseChartDefaults(["order_date", "region", "amount"], {
        order_date: "date",
        region: "string",
        amount: "float",
      }).dimension,
    ).toBe("region");
  });

  it("adds up the amount before a quantity", () => {
    expect(
      chooseChartDefaults(["region", "quantity", "amount"], {
        region: "string",
        quantity: "int",
        amount: "float",
      }).measure,
    ).toBe("amount");
  });

  it("copes before types are known", () => {
    expect(chooseChartDefaults(["a", "b"], {})).toEqual({
      dimension: "a",
      measure: "a",
      aggregation: "count",
    });
  });
});

describe("chartTitle", () => {
  it("names a chart in words", () => {
    expect(chartTitle("sum", "amount", "region")).toBe("Amount by region");
    expect(chartTitle("count", "order_id", "status")).toBe("Rows by status");
    expect(chartTitle("avg", "unit_price", "product")).toBe("Average unit price by product");
    expect(chartTitle("sum", "total_amount", null)).toBe("Total amount");
  });
});
