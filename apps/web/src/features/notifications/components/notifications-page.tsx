"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import type { AuthUser, UserNotificationListResponse, UserNotificationRecord } from "@platform/shared-types";
import { Button, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { OperationalEmpty, OperationalLoading } from "@/components/operational/operational-messages";
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
      return "border-danger-line bg-danger-soft text-danger";
    case "warning":
      return "border-warning-line bg-warning-soft text-warning";
    case "success":
      return "border-success-line bg-success-soft text-success";
    default:
      return "border-line bg-surface-2 text-ink";
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
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>
      ) : null}

      <SectionPanel
        title="Recent activity"
        description={data ? `${data.unread_count} unread` : "Fetching your latest alerts."}
      >
        {data ? (
          <div className="mb-5 grid gap-3 md:grid-cols-3">
            <div className="rounded-2xl border border-line bg-sunken px-4 py-4 text-sm text-ink-2">
              <div className="text-[11px] uppercase tracking-[0.18em] text-muted">Unread</div>
              <div className="mt-2 text-2xl font-semibold text-ink">{data.unread_count}</div>
            </div>
            <div className="rounded-2xl border border-line bg-sunken px-4 py-4 text-sm text-ink-2">
              <div className="text-[11px] uppercase tracking-[0.18em] text-muted">Visible in feed</div>
              <div className="mt-2 text-2xl font-semibold text-ink">{data.items.length}</div>
            </div>
            <div className="rounded-2xl border border-line bg-sunken px-4 py-4 text-sm leading-6 text-ink-3">
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
                  className={`flex flex-col gap-3 rounded-2xl border px-4 py-4 text-sm shadow-[var(--shadow-md)] sm:flex-row sm:items-start sm:justify-between ${
                    n.is_read ? "border-line bg-surface" : "border-accent-line bg-accent-soft"
                  }`}
                >
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`rounded-lg border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${levelBadgeClass(n.level)}`}
                      >
                        {n.level}
                      </span>
                      <span className="rounded border border-line px-2 py-0.5 text-[10px] uppercase tracking-wide text-ink-3">
                        {formatNotificationEventLabel(n.type)}
                      </span>
                      <span className="font-medium leading-6 text-ink">{n.title}</span>
                    </div>
                    <p className="leading-6 text-ink-2">{n.message}</p>
                    <div className="text-xs text-muted">{formatDate(n.created_at)}</div>
                    {href ? (
                      <Link href={href} className="inline-flex text-xs font-medium text-accent underline underline-offset-4">
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
                    <span className="shrink-0 text-xs uppercase tracking-wide text-muted">Read</span>
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
