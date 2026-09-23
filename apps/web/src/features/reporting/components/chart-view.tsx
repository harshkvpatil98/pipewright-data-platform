"use client";

import { useMemo } from "react";

import type { ChartData } from "@platform/shared-types";

import { cx } from "@/lib/utils";

import { formatDeltaPct } from "../dashboard-layout";
import {
  CHART_HEIGHT,
  CHART_WIDTH,
  PADDING,
  bandPositions,
  formatTick,
  linePath,
  niceScale,
  pieSlices,
  slicePath,
  yPosition,
} from "../chart-geometry";

/**
 * Series colours come from theme tokens, so they follow light/dark.
 *
 * The previous palette was literal hex "chosen to stay distinct on a dark
 * ground" -- seven of its eight entries dropped below 2:1 on white, and two
 * were indistinguishable under deuteranopia. The tokens are Okabe-Ito, ordered
 * so a short chart gets the most separated hues, and verified in series.test.ts.
 *
 * Hue alone is trustworthy to 5 series in light and 6 in dark; past that a
 * chart needs a second channel (dash pattern or marker shape).
 */
const PALETTE = Array.from({ length: 8 }, (_, index) => `var(--series-${index + 1})`);

export function ChartView({ data, className }: { data: ChartData; className?: string }) {
  const numeric = useMemo(
    () =>
      data.series.map((series) =>
        series.values.map((value) => (typeof value === "number" ? value : null)),
      ),
    [data.series],
  );

  if (data.row_count === 0) {
    return (
      <div className="flex h-[260px] items-center justify-center rounded-xl border border-line text-[12.5px] text-muted">
        Nothing to show yet.
      </div>
    );
  }

  if (data.chart_type === "kpi") return <KpiView data={data} className={className} />;
  if (data.chart_type === "table") return <TableView data={data} className={className} />;
  if (data.chart_type === "pie") return <PieView data={data} values={numeric[0] ?? []} />;
  if (data.chart_type === "donut") return <PieView data={data} values={numeric[0] ?? []} donut />;

  return <AxisChart data={data} numeric={numeric} className={className} />;
}

function KpiView({ data, className }: { data: ChartData; className?: string }) {
  const value = data.series[0]?.values[0];
  const delta = data.meta?.delta ?? null;
  const pct = delta ? formatDeltaPct(delta.change_pct) : null;
  const direction = delta?.change === null || delta?.change === undefined ? 0 : Math.sign(delta.change);
  return (
    <div
      className={cx(
        "flex h-[260px] flex-col items-center justify-center rounded-xl border border-line bg-surface",
        className,
      )}
    >
      <div className="text-[44px] font-semibold leading-none text-ink">
        {typeof value === "number" ? value.toLocaleString() : (value ?? "—")}
      </div>
      <div className="mt-2 text-[12.5px] capitalize text-muted">
        {data.series[0]?.name.replace(/_/g, " ")}
        {delta ? <span className="normal-case"> · {delta.current_label}</span> : null}
      </div>
      {delta ? (
        <div
          className={cx(
            "mt-3 flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px]",
            direction > 0 && "border-success-line bg-success-soft text-success",
            direction < 0 && "border-danger-line bg-danger-soft text-danger",
            direction === 0 && "border-line bg-sunken text-ink-3",
          )}
          title={`${delta.date_column}, by ${delta.period}: ${delta.previous_label} → ${delta.current_label}`}
        >
          <DeltaArrow direction={direction} />
          {delta.previous === null ? (
            <span>no data for {delta.previous_label}</span>
          ) : (
            <span>
              {pct ?? (delta.change === null ? "—" : `${delta.change > 0 ? "+" : ""}${delta.change.toLocaleString()}`)}
              <span className="text-muted"> vs {delta.previous_label} ({delta.previous.toLocaleString()})</span>
            </span>
          )}
        </div>
      ) : null}
    </div>
  );
}

