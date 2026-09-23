import type { CSSProperties } from "react";

import type { Metadata } from "next";

import type { PublicDashboardView } from "@platform/shared-types";

import { ChartView } from "@/features/reporting/components/chart-view";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { appConfig } from "@/lib/config";

// A shared dashboard is public by link, but it is not for search engines: the
// link is the access control, and an indexed link is a leaked one.
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

type PageProps = { params: Promise<{ token: string }> };

async function loadDashboard(token: string): Promise<PublicDashboardView | null> {
  try {
    return await serverApiFetch<PublicDashboardView>(
      `/public/dashboards/${encodeURIComponent(token)}`,
    );
  } catch (error) {
    // A revoked or unknown token is the expected "not available" case, not a
    // crash. Anything else is a real error and should surface.
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export default async function SharedDashboardPage({ params }: PageProps) {
  const { token } = await params;
  const dashboard = await loadDashboard(token);

  if (dashboard === null) {
    return (
      <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-3 px-6 text-center">
        <h1 className="text-lg font-semibold text-ink">This dashboard isn’t available</h1>
        <p className="text-[13px] leading-6 text-muted">
          The link may have been turned off by its owner, or it was never valid. Ask whoever shared
          it for a new link.
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto min-h-screen max-w-6xl px-6 py-10">
      <header className="mb-8 border-b border-line pb-6">
        <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.18em] text-muted">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-[color:var(--accent)]" />
          Shared dashboard
        </div>
        <h1 className="mt-2 text-2xl font-semibold text-ink">{dashboard.name}</h1>
        {dashboard.description ? (
          <p className="mt-2 max-w-2xl text-[13.5px] leading-6 text-ink-2">{dashboard.description}</p>
        ) : null}
      </header>

      {dashboard.tiles.length === 0 ? (
        <p className="text-[13px] text-muted">This dashboard has no charts yet.</p>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-12">
          {dashboard.tiles.map((tile, index) => (
            <section
              key={`${tile.name}-${index}`}
              // Stacks full-width on mobile (grid-cols-1); spans its stored
              // width on desktop via a CSS variable so the layout matches the
              // dashboard as its owner arranged it.
              className="rounded-2xl border border-line bg-[color:var(--panel)] p-4 md:[grid-column:span_var(--tile-w)]"
              style={{ "--tile-w": Math.min(Math.max(tile.width, 2), 12) } as CSSProperties}
            >
              {tile.kind === "text" ? (
                <>
                  {tile.name ? <h2 className="text-[15px] font-semibold text-ink">{tile.name}</h2> : null}
                  {tile.body ? (
                    <p className="mt-1.5 whitespace-pre-line text-[13px] leading-6 text-ink-2">{tile.body}</p>
                  ) : null}
                </>
              ) : (
                <>
                  <h2 className="text-[13.5px] font-semibold text-ink">{tile.name}</h2>
                  {tile.description ? (
                    <p className="mt-0.5 text-[11.5px] leading-4 text-muted">{tile.description}</p>
                  ) : null}
                  <div className="mt-3">{tile.data ? <ChartView data={tile.data} /> : null}</div>
                </>
              )}
            </section>
          ))}
        </div>
      )}

      <footer className="mt-10 border-t border-line pt-4 text-[11px] text-muted">
        Read-only view · Shared via {appConfig.appName}
      </footer>
    </main>
  );
}
