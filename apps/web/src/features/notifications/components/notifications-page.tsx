"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import type { AuthUser, UserNotificationListResponse, UserNotificationRecord } from "@platform/shared-types";
import { Badge, Button, buttonClassName, EmptyState, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { OperationalLoading } from "@/components/operational/operational-messages";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { formatNotificationEventLabel } from "@/lib/run-labels";
import { recipeHref } from "@/lib/navigation";

type NotificationsPageProps = {
  currentUser: AuthUser;
};

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
    return recipeHref(n.project_id, n.related_pipeline_id);
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
      subtitle="Messages about your runs, reports and mentions."
      currentUser={currentUser}
      actions={
        <>
          <Link href="/settings#notifications" className={buttonClassName("secondary", "sm")}>
            Choose what you get
          </Link>
          {data && data.unread_count > 0 ? (
            <Button type="button" size="sm" onClick={() => void onMarkAll()} disabled={markingAll}>
              {markingAll ? "Updating…" : "Mark all read"}
            </Button>
          ) : null}
        </>
      }
    >
      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>
      ) : null}

      <SectionPanel
        title={data ? (data.unread_count > 0 ? `${data.unread_count} unread` : "All caught up") : "Notifications"}
        description="Routine successes are added up into one summary a day; repeats of the same failure are grouped."
      >
        {!data ? (
          <OperationalLoading message="Loading notifications…" />
        ) : data.items.length === 0 ? (
          <EmptyState size="compact"
            title="Nothing new"
            description="Failures, finished reports and mentions of you appear here."
            action={
              <Link href="/settings#notifications" className={buttonClassName("secondary", "sm")}>
                Choose what you get
              </Link>
            }
          />
        ) : (
          <ul className="divide-y divide-line">
            {data.items.map((n) => {
              const href = relatedHref(n);
              const count = n.group_count ?? 1;
              const isSummary = n.type.startsWith("digest_");
              return (
                <li key={n.id} className="flex items-start gap-3 py-3">
                  <span
                    className={`mt-2 h-2 w-2 shrink-0 rounded-full ${n.is_read ? "bg-line-strong" : dotClass(n.level)}`}
                    aria-label={n.is_read ? "Read" : "Unread"}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`text-[14px] ${n.is_read ? "text-ink-2" : "font-medium text-ink"}`}>
                        {n.title}
                      </span>
                      {!isSummary && count > 1 ? (
                        <Badge>
                          {count} times
                        </Badge>
                      ) : null}
                      <span className="text-[12px] text-muted">
                        {isSummary ? "Daily summary" : formatNotificationEventLabel(n.type)}
                      </span>
                    </div>
                    <p className="mt-0.5 text-[13px] leading-5 text-ink-3">{n.message}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-3 text-[12px] text-muted">
                      <span>{count > 1 ? `Latest ${formatDate(n.updated_at)}` : formatDate(n.created_at)}</span>
                      {href ? (
                        <Link href={href} className="font-medium text-[color:var(--accent-muted)] hover:underline">
                          Open
                        </Link>
                      ) : null}
                    </div>
                  </div>
                  {!n.is_read ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="shrink-0"
                      disabled={busyId === n.id}
                      onClick={() => void onMarkRead(n.id)}
                    >
                      {busyId === n.id ? "…" : "Mark read"}
                    </Button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </SectionPanel>
    </AppShell>
  );
}

function dotClass(level: string): string {
  if (level === "error") return "bg-danger";
  if (level === "warning") return "bg-warning";
  if (level === "success") return "bg-success";
  return "bg-[color:var(--accent)]";
}
