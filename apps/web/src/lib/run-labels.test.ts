import { describe, expect, it } from "vitest";

import { formatNotificationEventLabel, formatRunStatusLabel, formatRunTypeLabel } from "@/lib/run-labels";

describe("formatRunTypeLabel", () => {
  it("maps known run types", () => {
    expect(formatRunTypeLabel("dataset_publish_postgres")).toBe("PostgreSQL publish");
  });

  it("falls back for unknown types", () => {
    expect(formatRunTypeLabel("custom_job")).toBe("custom job");
  });

  it("handles empty", () => {
    expect(formatRunTypeLabel(null)).toBe("Pipeline run");
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
    expect(formatNotificationEventLabel("transformation_run_succeeded")).toBe("Transformation");
  });

  it("falls back for unknown types", () => {
    expect(formatNotificationEventLabel("custom_alert")).toBe("custom alert");
  });
});