/** Up, down or flat -- drawn, not a glyph, so it matches the current ink. */
function DeltaArrow({ direction }: { direction: number }) {
  if (direction === 0) {
    return (
      <svg viewBox="0 0 12 12" width={10} height={10} aria-hidden="true">
        <path d="M2 6h8" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" fill="none" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 12 12" width={10} height={10} aria-hidden="true" className={direction < 0 ? "rotate-180" : undefined}>
      <path d="M6 10V2M2.5 5.5 6 2l3.5 3.5" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  );
}

function TableView({ data, className }: { data: ChartData; className?: string }) {
  const rowCount = data.series[0]?.values.length ?? 0;
  return (
    <div className={cx("max-h-[260px] overflow-auto rounded-xl border border-line", className)}>
      <table className="w-full text-left">
        <thead className="sticky top-0 bg-[color:var(--panel-strong)]">
          <tr className="text-[11px] uppercase tracking-[0.14em] text-muted">
            {data.labels.map((label) => (
              <th key={String(label)} className="cell-pad font-medium">
                {String(label).replace(/_/g, " ")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {Array.from({ length: rowCount }, (_unused, row) => (
            <tr key={row}>
              {data.series.map((series) => (
                <td key={series.name} className="cell-pad text-[12.5px] text-ink">
                  {series.values[row] === null ? "—" : String(series.values[row])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PieView({
  data,
  values,
  donut = false,
}: {
  data: ChartData;
  values: (number | null)[];
  donut?: boolean;
}) {
  const slices = pieSlices(values.map((value) => value ?? 0));
  const total = values.reduce<number>((sum, value) => sum + (value ?? 0), 0);

  return (
    <div className="flex items-center gap-6 rounded-xl border border-line bg-surface p-4">
      <svg
        viewBox="0 0 200 200"
        className="h-[200px] w-[200px] shrink-0"
        role="img"
        aria-label={donut ? "Donut chart" : "Pie chart"}
      >
        {slices.map((slice, index) => (
          <path
            key={index}
            d={slicePath(slice.start, slice.end, 100, 100, 88)}
            fill={PALETTE[index % PALETTE.length]}
            stroke="var(--panel-strong)"
            strokeWidth={1.5}
          />
        ))}
        {donut ? (
          <>
            {/* The hole is a panel-coloured disc over the slices: no extra
                geometry, and it follows the theme like everything else. */}
            <circle cx={100} cy={100} r={54} fill="var(--panel-strong)" />
            <text
              x={100}
              y={96}
              textAnchor="middle"
              fontSize={22}
              fontWeight={600}
              fill="var(--ink)"
            >
              {total.toLocaleString()}
            </text>
            <text x={100} y={116} textAnchor="middle" fontSize={10} fill="var(--muted)">
              total
            </text>
          </>
        ) : null}
      </svg>
      <ul className="min-w-0 flex-1 space-y-1.5">
        {slices.map((slice, index) => (
          <li key={index} className="flex items-center gap-2 text-[12.5px]">
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-sm"
              style={{ background: PALETTE[index % PALETTE.length] }}
            />
            <span className="min-w-0 flex-1 truncate text-ink-2">
              {String(data.labels[index] ?? "—")}
            </span>
            <span className="shrink-0 tabular text-muted">
              {(slice.fraction * 100).toFixed(1)}%
            </span>
          </li>
        ))}
        <li className="border-t border-line pt-1.5 text-[11.5px] text-muted">
          Total {total.toLocaleString()}
        </li>
      </ul>
    </div>
  );
}

function AxisChart({
  data,
  numeric,
  className,
}: {
  data: ChartData;
  numeric: (number | null)[][];
  className?: string;
}) {
  const all = numeric.flat().filter((value): value is number => value !== null);
  const scale = niceScale(all);
  const bands = bandPositions(data.labels.length);
  const isBarLike = data.chart_type === "bar" || data.chart_type === "column";
  const zeroLine = yPosition(Math.max(scale.min, 0), scale);

  // With several series in one band, each gets a slice of it.
  const groupWidth = (bands[0]?.width ?? 0) * 0.7;
  const barWidth = groupWidth / Math.max(numeric.length, 1);

  return (
    <div className={cx("rounded-xl border border-line bg-surface p-2", className)}>
      <svg
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        className="w-full"
        role="img"
        aria-label={`${data.chart_type} chart`}
      >
        {scale.ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={PADDING.left}
              x2={CHART_WIDTH - PADDING.right}
              y1={yPosition(tick, scale)}
              y2={yPosition(tick, scale)}
              className="stroke-line"
              strokeWidth={1}
            />
            <text
              x={PADDING.left - 8}
              y={yPosition(tick, scale) + 3.5}
              textAnchor="end"
              className="fill-muted text-[9px]"
            >
              {formatTick(tick)}
            </text>
          </g>
        ))}

        {numeric.map((values, seriesIndex) => {
          const colour = PALETTE[seriesIndex % PALETTE.length];

          if (isBarLike) {
            return values.map((value, index) => {
              if (value === null || !bands[index]) return null;
              const top = yPosition(value, scale);
              const left =
                bands[index].centre - groupWidth / 2 + barWidth * seriesIndex;
              return (
                <rect
                  key={`${seriesIndex}-${index}`}
                  x={left}
                  y={Math.min(top, zeroLine)}
                  width={Math.max(barWidth - 2, 1)}
                  height={Math.max(Math.abs(zeroLine - top), 1)}
                  rx={2}
                  fill={colour}
                  opacity={0.85}
                />
              );
            });
          }

          if (data.chart_type === "scatter") {
            return values.map((value, index) =>
              value === null || !bands[index] ? null : (
                <circle
                  key={`${seriesIndex}-${index}`}
                  cx={bands[index].centre}
                  cy={yPosition(value, scale)}
                  r={3.5}
                  fill={colour}
                  opacity={0.85}
                />
              ),
            );
          }

          const path = linePath(values, scale);
          return (
            <g key={seriesIndex}>
              {data.chart_type === "area" && path ? (
                <path
                  d={`${path} L ${CHART_WIDTH - PADDING.right} ${zeroLine} L ${PADDING.left} ${zeroLine} Z`}
                  fill={colour}
                  opacity={0.12}
                />
              ) : null}
              <path d={path} fill="none" stroke={colour} strokeWidth={2} />
            </g>
          );
        })}

        {data.labels.map((label, index) =>
          bands[index] && (data.labels.length <= 14 || index % Math.ceil(data.labels.length / 12) === 0) ? (
            <text
              key={index}
              x={bands[index].centre}
              y={CHART_HEIGHT - PADDING.bottom + 16}
              textAnchor="middle"
              className="fill-muted text-[9.5px]"
            >
              {truncate(String(label ?? ""))}
            </text>
          ) : null,
        )}
      </svg>

      {data.series.length > 1 ? (
        <ul className="mt-1 flex flex-wrap gap-3 px-2 pb-1">
          {data.series.map((series, index) => (
            <li key={series.name} className="flex items-center gap-1.5 text-[11px] text-ink-3">
              <span
                className="h-2 w-2 rounded-sm"
                style={{ background: PALETTE[index % PALETTE.length] }}
              />
              {series.name.replace(/_/g, " ")}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function truncate(label: string): string {
  return label.length > 12 ? `${label.slice(0, 11)}…` : label;
}
