import { describe, expect, it } from "vitest";

import type { LineageEdge, LineageNode } from "@platform/shared-types";

import {
  COLUMN_GAP,
  NODE_HEIGHT,
  NODE_WIDTH,
  PADDING,
  edgePath,
  layoutLineage,
} from "@/features/lineage/lineage-layout";

const node = (
  id: string,
  depth: number,
  kind: LineageNode["kind"] = "dataset",
  name = id,
): LineageNode => ({
  id,
  kind,
  name,
  subtitle: null,
  depth,
  is_focus: depth === 0,
});

const edge = (from: string, to: string, kind: LineageEdge["kind"] = "produces"): LineageEdge => ({
  from_id: from,
  to_id: to,
  kind,
  label: null,
});

describe("layoutLineage", () => {
  it("places depth on the horizontal axis", () => {
    const layout = layoutLineage(
      [node("raw", -2), node("focus", 0), node("out", 2)],
      [],
    );
    const xs = layout.nodes.map((positioned) => positioned.x);
    expect(xs).toEqual([PADDING, PADDING + NODE_WIDTH + COLUMN_GAP, PADDING + 2 * (NODE_WIDTH + COLUMN_GAP)]);
  });

  it("centres shorter columns against the tallest one", () => {
    const layout = layoutLineage(
      [node("a", -1), node("b", 1), node("c", 1), node("d", 1)],
      [],
    );
    const single = layout.nodes.find((positioned) => positioned.id === "a")!;
    const middleOfThree = layout.nodes.filter((positioned) => positioned.depth === 1)[1];
    expect(single.y).toBeCloseTo(middleOfThree.y, 1);
  });

  it("orders datasets above pipelines within a column", () => {
    const layout = layoutLineage(
      [node("p", 1, "pipeline", "zeta"), node("d", 1, "dataset", "alpha")],
      [],
    );
    const ordered = layout.nodes.filter((n) => n.depth === 1).sort((a, b) => a.y - b.y);
    expect(ordered.map((n) => n.kind)).toEqual(["dataset", "pipeline"]);
  });

  it("draws edges from the right of one node to the left of the next", () => {
    const layout = layoutLineage([node("a", 0), node("b", 1)], [edge("a", "b")]);
    expect(layout.edges).toHaveLength(1);
    expect(layout.edges[0].path.startsWith(`M ${PADDING + NODE_WIDTH} `)).toBe(true);
  });

  it("skips edges pointing at nodes that were trimmed away", () => {
    const layout = layoutLineage([node("a", 0)], [edge("a", "missing")]);
    expect(layout.edges).toEqual([]);
  });

  it("returns an empty layout rather than NaN dimensions for no nodes", () => {
    expect(layoutLineage([], [])).toEqual({ nodes: [], edges: [], width: 0, height: 0 });
  });

  it("sizes the canvas to fit every node", () => {
    const layout = layoutLineage([node("a", 0), node("b", 0), node("c", 1)], []);
    expect(layout.height).toBe(PADDING * 2 + 2 * NODE_HEIGHT + 20);
    expect(layout.width).toBe(PADDING * 2 + 2 * NODE_WIDTH + COLUMN_GAP);
  });
});

describe("edgePath", () => {
  it("caps the curve so short hops do not loop", () => {
    const short = edgePath({ x: 0, y: 0 }, { x: 10, y: 0 });
    expect(short).toContain("C 24 0");
  });

  it("keeps long hops smooth", () => {
    const long = edgePath({ x: 0, y: 0 }, { x: 1000, y: 40 });
    expect(long).toContain("C 90 0");
  });
});
