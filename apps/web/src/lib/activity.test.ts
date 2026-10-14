import { describe, expect, it } from "vitest";

import type { ActivityItem } from "@platform/shared-types";

import { byDay, dayLabel } from "@/features/activity/components/activity-page";

const item = (id: string, at: string): ActivityItem => ({
  id,
  kind: "changes",
  at,
  who: null,
  sentence: id,
  detail: null,
  level: "info",
  href: null,
});

/* The Activity page's days (A8, Y6), in the viewer's own time zone. */
describe("activity", () => {
  const now = new Date(2026, 9, 15, 9, 30);

  it("names today and yesterday, and dates the rest", () => {
    expect(dayLabel(new Date(2026, 9, 15, 0, 5).toISOString(), now)).toBe("Today");
    expect(dayLabel(new Date(2026, 9, 14, 23, 55).toISOString(), now)).toBe("Yesterday");
    expect(dayLabel(new Date(2026, 9, 12, 12, 0).toISOString(), now)).toBe("Monday, 12 October 2026");
  });

  it("groups the stream by day without reordering it", () => {
    const groups = byDay(
      [
        item("a", new Date(2026, 9, 15, 9, 0).toISOString()),
        item("b", new Date(2026, 9, 15, 8, 0).toISOString()),
        item("c", new Date(2026, 9, 14, 18, 0).toISOString()),
      ],
      now,
    );
    expect(groups.map((group) => [group.day, group.items.map((entry) => entry.id)])).toEqual([
      ["Today", ["a", "b"]],
      ["Yesterday", ["c"]],
    ]);
  });
});
