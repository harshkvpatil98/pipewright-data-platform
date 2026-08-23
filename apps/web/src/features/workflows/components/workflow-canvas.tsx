"use client";

import { useCallback, useMemo, useRef, useState } from "react";

import type {
  EdgeCondition,
  WorkflowEdgeInput,
  WorkflowNodeInput,
  WorkflowNodeRunRecord,
  WorkflowNodeType,
} from "@platform/shared-types";

import { Icon, type IconName } from "@/components/ui/icon";
import {
  NODE_HEIGHT,
  NODE_WIDTH,
  canvasExtent,
  edgeMidpoint,
  edgePath,
  inputPort,
  outputPort,
  snap,
} from "@/features/workflows/canvas-geometry";
import { cx } from "@/lib/utils";

export const NODE_META: Record<
  WorkflowNodeType,
  { label: string; icon: IconName; accent: string }
> = {
  extraction: { label: "Extract", icon: "database", accent: "var(--flow-extract)" },
  transformation: { label: "Transform", icon: "transform", accent: "var(--flow-transform)" },
  quality_gate: { label: "Quality gate", icon: "shield", accent: "var(--flow-quality)" },
  drift_gate: { label: "Drift gate", icon: "drift", accent: "var(--flow-quality)" },
  publish: { label: "Publish", icon: "send", accent: "var(--flow-publish)" },
  reverse_etl: { label: "Send back", icon: "download", accent: "var(--flow-publish)" },
  notify: { label: "Notify", icon: "bell", accent: "var(--flow-notify)" },
};

const CONDITION_STYLE: Record<EdgeCondition, { stroke: string; label: string; dash?: string }> = {
  on_success: { stroke: "var(--edge-success)", label: "on success" },
  on_failure: { stroke: "var(--edge-failure)", label: "on failure", dash: "5 4" },
  always: { stroke: "var(--edge-always)", label: "always", dash: "2 4" },
};

const RUN_STATUS_RING: Record<string, string> = {
  running: "ring-2 ring-[color:var(--accent)]",
  succeeded: "ring-1 ring-success",
  failed: "ring-2 ring-danger",
  skipped: "ring-1 ring-line",
};

type Connecting = { fromKey: string; x: number; y: number } | null;

type WorkflowCanvasProps = {
  nodes: WorkflowNodeInput[];
  edges: WorkflowEdgeInput[];
  selectedKey: string | null;
  /** Per-node status from the run being watched, if any. */
  nodeRuns?: Record<string, WorkflowNodeRunRecord>;
  readOnly?: boolean;
  onSelect: (key: string | null) => void;
  onMoveNode: (key: string, x: number, y: number) => void;
  onConnect: (fromKey: string, toKey: string) => void;
  onDeleteEdge: (from: string, to: string) => void;
};

