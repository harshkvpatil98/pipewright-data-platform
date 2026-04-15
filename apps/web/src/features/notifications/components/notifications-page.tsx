"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import type { AuthUser, UserNotificationListResponse, UserNotificationRecord } from "@platform/shared-types";
import { Button, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { OperationalEmpty, OperationalError, OperationalLoading } from "@/components/operational/operational-messages";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { formatNotificationEventLabel } from "@/lib/run-labels";

type NotificationsPageProps = {
  currentUser: AuthUser;
};

function levelBadgeClass(level: string): string {
  switch (level) {
    case "error":
      return "border-rose-400/30 bg-rose-500/10 text-rose-100";
    case "warning":
      return "border-amber-400/25 bg-amber-500/10 text-amber-100";
    case "success":
      return "border-emerald-400/25 bg-emerald-500/10 text-emerald-100";
    default:
      return "border-slate-500/25 bg-slate-500/10 text-slate-200";
  }
}

function relatedHref(n: UserNotificationRecord): string | null {
  if (n.related_run_id && n.project_id) {
    return `/projects/${n.project_id}/runs/${n.related_run_id}/audit`;
  }
  if (n.related_schedule_id && n.project_id) {
    return `/projects/${n.project_id}/schedules`;
  }
  if (n.related_dataset_id && n.project_id) {
    return `/projects/${n.project_id}/datasets/${n.related_dataset_id}`;
  }
  if (n.related_pipeline_id && n.project_id) {
    return `/projects/${n.project_id}/pipelines/${n.related_pipeline_id}`;
  }
  return null;
}

export function NotificationsPage({ currentUser }: NotificationsPageProps) {
  const [data, setData] = useState<UserNotificationListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [markingAll, setMarkingAll] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await apiFetch<UserNotificationListResponse>("/notifications?limit=100");
      setData(res);
    } catch (e) {
      setError(extractErrorMessage(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const onMarkRead = async (id: string) => {
    setBusyId(id);
    try {
      await apiFetch(`/notifications/${id}/read`, { method: "PATCH" });
      await load();
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setBusyId(null);
    }
  };

  const onMarkAll = async () => {
    setMarkingAll(true);
    try {
      await apiFetch("/notifications/read-all", { method: "PATCH" });
      await load();
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setMarkingAll(false);
    }
  };

  return (
    <AppShell
      title="Notifications"
      subtitle="In-app alerts for scheduled runs, publishes, and transformations. External delivery is optional; this page is the cleanest place to review recent outcomes."
      currentUser={currentUser}
      actions={
        <Button type="button" variant="secondary" size="sm" onClick={() => void onMarkAll()} disabled={markingAll}>
          {markingAll ? "Updating…" : "Mark all read"}
        </Button>
      }
    >
      {error ? (
        <div className="rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">{error}</div>
      ) : null}

      <SectionPanel
        title="Recent activity"
        description={data ? `${data.unread_count} unread` : "Fetching your latest alerts."}
      >
        {data ? (
          <div className="mb-5 grid gap-3 md:grid-cols-3">
            <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-4 text-sm text-slate-300">
              <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Unread</div>
              <div className="mt-2 text-2xl font-semibold text-white">{data.unread_count}</div>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-4 text-sm text-slate-300">
              <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Visible in feed</div>
              <div className="mt-2 text-2xl font-semibold text-white">{data.items.length}</div>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-4 text-sm leading-6 text-slate-400">
              Notifications link back to related runs, schedules, datasets, or pipelines when context is available.
            </div>
          </div>
        ) : null}
        {!data ? (
          <OperationalLoading message="Loading notifications…" />
        ) : data.items.length === 0 ? (
          <OperationalEmpty description="No notifications yet. Scheduled runs, publishes, and transformations will appear here when they complete." />
        ) : (
          <ul className="space-y-2">
            {data.items.map((n) => {
              const href = relatedHref(n);
              return (
                <li
                  key={n.id}
                  className={`flex flex-col gap-3 rounded-2xl border px-4 py-4 text-sm shadow-[0_12px_30px_rgba(2,6,23,0.14)] sm:flex-row sm:items-start sm:justify-between ${
                    n.is_read ? "border-white/[0.06] bg-white/[0.02]" : "border-indigo-400/15 bg-indigo-500/[0.06]"
                  }`}
                >
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`rounded-lg border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${levelBadgeClass(n.level)}`}
                      >
                        {n.level}
                      </span>
                      <span className="rounded border border-white/10 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-400">
                        {formatNotificationEventLabel(n.type)}
                      </span>
                      <span className="font-medium leading-6 text-slate-100">{n.title}</span>
                    </div>
                    <p className="leading-6 text-slate-300">{n.message}</p>
                    <div className="text-xs text-slate-500">{formatDate(n.created_at)}</div>
                    {href ? (
                      <Link href={href} className="inline-flex text-xs font-medium text-indigo-200 underline underline-offset-4">
                        Open related page
                      </Link>
                    ) : null}
                  </div>
                  {!n.is_read ? (
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      className="shrink-0"
                      disabled={busyId === n.id}
                      onClick={() => void onMarkRead(n.id)}
                    >
                      {busyId === n.id ? "…" : "Mark read"}
                    </Button>
                  ) : (
                    <span className="shrink-0 text-xs uppercase tracking-wide text-slate-500">Read</span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </SectionPanel>
    </AppShell>
  );
}
