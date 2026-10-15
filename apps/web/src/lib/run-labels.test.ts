import { describe, expect, it } from "vitest";

import { formatNotificationEventLabel, formatRunStatusLabel, formatRunTypeLabel, formatStageLabel } from "@/lib/run-labels";

describe("formatRunTypeLabel", () => {
  it("maps known run types", () => {
    // A0 vocabulary: "deliver" and "recipe", not "publish" and "transformation".
    expect(formatRunTypeLabel("dataset_publish_postgres")).toBe("Delivered to PostgreSQL");
    expect(formatRunTypeLabel("database_extraction")).toBe("Import");
  });

  it("falls back for unknown types", () => {
    expect(formatRunTypeLabel("custom_job")).toBe("custom job");
  });

  it("handles empty", () => {
    expect(formatRunTypeLabel(null)).toBe("Run");
  });
});

describe("formatRunStatusLabel", () => {
  it("maps known statuses", () => {
    expect(formatRunStatusLabel("succeeded")).toBe("Succeeded");
    expect(formatRunStatusLabel("FAILED")).toBe("Failed");
  });

  it("handles empty", () => {
    expect(formatRunStatusLabel(null)).toBe("—");
  });
});

describe("formatNotificationEventLabel", () => {
  it("maps known notification types", () => {
    expect(formatNotificationEventLabel("transformation_run_succeeded")).toBe("Recipe run");
  });

  it("falls back for unknown types", () => {
    expect(formatNotificationEventLabel("custom_alert")).toBe("custom alert");
  });
});

describe("formatStageLabel", () => {
  it("names each stage in words, the new ones included", () => {
    expect(formatStageLabel("parse")).toBe("Reading the rows");
    expect(formatStageLabel("incremental")).toBe("Computing only what changed");
    expect(formatStageLabel("reused")).toBe("Reusing earlier work");
    expect(formatStageLabel("check_contract")).toBe("Checking the contract");
    expect(formatStageLabel("apply_step_3")).toBe("Step 3");
    expect(formatStageLabel("something_new")).toBe("Something new");
    expect(formatStageLabel(null)).toBe("Step");
  });
});
