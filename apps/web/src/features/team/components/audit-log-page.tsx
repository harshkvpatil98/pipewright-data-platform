"use client";

import { useCallback, useState } from "react";

import type { AuditEntry, AuditListResponse, AuditOutcome, AuthUser } from "@platform/shared-types";
import { Badge, type BadgeTone, SectionPanel, Table, TableBody, TableCell, TableHead, TableHeaderCell, TableRow } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";
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
  { id: "succeeded", label: "Done" },
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
            Nothing recorded yet. Changes are recorded here; looking at things is not.
          </p>
        ) : (
          <Table minWidth={640}>
            <TableHead>
              <TableRow>
                <TableHeaderCell>When</TableHeaderCell>
                <TableHeaderCell>Who</TableHeaderCell>
                <TableHeaderCell>What they did</TableHeaderCell>
                <TableHeaderCell>Result</TableHeaderCell>
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

const OUTCOME_LABEL: Record<AuditOutcome, string> = {
  succeeded: "Done",
  denied: "Refused",
  failed: "Failed",
};

/** One entry as a sentence; the request it came from is on hover for whoever needs it. */
function AuditRow({ entry }: { entry: AuditEntry }) {
  const summary = entry.summary || entry.action;
  return (
    <TableRow title={`${entry.method} ${entry.path} (${entry.status_code})`}>
      <TableCell className="whitespace-nowrap text-[13px] text-ink-3">{formatDateTime(entry.created_at)}</TableCell>
      <TableCell className="text-[14px] text-ink">
        {entry.actor_username ?? "Someone who has left"}
        {entry.credential ? <span className="block text-[12px] text-muted">with {entry.credential}</span> : null}
      </TableCell>
      <TableCell>
        <div className="text-[14px] text-ink">{summary.charAt(0).toUpperCase() + summary.slice(1)}</div>
        {entry.object_name ? <div className="text-[13px] text-ink-3">{entry.object_name}</div> : null}
      </TableCell>
      <TableCell>
        <Badge tone={OUTCOME_TONE[entry.outcome]}>{OUTCOME_LABEL[entry.outcome] ?? entry.outcome}</Badge>
      </TableCell>
    </TableRow>
  );
}
