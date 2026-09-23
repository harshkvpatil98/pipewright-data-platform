import { describe, expect, it } from "vitest";

import type { DashboardTile } from "@platform/shared-types";

import {
  clampHeight,
  clampWidth,
  describeAge,
  describeFilter,
  describeRefresh,
  draftFromTiles,
  formatDeltaPct,
  moveTile,
  parseFilterValue,
  toTilePayload,
} from "./dashboard-layout";

const tile = (over: Partial<DashboardTile>): DashboardTile => ({
  id: "t",
  kind: "chart",
  chart_id: "c",
  title: null,
  body: null,
  position: 0,
  width: 6,
  height: 1,
  chart: null,
  ...over,
});

describe("dashboard layout", () => {
  it("orders drafts by stored position and rewrites positions from list order on save", () => {
    const drafts = draftFromTiles([
      tile({ id: "b", position: 1 }),
      tile({ id: "a", position: 0 }),
      tile({ id: "c", position: 2, kind: "text", chart_id: null, body: "note" }),
    ]);
    expect(drafts.map((d) => d.key)).toEqual(["a", "b", "c"]);
    const payload = toTilePayload(moveTile(drafts, 2, 0));
    expect(payload.map((t) => t.position)).toEqual([0, 1, 2]);
    expect(payload[0]).toMatchObject({ kind: "text", body: "note", chart_id: null });
    // A chart tile never carries text fields; a text tile never carries a chart.
    expect(payload[1]).toMatchObject({ kind: "chart", chart_id: "c", title: null, body: null });
  });

  it("moveTile ignores out-of-range moves instead of corrupting the list", () => {
    const items = ["a", "b", "c"];
    expect(moveTile(items, 0, 5)).toBe(items);
    expect(moveTile(items, -1, 0)).toBe(items);
    expect(moveTile(items, 0, 2)).toEqual(["b", "c", "a"]);
  });

  it("clamps sizes to what the grid can hold", () => {
    expect(clampWidth(1)).toBe(2);
    expect(clampWidth(40)).toBe(12);
    expect(clampWidth(Number.NaN)).toBe(6);
    expect(clampHeight(0)).toBe(1);
    expect(clampHeight(9)).toBe(4);
  });

  it("describes filters in words a reader can parse", () => {
    expect(describeFilter({ column: "region", operator: "equals", value: "north" })).toBe("region is north");
    expect(describeFilter({ column: "amount", operator: "greater_than", value: 0 })).toBe("amount > 0");
    expect(describeFilter({ column: "email", operator: "is_null", value: null })).toBe("email is empty");
    expect(describeFilter({ column: "region", operator: "in", value: ["a", "b"] })).toBe("region is one of a, b");
  });

  it("parses typed filter values into numbers, lists and text", () => {
    expect(parseFilterValue("equals", "42")).toBe(42);
    expect(parseFilterValue("equals", "north")).toBe("north");
    expect(parseFilterValue("in", "a, 2 ,c")).toEqual(["a", 2, "c"]);
    expect(parseFilterValue("is_null", "ignored")).toBeNull();
    // Leading zeros are an identifier, not a number.
    expect(parseFilterValue("equals", "007")).toBe("007");
    expect(parseFilterValue("equals", "0")).toBe(0);
    expect(parseFilterValue("equals", "-1.5")).toBe(-1.5);
  });

  it("describes refresh cadence and age plainly", () => {
    expect(describeRefresh(null)).toBe("manual refresh only");
    expect(describeRefresh(300)).toBe("every 5 minutes");
    const now = new Date("2026-09-23T12:00:00Z");
    expect(describeAge("2026-09-23T11:59:58Z", now)).toBe("just now");
    expect(describeAge("2026-09-23T11:57:00Z", now)).toBe("3 minutes ago");
    expect(describeAge("2026-09-23T13:00:00Z", now)).toBe("just now"); // never negative
  });

  it("formats a delta percentage with an explicit sign", () => {
    expect(formatDeltaPct(0.125)).toBe("+12.5%");
    expect(formatDeltaPct(-0.03)).toBe("−3.0%");
    expect(formatDeltaPct(0)).toBe("0.0%");
    expect(formatDeltaPct(null)).toBeNull();
  });
});
