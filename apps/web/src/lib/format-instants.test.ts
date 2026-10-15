import { describe, expect, it } from "vitest";

import { formatDateTime, formatDateUtc, formatDurationMs, formatTimeUtc } from "./format";

describe("formatDateTime", () => {
  it("shows the minute in UTC, so two versions published the same day are distinguishable", () => {
    expect(formatDateTime("2026-09-23T10:59:07+00:00")).toBe("23 Sept 2026, 10:59 UTC");
    expect(formatDateTime("2026-09-23T23:30:00+05:30")).toBe("23 Sept 2026, 18:00 UTC");
  });
});

describe("formatTimeUtc and formatDateUtc", () => {
  it("split an instant into its UTC time and date, agreeing with formatDateTime", () => {
    expect(formatTimeUtc("2026-09-23T23:30:00+05:30")).toBe("18:00 UTC");
    expect(formatDateUtc("2026-09-24T01:30:00+05:30")).toBe("23 Sept 2026");
  });
});

describe("formatDurationMs", () => {
  it("never says 0 ms for a sub-millisecond answer", () => {
    expect(formatDurationMs(0.4)).toBe("< 1 ms");
    expect(formatDurationMs(12.6)).toBe("13 ms");
    expect(formatDurationMs(2400)).toBe("2.4 s");
  });
});
