import type { ThroughputPoint } from "@platform/shared-types";

import { countOf, formatNumber, formatTimeUtc } from "@/lib/format";

type ThroughputChartProps = {
  points: ThroughputPoint[];
};

const WIDTH = 600;
const HEIGHT = 72;

/**
 * Events stored per minute over the last hour, as bars (hand-drawn SVG, like
 * every chart here). The busiest minute sets the height; a quiet hour is a
 * flat line and says so.
 */
export function ThroughputChart({ points }: ThroughputChartProps) {
  const total = points.reduce((sum, point) => sum + point.events, 0);
  const peak = points.reduce((most, point) => Math.max(most, point.events), 0);
  const gap = 2;
  const bar = points.length ? WIDTH / points.length - gap : 0;
  const summary = total
    ? `${countOf(total, "event")} in the last hour; the busiest minute had ${formatNumber(peak)}.`
    : "Nothing arrived in the last hour.";

  return (
    <figure className="space-y-2">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-[72px] w-full"
        preserveAspectRatio="none"
        role="img"
        aria-label={summary}
      >
        <line x1={0} y1={HEIGHT - 0.5} x2={WIDTH} y2={HEIGHT - 0.5} stroke="var(--line)" strokeWidth={1} />
        {points.map((point, index) => {
          const height = peak ? Math.max(point.events ? 2 : 0, (point.events / peak) * (HEIGHT - 4)) : 0;
          return (
            <rect
              key={point.minute}
              x={index * (bar + gap)}
              y={HEIGHT - height}
              width={Math.max(bar, 1)}
              height={height}
              rx={1.5}
              fill="var(--accent)"
              opacity={0.85}
            >
              <title>{`${formatTimeUtc(point.minute)}: ${countOf(point.events, "event")}`}</title>
            </rect>
          );
        })}
      </svg>
      <figcaption className="flex flex-wrap justify-between gap-2 text-[13px] text-ink-3">
        <span>{summary}</span>
        {points.length ? (
          <span>
            {formatTimeUtc(points[0].minute)} to {formatTimeUtc(points[points.length - 1].minute)}
          </span>
        ) : null}
      </figcaption>
    </figure>
  );
}
