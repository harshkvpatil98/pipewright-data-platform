import { describe, expect, it } from "vitest";

import { formatDateTime, formatDurationMs } from "./format";

describe("formatDateTime", () => {
  it("shows the minute in UTC, so two versions published the same day are distinguishable", () => {
    expect(formatDateTime("2026-09-23T10:59:07+00:00")).toBe("Sep 23, 2026, 10:59 AM UTC");
    expect(formatDateTime("2026-09-23T23:30:00+05:30")).toBe("Sep 23, 2026, 6:00 PM UTC");
  });
});

describe("formatDurationMs", () => {
  it("never says 0 ms for a sub-millisecond answer", () => {
    expect(formatDurationMs(0.4)).toBe("< 1 ms");
    expect(formatDurationMs(12.6)).toBe("13 ms");
    expect(formatDurationMs(2400)).toBe("2.4 s");
  });
});
