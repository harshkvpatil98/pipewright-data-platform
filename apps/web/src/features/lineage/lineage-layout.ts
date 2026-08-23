/**
 * Laying out a lineage graph.
 *
 * Lineage has something a free-form canvas does not: a direction. Every node
 * already knows how far upstream or downstream of the focus it sits, so the
 * layout does not need a force simulation or a layering pass -- depth is the
 * column, and the only real decision is the vertical order inside each one.
 *
 * Kept separate from the component, and pure, so the arithmetic is testable
 * without rendering anything.
 */

import type { LineageEdge, LineageNode } from "@platform/shared-types";

export const NODE_WIDTH = 172;
export const NODE_HEIGHT = 56;
export const COLUMN_GAP = 96;
export const ROW_GAP = 20;
export const PADDING = 24;

export type PositionedNode = LineageNode & {
  x: number;
  y: number;
};

export type PositionedEdge = {
  key: string;
  path: string;
  kind: LineageEdge["kind"];
  label: string | null;
};

export type LineageLayout = {
  nodes: PositionedNode[];
  edges: PositionedEdge[];
  width: number;
  height: number;
};

/** A horizontal S-curve between two points, flattening over short spans. */
export function edgePath(
  from: { x: number; y: number },
  to: { x: number; y: number },
): string {
  const distance = Math.abs(to.x - from.x);
  const curve = Math.max(24, Math.min(distance * 0.5, 90));
  return `M ${from.x} ${from.y} C ${from.x + curve} ${from.y}, ${to.x - curve} ${to.y}, ${to.x} ${to.y}`;
}

function columnOrder(nodes: LineageNode[]): number[] {
  return Array.from(new Set(nodes.map((node) => node.depth))).sort((a, b) => a - b);
}

export function layoutLineage(nodes: LineageNode[], edges: LineageEdge[]): LineageLayout {
  if (nodes.length === 0) {
    return { nodes: [], edges: [], width: 0, height: 0 };
  }

  const depths = columnOrder(nodes);
  const byDepth = new Map<number, LineageNode[]>();
  for (const node of nodes) {
    const bucket = byDepth.get(node.depth) ?? [];
    bucket.push(node);
    byDepth.set(node.depth, bucket);
  }

  // The tallest column sets the height; every other column is centred against
  // it so the focus node sits on the same line as its neighbours.
  const tallest = Math.max(...[...byDepth.values()].map((bucket) => bucket.length));
  const height = PADDING * 2 + tallest * NODE_HEIGHT + (tallest - 1) * ROW_GAP;
  const width = PADDING * 2 + depths.length * NODE_WIDTH + (depths.length - 1) * COLUMN_GAP;

  const positioned: PositionedNode[] = [];
  depths.forEach((depth, columnIndex) => {
    const bucket = (byDepth.get(depth) ?? []).slice().sort((a, b) => {
      // Datasets above pipelines, then alphabetical: a stable order beats a
      // prettier one that moves every time the page loads.
      if (a.kind !== b.kind) return a.kind === "dataset" ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    const columnHeight = bucket.length * NODE_HEIGHT + (bucket.length - 1) * ROW_GAP;
    const top = PADDING + (height - PADDING * 2 - columnHeight) / 2;

    bucket.forEach((node, rowIndex) => {
      positioned.push({
        ...node,
        x: PADDING + columnIndex * (NODE_WIDTH + COLUMN_GAP),
        y: top + rowIndex * (NODE_HEIGHT + ROW_GAP),
      });
    });
  });

  const byId = new Map(positioned.map((node) => [node.id, node]));
  const drawn: PositionedEdge[] = [];
  for (const edge of edges) {
    const from = byId.get(edge.from_id);
    const to = byId.get(edge.to_id);
    if (!from || !to) continue;
    drawn.push({
      key: `${edge.from_id}->${edge.to_id}:${edge.kind}`,
      path: edgePath(
        { x: from.x + NODE_WIDTH, y: from.y + NODE_HEIGHT / 2 },
        { x: to.x, y: to.y + NODE_HEIGHT / 2 },
      ),
      kind: edge.kind,
      label: edge.label,
    });
  }

  return { nodes: positioned, edges: drawn, width, height };
}
