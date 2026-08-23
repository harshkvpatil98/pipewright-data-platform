"use client";

import type { RunTimeline } from "@platform/shared-types";

import { cx } from "@/lib/utils";

const STATUS_TONE: Record<string, string> = {
  succeeded: "bg-success",
  failed: "bg-danger",
  skipped: "bg-surface-2",
  running: "bg-info",
  pending: "bg-surface-2",
};

function humanise(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)} min`;
}

/**
 * Where a run's time went.
 *
 * The engine runs nodes one at a time, so this is a waterfall rather than a
 * true Gantt — saying so is better than drawing overlapping bars that imply a
 * parallelism the executor does not have.
 */
export function RunTimelineView({ timeline }: { timeline: RunTimeline }) {
  if (timeline.entries.length === 0) {
    return <p className="text-[11px] text-muted">{timeline.summary}</p>;
  }

  const total = Math.max(timeline.total_ms, 1);

  return (
    <div>
      <div className="mb-1.5 text-[11px] uppercase tracking-[0.16em] text-muted">Timeline</div>
      <ul className="space-y-1.5">
        {timeline.entries.map((entry) => {
          const left = (entry.offset_ms / total) * 100;
          // Below about a percent a bar is invisible; a sliver still shows the
          // step ran at all, which is the thing being looked for.
          const width = Math.max((entry.duration_ms / total) * 100, entry.duration_ms > 0 ? 1.5 : 0);
          return (
            <li key={entry.node_key}>
              <div className="flex items-baseline justify-between gap-2">
                <span
                  className={cx(
                    "truncate text-[11.5px]",
                    entry.node_key === timeline.slowest_node_key ? "text-ink" : "text-ink-3",
                  )}
                  title={entry.node_name}
                >
                  {entry.node_name}
                </span>
                <span className="shrink-0 tabular text-[10px] text-muted">
                  {entry.duration_ms > 0 ? humanise(entry.duration_ms) : entry.status}
                </span>
              </div>
              <div className="mt-0.5 h-1.5 w-full rounded-full bg-surface">
                {width > 0 ? (
                  <div
                    className={cx("h-full rounded-full", STATUS_TONE[entry.status] ?? STATUS_TONE.pending)}
                    style={{ marginLeft: `${left}%`, width: `${width}%` }}
                  />
                ) : (
                  <div
                    className="h-full w-1 rounded-full bg-surface-2"
                    style={{ marginLeft: `${left}%` }}
                  />
                )}
              </div>
            </li>
          );
        })}
      </ul>
      <p className="mt-2 text-[11px] leading-5 text-muted">{timeline.summary}</p>
    </div>
  );
}
