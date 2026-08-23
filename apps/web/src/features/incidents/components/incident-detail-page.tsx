"use client";

import Link from "next/link";
import { useCallback, useState } from "react";

import type { AuthUser, IncidentDetail } from "@platform/shared-types";
import { Button, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { cx } from "@/lib/utils";

import { SEVERITY_TONE, SOURCE_LABEL, StatusPill } from "./incidents-page";

type IncidentDetailPageProps = {
  currentUser: AuthUser;
  projectId: string;
  initial: IncidentDetail;
};

const EVENT_ICON: Record<string, { icon: "warning" | "check" | "info" | "refresh"; tone: string }> = {
  opened: { icon: "warning", tone: "text-danger" },
  recurred: { icon: "refresh", tone: "text-warning" },
  acknowledged: { icon: "info", tone: "text-info" },
  assigned: { icon: "info", tone: "text-info" },
  comment: { icon: "info", tone: "text-ink-3" },
  resolved: { icon: "check", tone: "text-success" },
  auto_resolved: { icon: "check", tone: "text-success" },
  reopened: { icon: "warning", tone: "text-danger" },
};

export function IncidentDetailPageView({
  currentUser,
  projectId,
  initial,
}: IncidentDetailPageProps) {
  const [incident, setIncident] = useState(initial);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const act = useCallback(
    async (action: string, body?: Record<string, unknown>) => {
      setBusy(action);
      setError(null);
      try {
        setIncident(
          await apiFetch<IncidentDetail>(
            `/projects/${projectId}/incidents/${incident.id}/${action}`,
            { method: "POST", body: JSON.stringify(body ?? {}) },
          ),
        );
        if (action === "comments") setComment("");
      } catch (caught) {
        setError(extractErrorMessage(caught));
      } finally {
        setBusy(null);
      }
    },
    [projectId, incident.id],
  );

  const resolved = incident.status === "resolved";

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Trust"
      title={incident.title}
      subtitle={incident.summary ?? "Opened automatically by a check that failed."}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Link
          href={`/projects/${projectId}/incidents`}
          className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1.5 text-[12px] text-ink-2 transition hover:bg-surface-2"
        >
          <Icon name="chevronLeft" size={12} />
          All incidents
        </Link>
        <span className={cx("rounded-full border px-2 py-0.5 text-[11px] capitalize", SEVERITY_TONE[incident.severity])}>
          {incident.severity}
        </span>
        <StatusPill status={incident.status} />
        <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[11px] text-ink-3">
          {SOURCE_LABEL[incident.source_kind] ?? incident.source_kind}
        </span>
      </div>

      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <SectionPanel
          title="Timeline"
          description="Every occurrence and every action, in the order it happened."
        >
          <ol className="space-y-3">
            {incident.events.map((event) => {
              const style = EVENT_ICON[event.kind] ?? EVENT_ICON.comment;
              return (
                <li key={event.id} className="flex gap-3">
                  <div
                    className={cx(
                      "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-line bg-surface",
                      style.tone,
                    )}
                  >
                    <Icon name={style.icon} size={11} />
                  </div>
                  <div className="min-w-0 flex-1 border-b border-line pb-3">
                    <div className="text-[12.5px] text-ink">{event.message}</div>
                    <div className="mt-0.5 text-[11px] text-muted">
                      {event.kind.replace("_", " ")}
                      {event.actor_name ? ` · ${event.actor_name}` : ""} ·{" "}
                      {formatDate(event.created_at)}
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>

          <div className="mt-4 flex gap-2">
            <input
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              placeholder="Add a note for whoever picks this up next…"
              className="h-9 flex-1 rounded-lg border border-line bg-sunken px-3 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)]"
            />
            <Button
              variant="secondary"
              disabled={!comment.trim() || busy !== null}
              onClick={() => void act("comments", { message: comment })}
            >
              Comment
            </Button>
          </div>
        </SectionPanel>

        <div className="space-y-4">
          <SectionPanel title="Actions">
            <div className="space-y-2">
              {!resolved ? (
                <>
                  {incident.status === "open" ? (
                    <Button
                      variant="secondary"
                      className="w-full"
                      disabled={busy !== null}
                      onClick={() => void act("acknowledge")}
                    >
                      Acknowledge
                    </Button>
                  ) : null}
                  <Button
                    className="w-full"
                    disabled={busy !== null}
                    onClick={() => void act("resolve", { note: comment.trim() || null })}
                  >
                    Resolve
                  </Button>
                  <Button
                    variant="secondary"
                    className="w-full"
                    disabled={busy !== null}
                    onClick={() => void act("assign", { assignee_user_id: currentUser.id })}
                  >
                    Assign to me
                  </Button>
                </>
              ) : (
                <Button
                  variant="secondary"
                  className="w-full"
                  disabled={busy !== null}
                  onClick={() => void act("reopen", { note: comment.trim() || null })}
                >
                  Reopen
                </Button>
              )}
            </div>
          </SectionPanel>

          <SectionPanel title="Details">
            <dl className="space-y-2 text-[12px]">
              <Detail label="First seen" value={formatDate(incident.opened_at)} />
              <Detail label="Last seen" value={formatDate(incident.last_seen_at)} />
              <Detail label="Occurrences" value={String(incident.occurrence_count)} />
              {incident.dataset_name ? (
                <Detail
                  label="Dataset"
                  value={
                    <Link
                      href={`/projects/${projectId}/datasets/${incident.dataset_id}`}
                      className="text-[color:var(--accent)] hover:underline"
                    >
                      {incident.dataset_name}
                    </Link>
                  }
                />
              ) : null}
              {incident.assignee_name ? (
                <Detail label="Assignee" value={incident.assignee_name} />
              ) : null}
              {incident.resolution_note ? (
                <Detail label="Resolution" value={incident.resolution_note} />
              ) : null}
            </dl>
          </SectionPanel>
        </div>
      </div>
    </AppShell>
  );
}

function Detail({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="shrink-0 text-muted">{label}</dt>
      <dd className="text-right text-ink">{value}</dd>
    </div>
  );
}
