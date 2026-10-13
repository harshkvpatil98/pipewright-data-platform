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
import {
  Badge,
  type BadgeTone,
  Button,
  buttonClassName,
  EmptyState,
  Icon,
  SectionPanel,
} from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { cx } from "@/lib/utils";

type IncidentsPageProps = {
  currentUser: AuthUser;
  projectId: string;
  initial: IncidentListResponse;
};

const SEVERITY: Record<IncidentSeverity, { tone: BadgeTone; label: string }> = {
  critical: { tone: "danger", label: "Critical" },
  high: { tone: "warning", label: "High" },
  medium: { tone: "warning", label: "Medium" },
  low: { tone: "neutral", label: "Low" },
};

export const SOURCE_LABEL: Record<string, string> = {
  quality: "Check",
  drift: "Schema change",
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
      title="Incidents"
      subtitle="Problems that need a person, newest first."
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
          <EmptyState
            size="compact"
            title={
              filter === "open"
                ? "Nothing is broken right now."
                : filter === "all"
                  ? "No incidents yet."
                  : `No ${filter} incidents.`
            }
            description="An incident opens when a check fails, a source changes shape, data is late, or a number leaves its usual range."
            action={
              <Link href={`/projects/${projectId}/checks`} className={buttonClassName("secondary", "sm")}>
                See your checks
              </Link>
            }
          />
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
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-muted">
            <Badge>
              {SOURCE_LABEL[incident.source_kind] ?? incident.source_kind}
            </Badge>
            {incident.dataset_name ? <span>{incident.dataset_name}</span> : null}
            <span>opened {formatDate(incident.opened_at)}</span>
            {incident.occurrence_count > 1 ? (
              <span className="text-warning">seen {incident.occurrence_count}×</span>
            ) : null}
            {incident.assignee_name ? <span>· {incident.assignee_name}</span> : null}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <IncidentSeverityBadge severity={incident.severity} />
          <IncidentStatusBadge status={incident.status} />
        </div>
      </div>
    </li>
  );
}

export function IncidentSeverityBadge({ severity }: { severity: IncidentSeverity }) {
  const { tone, label } = SEVERITY[severity] ?? { tone: "neutral" as const, label: severity };
  return <Badge tone={tone}>{label}</Badge>;
}

const STATUS: Record<IncidentStatus, { tone: BadgeTone; label: string }> = {
  open: { tone: "danger", label: "Open" },
  acknowledged: { tone: "info", label: "Acknowledged" },
  resolved: { tone: "success", label: "Resolved" },
};

export function IncidentStatusBadge({ status }: { status: IncidentStatus }) {
  const { tone, label } = STATUS[status] ?? { tone: "neutral" as const, label: status };
  return (
    <Badge tone={tone}>
      <Icon name={status === "resolved" ? "check" : "warning"} size={12} />
      {label}
    </Badge>
  );
}
