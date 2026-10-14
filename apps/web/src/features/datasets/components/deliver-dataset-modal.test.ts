import { describe, expect, it } from "vitest";

import type { DeliveryResult } from "@platform/shared-types";

import { resultFromRun, tableNameFor } from "./deliver-dataset-modal";

const started: DeliveryResult = {
  run_id: "r1",
  status: "queued",
  target: "public.orders",
  mode: "update",
  message: "Delivering 120,000 rows to public.orders in the background.",
  rows_written: 0,
  rows_updated: 0,
  rows_added: 0,
  table_created: null,
  warnings: [],
};

describe("a delivery the worker wrote", () => {
  it("reads the counts and warnings from the finished run", () => {
    const result = resultFromRun(started, {
      status: "succeeded",
      logs_json: { events: [{ message: "Writing 120,000 rows to public.orders." }] },
      summary_json: { rows_written: 120000, rows_updated: 20000, rows_added: 100000, warnings: ["Two columns were text."] },
    });
    expect(result.status).toBe("succeeded");
    expect(result.message).toBe("Delivered 120,000 rows to public.orders.");
    expect([result.rows_updated, result.rows_added]).toEqual([20000, 100000]);
    expect(result.warnings).toEqual(["Two columns were text."]);
  });

  it("says why it failed, in the run's words", () => {
    const failed = resultFromRun(started, {
      status: "failed",
      logs_json: { events: [{ message: "Waiting." }, { message: "The server refused the connection." }] },
      summary_json: null,
    });
    expect(failed.status).toBe("failed");
    expect(failed.message).toBe("The server refused the connection.");
    expect(failed.rows_written).toBe(0);
  });

  it("one row is a row", () => {
    const one = resultFromRun(started, { status: "succeeded", logs_json: null, summary_json: { rows_written: 1 } });
    expect(one.message).toBe("Delivered 1 row to public.orders.");
  });
});

describe("table names", () => {
  it("come from the dataset name", () => {
    expect(tableNameFor("Sample customers")).toBe("sample_customers");
    expect(tableNameFor("2024 orders")).toBe("t_2024_orders");
  });
});
