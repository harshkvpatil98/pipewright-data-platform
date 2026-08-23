"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";

import type {
  AuthUser,
  Incident,
  IncidentListResponse,
  IncidentSeverity,
  IncidentStatus,
} from "@platform/shared-types";
import { Button, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { cx } from "@/lib/utils";

type IncidentsPageProps = {
  currentUser: AuthUser;
  projectId: string;
  initial: IncidentListResponse;
};

export const SEVERITY_TONE: Record<IncidentSeverity, string> = {
  critical: "border-danger-line bg-danger-soft text-danger",
  high: "border-warning-line bg-warning-soft text-warning",
  medium: "border-warning-line bg-warning-soft text-warning",
  low: "border-line bg-surface-2 text-ink-2",
};

export const SOURCE_LABEL: Record<string, string> = {
  quality: "Quality rule",
  drift: "Schema drift",
  freshness: "Freshness",
  anomaly: "Anomaly",
  workflow: "Workflow",
};

const FILTERS: { id: IncidentStatus | "all"; label: string }[] = [
  { id: "open", label: "Open" },
  { id: "acknowledged", label: "Acknowledged" },
  { id: "resolved", label: "Resolved" },
  { id: "all", label: "All" },
];

export function IncidentsPageView({ currentUser, projectId, initial }: IncidentsPageProps) {
  const [data, setData] = useState(initial);
  const [filter, setFilter] = useState<IncidentStatus | "all">("open");
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  const load = useCallback(
    async (next: IncidentStatus | "all") => {
      setFilter(next);
      setError(null);
      try {
        const query = next === "all" ? "" : `?status=${next}`;
        setData(await apiFetch<IncidentListResponse>(`/projects/${projectId}/incidents${query}`));
      } catch (caught) {
        setError(extractErrorMessage(caught));
      }
    },
    [projectId],
  );

  const runFreshnessCheck = useCallback(async () => {
    setChecking(true);
    setError(null);
    try {
      await apiFetch(`/projects/${projectId}/freshness/check`, { method: "POST" });
      await load(filter);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setChecking(false);
    }
  }, [projectId, filter, load]);

  const counts = useMemo(
    () => [
      { label: "Open", value: data.open_count, tone: "text-danger" },
      { label: "Acknowledged", value: data.acknowledged_count, tone: "text-warning" },
      { label: "Resolved", value: data.resolved_count, tone: "text-success" },
    ],
    [data],
  );

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Trust"
      title="Incidents"
      subtitle="Failing rules, schema drift, stale datasets, and metrics outside their usual range — grouped so that one recurring problem is one line, not thirty."
    >
      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-3">
        {counts.map((count) => (
          <div
            key={count.label}
            className="rounded-2xl border border-line bg-surface px-4 py-3"
          >
            <div className={cx("text-2xl font-semibold", count.tone)}>{count.value}</div>
            <div className="mt-0.5 text-[12px] text-muted">{count.label}</div>
          </div>
        ))}
      </div>

      <SectionPanel
        title="What needs attention"
        description="An incident stays open until someone resolves it, or until the condition that opened it goes away on its own."
        actions={
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={runFreshnessCheck} disabled={checking}>
              {checking ? "Checking…" : "Run freshness check"}
            </Button>
          </div>
        }
      >
        <div className="mb-3 flex flex-wrap gap-1.5">
          {FILTERS.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => void load(option.id)}
              className={cx(
                "rounded-lg px-2.5 py-1 text-[12px] transition",
                filter === option.id
                  ? "bg-[color:var(--accent)] text-accent-ink"
                  : "border border-line text-ink-3 hover:text-ink",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>

        {data.items.length === 0 ? (
          <EmptyState filter={filter} />
        ) : (
          <ul className="space-y-2">
            {data.items.map((incident) => (
              <IncidentRow key={incident.id} projectId={projectId} incident={incident} />
            ))}
          </ul>
        )}
      </SectionPanel>
    </AppShell>
  );
}

function EmptyState({ filter }: { filter: IncidentStatus | "all" }) {
  return (
    <div className="rounded-xl border border-line px-4 py-8 text-center">
      <div className="text-[13px] text-ink-2">
        {filter === "open"
          ? "Nothing is broken right now."
          : `No ${filter === "all" ? "" : filter + " "}incidents.`}
      </div>
      <div className="mt-1 text-[12px] text-muted">
        Incidents appear when a quality gate fails, a schema breaks, a dataset goes stale, or a
        metric leaves its usual range.
      </div>
    </div>
  );
}

function IncidentRow({ projectId, incident }: { projectId: string; incident: Incident }) {
  return (
    <li className="relative rounded-xl border border-line bg-surface px-4 py-3 transition hover:border-line-strong">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            href={`/projects/${projectId}/incidents/${incident.id}`}
            className="text-[13.5px] font-medium text-ink after:absolute after:inset-0 after:content-['']"
          >
            {incident.title}
          </Link>
          {incident.summary ? (
            <p className="mt-1 line-clamp-2 text-[12.5px] text-ink-3">{incident.summary}</p>
          ) : null}
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[11.5px] text-muted">
            <span className="rounded bg-surface-2 px-1.5 py-0.5">
              {SOURCE_LABEL[incident.source_kind] ?? incident.source_kind}
            </span>
            {incident.dataset_name ? <span>{incident.dataset_name}</span> : null}
            <span>opened {formatDate(incident.opened_at)}</span>
            {incident.occurrence_count > 1 ? (
              <span className="text-warning">seen {incident.occurrence_count}×</span>
            ) : null}
            {incident.assignee_name ? <span>· {incident.assignee_name}</span> : null}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span
            className={cx(
              "rounded-full border px-2 py-0.5 text-[11px] capitalize",
              SEVERITY_TONE[incident.severity],
            )}
          >
            {incident.severity}
          </span>
          <StatusPill status={incident.status} />
        </div>
      </div>
    </li>
  );
}

export function StatusPill({ status }: { status: IncidentStatus }) {
  const tone =
    status === "resolved"
      ? "border-success-line bg-success-soft text-success"
      : status === "acknowledged"
        ? "border-info-line bg-info-soft text-info"
        : "border-danger-line bg-danger-soft text-danger";
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] capitalize", tone)}>
      <Icon name={status === "resolved" ? "check" : "warning"} size={10} />
      {status}
    </span>
  );
}
