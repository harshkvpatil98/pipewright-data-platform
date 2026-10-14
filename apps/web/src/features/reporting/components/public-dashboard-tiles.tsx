import type { CSSProperties } from "react";

import type { PublicDashboardView } from "@platform/shared-types";

import { ChartView } from "@/features/reporting/components/chart-view";

/**
 * A dashboard's tiles as someone without an account sees them, on a shared
 * link or inside another site. Tiles stack on a phone and keep the widths
 * their owner gave them on wider screens.
 */
export function PublicDashboardTiles({ dashboard }: { dashboard: PublicDashboardView }) {
  if (dashboard.tiles.length === 0) {
    return <p className="text-[13px] text-muted">This dashboard has no charts yet.</p>;
  }
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-12">
      {dashboard.tiles.map((tile, index) => (
        <section
          key={`${tile.name}-${index}`}
          className="rounded-2xl border border-line bg-[color:var(--panel)] p-4 md:[grid-column:span_var(--tile-w)]"
          style={{ "--tile-w": Math.min(Math.max(tile.width, 2), 12) } as CSSProperties}
        >
          {tile.kind === "text" ? (
            <>
              {tile.name ? <h2 className="text-[15px] font-semibold text-ink">{tile.name}</h2> : null}
              {tile.body ? <p className="mt-1.5 whitespace-pre-line text-[13px] leading-6 text-ink-2">{tile.body}</p> : null}
            </>
          ) : (
            <>
              <h2 className="text-[13.5px] font-semibold text-ink">{tile.name}</h2>
              {tile.description ? <p className="mt-0.5 text-[12px] leading-4 text-muted">{tile.description}</p> : null}
              <div className="mt-3">{tile.data ? <ChartView data={tile.data} /> : null}</div>
            </>
          )}
        </section>
      ))}
    </div>
  );
}
