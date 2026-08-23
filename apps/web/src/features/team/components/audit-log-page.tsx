"use client";

import { useCallback, useState } from "react";

import type { AuditEntry, AuditListResponse, AuditOutcome, AuthUser } from "@platform/shared-types";
import { SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { cx } from "@/lib/utils";

type AuditLogPageProps = {
  currentUser: AuthUser;
  projectId: string;
  initial: AuditListResponse;
};

const OUTCOME_TONE: Record<AuditOutcome, string> = {
  succeeded: "border-success-line bg-success-soft text-success",
  denied: "border-warning-line bg-warning-soft text-warning",
  failed: "border-danger-line bg-danger-soft text-danger",
};

const FILTERS: { id: AuditOutcome | "all"; label: string }[] = [
  { id: "all", label: "Everything" },
  { id: "succeeded", label: "Succeeded" },
  { id: "denied", label: "Refused" },
  { id: "failed", label: "Failed" },
];

export function AuditLogPageView({ currentUser, projectId, initial }: AuditLogPageProps) {
  const [data, setData] = useState(initial);
  const [filter, setFilter] = useState<AuditOutcome | "all">("all");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (next: AuditOutcome | "all") => {
      setFilter(next);
      setError(null);
      try {
        const query = next === "all" ? "" : `?outcome=${next}`;
        setData(await apiFetch<AuditListResponse>(`/projects/${projectId}/audit-log${query}`));
      } catch (caught) {
        setError(extractErrorMessage(caught));
      }
    },
    [projectId],
  );

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Team"
      title="Audit log"
      subtitle="Every request that could change something, including the ones that were refused. Written by the gateway rather than by each service, so nothing gets through unlogged."
    >
      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}

      <SectionPanel title="Activity" description="Newest first.">
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
          <p className="rounded-xl border border-line px-4 py-8 text-center text-[12.5px] text-muted">
            Nothing recorded yet. Reads are not audited — only requests that could change something.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left">
              <thead>
                <tr className="text-[11px] uppercase tracking-[0.14em] text-muted">
                  <th className="pb-2 pr-3 font-medium">When</th>
                  <th className="pb-2 pr-3 font-medium">Who</th>
                  <th className="pb-2 pr-3 font-medium">Did what</th>
                  <th className="pb-2 pr-3 font-medium">Outcome</th>
                  <th className="pb-2 font-medium">Took</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.items.map((entry) => (
                  <AuditRow key={entry.id} entry={entry} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionPanel>
    </AppShell>
  );
}

function AuditRow({ entry }: { entry: AuditEntry }) {
  return (
    <tr className="align-top">
      <td className="py-2.5 pr-3 text-[11.5px] text-muted">{formatDate(entry.created_at)}</td>
      <td className="py-2.5 pr-3 text-[12.5px] text-ink">
        {entry.actor_username ?? "unknown"}
      </td>
      <td className="py-2.5 pr-3">
        <div className="text-[12.5px] capitalize text-ink">{entry.action}</div>
        <div className="truncate font-mono text-[10.5px] text-muted">
          {entry.method} {entry.path}
        </div>
      </td>
      <td className="py-2.5 pr-3">
        <span
          className={cx(
            "rounded-full border px-2 py-0.5 text-[11px] capitalize",
            OUTCOME_TONE[entry.outcome],
          )}
        >
          {entry.outcome === "denied" ? "refused" : entry.outcome}
        </span>
        <span className="ml-1.5 text-[10.5px] text-muted">{entry.status_code}</span>
      </td>
      <td className="py-2.5 tabular text-[11.5px] text-muted">
        {entry.duration_ms !== null ? `${entry.duration_ms} ms` : "—"}
      </td>
    </tr>
  );
}
