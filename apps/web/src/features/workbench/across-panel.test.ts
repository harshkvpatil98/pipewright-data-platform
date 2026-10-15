import { describe, expect, it } from "vitest";

import { acrossExample, databases, plainName } from "@/features/workbench/across-panel";

const connection = (name: string, connector_type: string) => ({ id: name, name, connector_type, status: "active" });

describe("across sources", () => {
  it("writes a connection's name the way the server reads it unquoted", () => {
    expect(plainName("Shop DB")).toBe("shop_db");
    expect(plainName("  CRM (EU) ")).toBe("crm_eu");
  });

  it("offers only databases, and an example that names one", () => {
    const list = [connection("Files", "s3"), connection("Sales PG", "postgresql")];
    expect(databases(list).map((item) => item.name)).toEqual(["Sales PG"]);
    expect(acrossExample(list)).toContain("FROM sales_pg.public.orders AS o");
    expect(acrossExample([])).toContain('FROM datasets."Orders" AS o');
  });
});
