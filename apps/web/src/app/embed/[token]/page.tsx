import type { Metadata } from "next";

import type { PublicDashboardView } from "@platform/shared-types";

import { PublicDashboardTiles } from "@/features/reporting/components/public-dashboard-tiles";
import { RefreshEvery } from "@/features/reporting/components/refresh-every";
import { ApiError, extractErrorMessage } from "@/lib/api/errors";
import { publicApiFetch } from "@/lib/api/public";

// The link is the access control; an indexed link is a leaked one.
export const metadata: Metadata = {
  title: "Dashboard",
  robots: { index: false, follow: false },
};

type PageProps = {
  params: Promise<{ token: string }>;
  searchParams: Promise<{ title?: string }>;
};

type Loaded = { dashboard: PublicDashboardView } | { problem: { title: string; detail: string } };

async function load(token: string): Promise<Loaded> {
  try {
    return { dashboard: await publicApiFetch<PublicDashboardView>(`/public/embeds/${encodeURIComponent(token)}`) };
  } catch (error) {
    if (error instanceof ApiError && error.status === 410) {
      return {
        problem: {
          title: "This link has run out",
          detail: "Reload the page it was on for a new one. If it keeps happening, tell whoever runs that site.",
        },
      };
    }
    if (error instanceof ApiError && error.status === 404) {
      return {
        problem: {
          title: "This dashboard isn’t available",
          detail: "Its owner may have turned it off, or the link was never valid.",
        },
      };
    }
    if (error instanceof ApiError && error.status === 400) {
      return { problem: { title: "This link could not be read", detail: extractErrorMessage(error) } };
    }
    throw error;
  }
}

/**
 * A dashboard inside another site (A8, Y4): no navigation, no sign-in, and
 * nothing around it, so it sits in the frame as part of that site. Only the
 * sites in `EMBED_ALLOWED_ORIGINS` may frame it (the proxy sends them). Add
 * `?title=0` to leave the name off, and `?theme=light` or `dark` to match.
 */
export default async function EmbeddedDashboardPage({ params, searchParams }: PageProps) {
  const [{ token }, { title }] = await Promise.all([params, searchParams]);
  const loaded = await load(token);

  if ("problem" in loaded) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-2 px-4 text-center">
        <h1 className="text-[15px] font-semibold text-ink">{loaded.problem.title}</h1>
        <p className="max-w-sm text-[13px] leading-6 text-muted">{loaded.problem.detail}</p>
      </main>
    );
  }

  const { dashboard } = loaded;
  return (
    <main className="min-h-screen p-4">
      <RefreshEvery seconds={dashboard.refresh_seconds} />
      {title === "0" ? null : <h1 className="mb-3 text-[15px] font-semibold text-ink">{dashboard.name}</h1>}
      <PublicDashboardTiles dashboard={dashboard} />
    </main>
  );
}