export function WorkflowCanvas({
  nodes,
  edges,
  selectedKey,
  nodeRuns,
  readOnly = false,
  onSelect,
  onMoveNode,
  onConnect,
  onDeleteEdge,
}: WorkflowCanvasProps) {
  const surfaceRef = useRef<HTMLDivElement>(null);
  const [connecting, setConnecting] = useState<Connecting>(null);
  const [hoverEdge, setHoverEdge] = useState<string | null>(null);

  const byKey = useMemo(
    () => Object.fromEntries(nodes.map((node) => [node.node_key, node])),
    [nodes],
  );
  const extent = useMemo(() => canvasExtent(nodes), [nodes]);

  /** Pointer position in canvas coordinates, accounting for scroll. */
  const toCanvasPoint = useCallback((event: { clientX: number; clientY: number }) => {
    const surface = surfaceRef.current;
    if (!surface) return { x: 0, y: 0 };
    const box = surface.getBoundingClientRect();
    return {
      x: event.clientX - box.left + surface.scrollLeft,
      y: event.clientY - box.top + surface.scrollTop,
    };
  }, []);

  // Dragging a node.
  //
  // Movement is tracked on `window` rather than the card, so a fast drag that
  // outruns the cursor still lands. Pointer capture is attempted as a bonus but
  // is not relied on: it throws if the pointer id is no longer active, and
  // letting that propagate would abort the drag entirely.
  const startDrag = (event: React.PointerEvent, node: WorkflowNodeInput) => {
    if (readOnly) return;
    event.stopPropagation();
    onSelect(node.node_key);

    const start = toCanvasPoint(event);
    const offsetX = start.x - node.position_x;
    const offsetY = start.y - node.position_y;
    const target = event.currentTarget as HTMLElement;

    try {
      target.setPointerCapture(event.pointerId);
    } catch {
      /* capture is an optimisation; window listeners below do the real work */
    }

    const move = (moveEvent: PointerEvent) => {
      const point = toCanvasPoint(moveEvent);
      onMoveNode(
        node.node_key,
        Math.max(0, snap(point.x - offsetX)),
        Math.max(0, snap(point.y - offsetY)),
      );
    };

    const finish = () => {
      try {
        target.releasePointerCapture(event.pointerId);
      } catch {
        /* nothing to release */
      }
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", finish);
    };

    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish);
    window.addEventListener("pointercancel", finish);
  };

  // Dragging from an output port to another node creates a dependency.
  const startConnect = (event: React.PointerEvent, node: WorkflowNodeInput) => {
    if (readOnly) return;
    event.stopPropagation();
    event.preventDefault();
    const point = toCanvasPoint(event);
    setConnecting({ fromKey: node.node_key, x: point.x, y: point.y });

    const move = (moveEvent: PointerEvent) => {
      const next = toCanvasPoint(moveEvent);
      setConnecting((current) => (current ? { ...current, x: next.x, y: next.y } : current));
    };

    const finish = (upEvent: PointerEvent) => {
      const dropped = document
        .elementsFromPoint(upEvent.clientX, upEvent.clientY)
        .map((element) => (element as HTMLElement).dataset?.nodeKey)
        .find(Boolean);

      if (dropped && dropped !== node.node_key) {
        onConnect(node.node_key, dropped);
      }
      setConnecting(null);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
    };

    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish);
  };

  return (
    <div
      ref={surfaceRef}
      onPointerDown={() => onSelect(null)}
      className="relative h-full w-full overflow-auto bg-[color:var(--surface-sunken)]"
      style={{
        // A dot grid gives the canvas depth and makes snapping legible.
        backgroundImage:
          "radial-gradient(circle, rgba(148,163,184,0.16) 1px, transparent 1px)",
        backgroundSize: "20px 20px",
      }}
    >
      <div className="relative" style={{ width: extent.width, height: extent.height }}>
        <svg
          className="pointer-events-none absolute inset-0"
          width={extent.width}
          height={extent.height}
          aria-hidden="true"
        >
          <defs>
            {Object.entries(CONDITION_STYLE).map(([condition, style]) => (
              <marker
                key={condition}
                id={`arrow-${condition}`}
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" fill={style.stroke} />
              </marker>
            ))}
          </defs>

          {edges.map((edge) => {
            const source = byKey[edge.from_node_key];
            const target = byKey[edge.to_node_key];
            if (!source || !target) return null;

            const from = outputPort(source);
            const to = inputPort(target);
            const style = CONDITION_STYLE[edge.condition];
            const id = `${edge.from_node_key}->${edge.to_node_key}`;
            const mid = edgeMidpoint(from, to);
            const active = hoverEdge === id;

            return (
              <g key={id}>
                <path
                  d={edgePath(from, to)}
                  fill="none"
                  stroke={style.stroke}
                  strokeWidth={active ? 2.5 : 1.75}
                  strokeDasharray={style.dash}
                  markerEnd={`url(#arrow-${edge.condition})`}
                  opacity={active ? 1 : 0.85}
                />
                {/* A fat invisible path makes the thin curve easy to hit. */}
                <path
                  d={edgePath(from, to)}
                  fill="none"
                  stroke="transparent"
                  strokeWidth={16}
                  className={readOnly ? "" : "pointer-events-auto cursor-pointer"}
                  onPointerEnter={() => setHoverEdge(id)}
                  onPointerLeave={() => setHoverEdge(null)}
                  onPointerDown={(event) => {
                    if (readOnly) return;
                    event.stopPropagation();
                    onDeleteEdge(edge.from_node_key, edge.to_node_key);
                  }}
                />
                {edge.condition !== "on_success" || active ? (
                  <text
                    x={mid.x}
                    y={mid.y - 8}
                    textAnchor="middle"
                    className="select-none"
                    style={{ fontSize: 10, fill: style.stroke }}
                  >
                    {active ? "click to remove" : style.label}
                  </text>
                ) : null}
              </g>
            );
          })}

          {connecting ? (
            <path
              d={edgePath(outputPort(byKey[connecting.fromKey]), {
                x: connecting.x,
                y: connecting.y,
              })}
              fill="none"
              stroke="var(--accent)"
              strokeWidth={2}
              strokeDasharray="4 4"
            />
          ) : null}
        </svg>

        {nodes.map((node) => {
          const meta = NODE_META[node.node_type];
          const run = nodeRuns?.[node.node_key];
          const selected = node.node_key === selectedKey;

          return (
            <div
              key={node.node_key}
              data-node-key={node.node_key}
              onPointerDown={(event) => startDrag(event, node)}
              className={cx(
                "absolute select-none rounded-xl border bg-[color:var(--panel-strong)] shadow-[var(--shadow-md)] transition-shadow",
                readOnly ? "cursor-default" : "cursor-grab active:cursor-grabbing",
                selected
                  ? "border-[color:var(--accent)] shadow-[var(--shadow-glow)]"
                  : "border-line hover:border-line-strong",
                run ? RUN_STATUS_RING[run.status] : "",
              )}
              style={{
                left: node.position_x,
                top: node.position_y,
                width: NODE_WIDTH,
                height: NODE_HEIGHT,
              }}
            >
              <div className="flex h-full items-center gap-2.5 px-3">
                <span
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
                  style={{ background: `color-mix(in srgb, ${meta.accent} 18%, transparent)` }}
                >
                  <Icon name={meta.icon} size={16} />
                </span>
                <span className="min-w-0 flex-1" data-node-key={node.node_key}>
                  <span
                    className="block truncate text-[12.5px] font-medium text-ink"
                    data-node-key={node.node_key}
                  >
                    {node.name}
                  </span>
                  <span
                    className="block truncate text-[10px] uppercase tracking-[0.14em] text-muted"
                    data-node-key={node.node_key}
                  >
                    {meta.label}
                  </span>
                </span>
                {run ? <NodeRunBadge status={run.status} /> : null}
              </div>

              {/* Output port: drag from here to another node to add a dependency. */}
              {readOnly ? null : (
                <button
                  type="button"
                  aria-label={`Connect from ${node.name}`}
                  onPointerDown={(event) => startConnect(event, node)}
                  className="absolute -right-2 top-1/2 flex h-4 w-4 -translate-y-1/2 items-center justify-center rounded-full border border-line-strong bg-[color:var(--panel-strong)] text-ink-3 transition hover:border-[color:var(--accent)] hover:bg-[color:var(--accent)] hover:text-accent-ink"
                >
                  <Icon name="plus" size={9} />
                </button>
              )}
            </div>
          );
        })}

        {nodes.length === 0 ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <Icon name="transform" size={26} className="mx-auto text-muted" />
              <p className="mt-3 text-[13px] text-ink-3">This workflow has no steps yet.</p>
              <p className="mt-1 text-[12px] text-muted">
                Add one from the ribbon above to begin.
              </p>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function NodeRunBadge({ status }: { status: string }) {
  const tone =
    status === "succeeded"
      ? "text-success"
      : status === "failed"
        ? "text-danger"
        : status === "running"
          ? "text-[color:var(--accent-muted)]"
          : "text-muted";

  const icon: IconName =
    status === "succeeded"
      ? "check"
      : status === "failed"
        ? "warning"
        : status === "running"
          ? "refresh"
          : "close";

  return (
    <span className={cx("shrink-0", tone, status === "running" && "animate-live")}>
      <Icon name={icon} size={14} />
    </span>
  );
}
