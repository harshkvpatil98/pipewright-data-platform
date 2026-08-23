/**
 * Canvas maths, kept free of React so it can be tested directly.
 *
 * The canvas draws nodes as fixed-size cards and edges as cubic curves between
 * their ports. Everything here is pure geometry over those coordinates.
 */

export const NODE_WIDTH = 190;
export const NODE_HEIGHT = 68;

/** Horizontal gap between dependency levels, and vertical gap within a level. */
const LEVEL_GAP = 260;
const ROW_GAP = 110;
const MARGIN = 40;

export type Point = { x: number; y: number };

export type PositionedNode = {
  node_key: string;
  position_x: number;
  position_y: number;
};

/** Where an edge leaves a node: the right edge, vertically centred. */
export function outputPort(node: PositionedNode): Point {
  return { x: node.position_x + NODE_WIDTH, y: node.position_y + NODE_HEIGHT / 2 };
}

/** Where an edge arrives: the left edge, vertically centred. */
export function inputPort(node: PositionedNode): Point {
  return { x: node.position_x, y: node.position_y + NODE_HEIGHT / 2 };
}

/**
 * A horizontal cubic Bézier between two ports.
 *
 * Control points are pushed out horizontally so edges leave and enter flat,
 * which keeps parallel branches readable instead of crossing at sharp angles.
 * The offset grows with distance but is capped so long edges do not bow absurdly.
 */
export function edgePath(from: Point, to: Point): string {
  const distance = Math.abs(to.x - from.x);
  const curve = Math.max(40, Math.min(distance * 0.5, 140));
  return `M ${from.x} ${from.y} C ${from.x + curve} ${from.y}, ${to.x - curve} ${to.y}, ${to.x} ${to.y}`;
}

/** Midpoint of that curve, used to place the condition label. */
export function edgeMidpoint(from: Point, to: Point): Point {
  return { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 };
}

/**
 * Arrange nodes into columns by dependency level.
 *
 * `levels` comes from the server's topological ordering, so the layout reflects
 * real execution order rather than a guess. Nodes the server did not place
 * (an invalid graph has no ordering) are laid out in a trailing column so they
 * remain reachable.
 */
export function tidyLayout(
  levels: string[][],
  allKeys: string[],
): Record<string, Point> {
  const placed: Record<string, Point> = {};
  const seen = new Set<string>();

  levels.forEach((level, columnIndex) => {
    // Centre each column vertically against the tallest column.
    const columnHeight = level.length * NODE_HEIGHT + (level.length - 1) * (ROW_GAP - NODE_HEIGHT);
    const startY = MARGIN + Math.max(0, (tallestColumn(levels) - columnHeight) / 2);

    level.forEach((key, rowIndex) => {
      placed[key] = {
        x: MARGIN + columnIndex * LEVEL_GAP,
        y: startY + rowIndex * ROW_GAP,
      };
      seen.add(key);
    });
  });

  const orphans = allKeys.filter((key) => !seen.has(key));
  orphans.forEach((key, index) => {
    placed[key] = {
      x: MARGIN + levels.length * LEVEL_GAP,
      y: MARGIN + index * ROW_GAP,
    };
  });

  return placed;
}

function tallestColumn(levels: string[][]): number {
  return levels.reduce((tallest, level) => {
    const height = level.length * NODE_HEIGHT + (level.length - 1) * (ROW_GAP - NODE_HEIGHT);
    return Math.max(tallest, height);
  }, 0);
}

/** Canvas extent needed to show every node, with room to drag past the edge. */
export function canvasExtent(nodes: PositionedNode[]): { width: number; height: number } {
  const right = nodes.reduce((max, node) => Math.max(max, node.position_x + NODE_WIDTH), 0);
  const bottom = nodes.reduce((max, node) => Math.max(max, node.position_y + NODE_HEIGHT), 0);
  return { width: right + 320, height: bottom + 240 };
}

/** Snap to a grid so hand-placed nodes still line up. */
export function snap(value: number, grid = 10): number {
  return Math.round(value / grid) * grid;
}

/**
 * A node key derived from a label: lowercase, underscores, letter-initial.
 * Must satisfy the same rule the backend enforces.
 */
export function toNodeKey(label: string, taken: string[] = []): string {
  const base =
    label
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .replace(/^([^a-z])/, "n$1")
      .slice(0, 48) || "node";

  if (!taken.includes(base)) return base;

  let suffix = 2;
  while (taken.includes(`${base}_${suffix}`)) suffix += 1;
  return `${base}_${suffix}`;
}
