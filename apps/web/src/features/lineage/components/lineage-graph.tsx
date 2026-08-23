"use client";

import type { DatasetLineage } from "@platform/shared-types";

import { Icon } from "@/components/ui/icon";
import { cx } from "@/lib/utils";

import { NODE_HEIGHT, NODE_WIDTH, layoutLineage } from "../lineage-layout";

const EDGE_TONE: Record<string, string> = {
  produces: "stroke-[color:var(--accent)]",
  consumes: "stroke-muted",
  joins: "stroke-accent",
  unions: "stroke-accent",
  derives: "stroke-muted",
};

const EDGE_DASH: Record<string, string> = {
  joins: "5 4",
  unions: "5 4",
};

export function LineageGraph({ lineage }: { lineage: DatasetLineage }) {
  const layout = layoutLineage(lineage.nodes, lineage.edges);

  if (layout.nodes.length === 0) {
    return (
      <div className="rounded-xl border border-line px-4 py-8 text-center text-[12.5px] text-muted">
        Nothing is connected to this dataset yet.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <svg
        width={layout.width}
        height={layout.height}
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        role="img"
        aria-label="Dataset lineage"
        className="min-w-full"
      >
        <defs>
          <marker
            id="lineage-arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" className="fill-muted" />
          </marker>
        </defs>

        {layout.edges.map((edge) => (
          <path
            key={edge.key}
            d={edge.path}
            fill="none"
            strokeWidth={1.5}
            strokeDasharray={EDGE_DASH[edge.kind]}
            markerEnd="url(#lineage-arrow)"
            className={cx(EDGE_TONE[edge.kind] ?? "stroke-muted", "opacity-70")}
          />
        ))}

        {layout.nodes.map((node) => (
          <g key={node.id} transform={`translate(${node.x}, ${node.y})`}>
            <rect
              width={NODE_WIDTH}
              height={NODE_HEIGHT}
              rx={10}
              className={cx(
                "stroke-[1.5]",
                node.is_focus
                  ? "fill-[color:var(--accent-soft)] stroke-[color:var(--accent)]"
                  : node.kind === "pipeline"
                    ? "fill-surface-2 stroke-line"
                    : "fill-surface-2 stroke-line",
              )}
            />
            <foreignObject x={0} y={0} width={NODE_WIDTH} height={NODE_HEIGHT}>
              <div className="flex h-full flex-col justify-center gap-0.5 px-3">
                <div className="flex items-center gap-1.5">
                  <span className={node.is_focus ? "text-ink" : "text-ink-3"}>
                    <Icon name={node.kind === "pipeline" ? "transform" : "table"} size={11} />
                  </span>
                  <span
                    className={cx(
                      "truncate text-[12px] font-medium",
                      node.is_focus ? "text-ink" : "text-ink",
                    )}
                    title={node.name}
                  >
                    {node.name}
                  </span>
                </div>
                {node.subtitle ? (
                  <div className="truncate pl-[18px] text-[10.5px] text-muted">
                    {node.subtitle}
                  </div>
                ) : null}
              </div>
            </foreignObject>
          </g>
        ))}
      </svg>
    </div>
  );
}
