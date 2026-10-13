"use client";

import { useCallback, useState } from "react";

import type { AuditEntry, AuditListResponse, AuditOutcome, AuthUser } from "@platform/shared-types";
import { Badge, type BadgeTone, SectionPanel, Table, TableBody, TableCell, TableHead, TableHeaderCell, TableRow } from "@platform/shared-ui";

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

const OUTCOME_TONE: Record<AuditOutcome, BadgeTone> = {
  succeeded: "success",
  denied: "warning",
  failed: "danger",
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
      title="Audit log"
      subtitle="Who changed what in this project, and when."
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
            Nothing recorded yet. Only requests that could change something are recorded, not reads.
          </p>
        ) : (
          <Table minWidth={640}>
            <TableHead>
              <TableRow className="text-[12px] text-muted">
                <TableHeaderCell>When</TableHeaderCell>
                <TableHeaderCell>Who</TableHeaderCell>
                <TableHeaderCell>Did what</TableHeaderCell>
                <TableHeaderCell>Outcome</TableHeaderCell>
                <TableHeaderCell>Took</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {data.items.map((entry) => (
                <AuditRow key={entry.id} entry={entry} />
              ))}
            </TableBody>
          </Table>
        )}
      </SectionPanel>
    </AppShell>
  );
}

function AuditRow({ entry }: { entry: AuditEntry }) {
  return (
    <TableRow>
      <TableCell className="text-[12px] text-muted">{formatDate(entry.created_at)}</TableCell>
      <TableCell className="text-[12.5px] text-ink">
        {entry.actor_username ?? "unknown"}
      </TableCell>
      <TableCell>
        <div className="text-[12.5px] capitalize text-ink">{entry.action}</div>
        <div className="truncate font-mono text-[12px] text-muted">
          {entry.method} {entry.path}
        </div>
      </TableCell>
      <TableCell>
        <Badge tone={OUTCOME_TONE[entry.outcome]}>
          {entry.outcome === "denied" ? "refused" : entry.outcome}
        </Badge>
        <span className="ml-1.5 text-[12px] text-muted">{entry.status_code}</span>
      </TableCell>
      <TableCell className="tabular text-[12px] text-muted">
        {entry.duration_ms !== null ? `${entry.duration_ms} ms` : "—"}
      </TableCell>
    </TableRow>
  );
}
