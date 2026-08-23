import { describe, expect, it } from "vitest";

import {
  NODE_HEIGHT,
  NODE_WIDTH,
  canvasExtent,
  edgeMidpoint,
  edgePath,
  inputPort,
  outputPort,
  snap,
  tidyLayout,
  toNodeKey,
} from "@/features/workflows/canvas-geometry";

const node = (key: string, x: number, y: number) => ({
  node_key: key,
  position_x: x,
  position_y: y,
});

describe("ports", () => {
  it("leaves a node from its right edge and enters at its left", () => {
    const box = node("a", 100, 200);
    expect(outputPort(box)).toEqual({ x: 100 + NODE_WIDTH, y: 200 + NODE_HEIGHT / 2 });
    expect(inputPort(box)).toEqual({ x: 100, y: 200 + NODE_HEIGHT / 2 });
  });
});

describe("edgePath", () => {
  it("starts and ends at the given points", () => {
    const path = edgePath({ x: 0, y: 0 }, { x: 300, y: 100 });
    expect(path.startsWith("M 0 0")).toBe(true);
    expect(path.endsWith("300 100")).toBe(true);
  });

  it("caps the curve so long edges do not bow excessively", () => {
    const long = edgePath({ x: 0, y: 0 }, { x: 5000, y: 0 });
    // The first control point is offset by the cap, not half the distance.
    expect(long).toContain("C 140 0");
  });

  it("keeps a minimum curve for very short edges", () => {
    const short = edgePath({ x: 0, y: 0 }, { x: 10, y: 0 });
    expect(short).toContain("C 40 0");
  });

  it("finds the midpoint for the condition label", () => {
    expect(edgeMidpoint({ x: 0, y: 0 }, { x: 100, y: 50 })).toEqual({ x: 50, y: 25 });
  });
});

describe("tidyLayout", () => {
  it("places each dependency level in its own column", () => {
    const layout = tidyLayout([["a"], ["b"], ["c"]], ["a", "b", "c"]);
    expect(layout.a.x).toBeLessThan(layout.b.x);
    expect(layout.b.x).toBeLessThan(layout.c.x);
  });

  it("stacks nodes that run in parallel within one column", () => {
    const layout = tidyLayout([["a"], ["b", "c"]], ["a", "b", "c"]);
    expect(layout.b.x).toBe(layout.c.x);
    expect(layout.b.y).not.toBe(layout.c.y);
  });

  it("still places nodes the server could not order", () => {
    // An invalid graph returns no ordering, but the nodes must stay visible.
    const layout = tidyLayout([], ["orphan_a", "orphan_b"]);
    expect(layout.orphan_a).toBeDefined();
    expect(layout.orphan_b).toBeDefined();
    expect(layout.orphan_a.y).not.toBe(layout.orphan_b.y);
  });

  it("puts unordered nodes after the ordered ones", () => {
    const layout = tidyLayout([["a"]], ["a", "loose"]);
    expect(layout.loose.x).toBeGreaterThan(layout.a.x);
  });
});

describe("canvasExtent", () => {
  it("covers the furthest node plus room to drag", () => {
    const extent = canvasExtent([node("a", 0, 0), node("b", 600, 400)]);
    expect(extent.width).toBeGreaterThan(600 + NODE_WIDTH);
    expect(extent.height).toBeGreaterThan(400 + NODE_HEIGHT);
  });

  it("handles an empty canvas", () => {
    expect(canvasExtent([]).width).toBeGreaterThan(0);
  });
});

describe("snap", () => {
  it("rounds to the grid", () => {
    expect(snap(103)).toBe(100);
    expect(snap(107)).toBe(110);
  });
});

describe("toNodeKey", () => {
  it("converts a label into a valid key", () => {
    expect(toNodeKey("Pull Invoices")).toBe("pull_invoices");
  });

  it("strips punctuation and collapses separators", () => {
    expect(toNodeKey("Extract -- orders (daily)")).toBe("extract_orders_daily");
  });

  it("prefixes a label that starts with a digit", () => {
    // The backend requires a letter first.
    expect(toNodeKey("2024 refresh")).toMatch(/^[a-z]/);
  });

  it("falls back when a label has nothing usable", () => {
    expect(toNodeKey("!!!")).toBe("node");
  });

  it("disambiguates against keys already in use", () => {
    expect(toNodeKey("Extract", ["extract"])).toBe("extract_2");
    expect(toNodeKey("Extract", ["extract", "extract_2"])).toBe("extract_3");
  });
});
