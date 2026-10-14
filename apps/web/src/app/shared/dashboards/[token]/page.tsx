import type { Metadata } from "next";

import type { PublicDashboardView } from "@platform/shared-types";

import { PublicDashboardTiles } from "@/features/reporting/components/public-dashboard-tiles";
import { RefreshEvery } from "@/features/reporting/components/refresh-every";
import { ApiError } from "@/lib/api/errors";
import { publicApiFetch } from "@/lib/api/public";
import { appConfig } from "@/lib/config";

// A shared dashboard is public by link, but it is not for search engines: the
// link is the access control, and an indexed link is a leaked one.
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

type PageProps = { params: Promise<{ token: string }> };

async function loadDashboard(token: string): Promise<PublicDashboardView | null> {
  try {
    return await publicApiFetch<PublicDashboardView>(`/public/dashboards/${encodeURIComponent(token)}`);
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
      <RefreshEvery seconds={dashboard.refresh_seconds} />
      <header className="mb-8 border-b border-line pb-6">
        <div className="flex items-center gap-2 text-[12px] font-medium text-muted">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-[color:var(--accent)]" />
          Shared dashboard
        </div>
        <h1 className="mt-2 text-2xl font-semibold text-ink">{dashboard.name}</h1>
        {dashboard.description ? (
          <p className="mt-2 max-w-2xl text-[13.5px] leading-6 text-ink-2">{dashboard.description}</p>
        ) : null}
      </header>

      <PublicDashboardTiles dashboard={dashboard} />

      <footer className="mt-10 border-t border-line pt-4 text-[12px] text-muted">
        Read-only view · Shared via {appConfig.appName}
      </footer>
    </main>
  );
}
