"use client";

import Link from "next/link";
import { useState } from "react";

import type { ActivityItem, ActivityKind, ActivityResponse, AuthUser } from "@platform/shared-types";
import { ACTIVITY_KINDS } from "@platform/shared-types";
import { Button, EmptyState, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";
import { formatDay, formatTime } from "@/lib/format";

const KIND_WORDS: Record<ActivityKind, string> = {
  changes: "Changes",
  runs: "Runs",
  incidents: "Incidents",
  comments: "Comments",
  alerts: "Alerts",
};

const LEVEL_DOT: Record<ActivityItem["level"], string> = {
  info: "bg-ink-3",
  success: "bg-success",
  warning: "bg-warning",
  error: "bg-danger",
};


/** "Today", "Yesterday", or the date, in the viewer's own time zone. */
export function dayLabel(at: string, now: Date = new Date()): string {
  const day = new Date(at);
  const start = (moment: Date) => new Date(moment.getFullYear(), moment.getMonth(), moment.getDate()).getTime();
  const days = Math.round((start(now) - start(day)) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return formatDay(day);
}

/** Items grouped under their day, keeping the stream's order. */
export function byDay(items: ActivityItem[], now: Date = new Date()): { day: string; items: ActivityItem[] }[] {
  const groups: { day: string; items: ActivityItem[] }[] = [];
  for (const item of items) {
    const day = dayLabel(item.at, now);
    const last = groups[groups.length - 1];
    if (last && last.day === day) last.items.push(item);
    else groups.push({ day, items: [item] });
  }
  return groups;
}

/**
 * What happened in a project, newest first (A8, Y6): changes, runs,
 * incidents, comments and alerts in one list, with who and when.
 */
export function ActivityPageView({
  currentUser,
  projectId,
  initial,
}: {
  currentUser: AuthUser;
  projectId: string;
  initial: ActivityResponse;
}) {
  const [kind, setKind] = useState<ActivityKind | null>(null);
  const [items, setItems] = useState(initial.items);
  const [nextOffset, setNextOffset] = useState(initial.next_offset);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (chosen: ActivityKind | null, offset: number) => {
    setBusy(true);
    setError(null);
    try {
      const query = new URLSearchParams({ offset: String(offset) });
      if (chosen) query.set("kind", chosen);
      const page = await apiFetch<ActivityResponse>(`/projects/${projectId}/activity?${query}`);
      setItems((current) => {
        if (offset === 0) return page.items;
        // New activity can move items down a page; show each one once.
        const seen = new Set(current.map((item) => item.id));
        return [...current, ...page.items.filter((item) => !seen.has(item.id))];
      });
      setNextOffset(page.next_offset);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const choose = (next: ActivityKind | null) => {
    setKind(next);
    void load(next, 0);
  };

  return (
    <AppShell currentUser={currentUser} title="Activity" subtitle="What happened in this project, newest first.">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Show">
        {[null, ...ACTIVITY_KINDS].map((value) => (
          <button
            key={value ?? "all"}
            type="button"
            aria-pressed={kind === value}
            onClick={() => choose(value)}
            className={cx(
              "rounded-full border px-3 py-1.5 text-[13px] transition",
              kind === value
                ? "border-[color:var(--accent)] bg-[color:var(--accent-soft)] text-ink"
                : "border-line text-ink-3 hover:text-ink",
            )}
          >
            {value ? KIND_WORDS[value] : "Everything"}
          </button>
        ))}
      </div>

      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>
      ) : null}

      {items.length === 0 ? (
        <EmptyState
          title={kind ? `No ${KIND_WORDS[kind].toLowerCase()} yet` : "Nothing has happened yet"}
          description="Changes, runs, incidents, comments and alerts appear here as they happen."
        />
      ) : (
        byDay(items).map((group) => (
          <SectionPanel key={group.day} title={group.day}>
            <ol className="divide-y divide-line">
              {group.items.map((item) => (
                <li key={item.id} className="flex items-start gap-3 py-2.5">
                  <span className={cx("mt-1.5 h-2 w-2 shrink-0 rounded-full", LEVEL_DOT[item.level])} aria-hidden />
                  <div className="min-w-0 flex-1">
                    <div className="text-[13.5px] text-ink">
                      {item.href ? (
                        <Link href={item.href} className="hover:underline">
                          {item.sentence}
                        </Link>
                      ) : (
                        item.sentence
                      )}
                    </div>
                    {item.detail ? <div className="mt-0.5 break-words text-[12.5px] text-ink-3">{item.detail}</div> : null}
                  </div>
                  <time dateTime={item.at} className="shrink-0 text-[12px] text-ink-3">
                    {formatTime(item.at)}
                  </time>
                </li>
              ))}
            </ol>
          </SectionPanel>
        ))
      )}

      {nextOffset !== null ? (
        <div className="flex justify-center">
          <Button variant="secondary" disabled={busy} onClick={() => void load(kind, nextOffset)}>
            {busy ? "Loading…" : "Show older"}
          </Button>
        </div>
      ) : items.length > 0 ? (
        <p className="text-center text-[12.5px] text-ink-3">
          That is everything here. The{" "}
          <Link href={`/projects/${projectId}/audit-log`} className="underline">
            audit log
          </Link>{" "}
          keeps every change, including refused ones.
        </p>
      ) : null}
    </AppShell>
  );
}
