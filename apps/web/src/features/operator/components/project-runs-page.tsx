"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type { AuthUser, PipelineRunRecord } from "@platform/shared-types";
import {
  buttonClassName,
  EmptyState,
  SectionPanel,
  StatusBadge,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { getPipelineRunSecondaryText } from "@/features/datasets/run-summary";
import { formatDate } from "@/lib/format";
import { formatRunTypeLabel } from "@/lib/run-labels";
import { cx } from "@/lib/utils";

type ProjectRunsPageProps = {
  currentUser: AuthUser;
  projectId: string;
  runs: PipelineRunRecord[];
};

const FILTERS: { key: string; label: string }[] = [
  { key: "", label: "All" },
  { key: "failed", label: "Failed" },
  { key: "running", label: "Running" },
  { key: "queued", label: "Waiting" },
  { key: "succeeded", label: "Succeeded" },
];

/** "4 s", "2 min", "1 h 5 min": how long a run took, for a person. */
export function formatRunDuration(run: Pick<PipelineRunRecord, "started_at" | "completed_at">) {
  if (!run.started_at || !run.completed_at) return "—";
  const seconds = Math.max(
    0,
    Math.round((Date.parse(run.completed_at) - Date.parse(run.started_at)) / 1000),
  );
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

/**
 * Automate → Runs: everything that has run in this project, newest first,
 * with failures one click away. Workflow runs keep their own history on the
 * workflow's page, which this links to from the Workflows tab.
 */
export function ProjectRunsPageView({ currentUser, projectId, runs }: ProjectRunsPageProps) {
  const [status, setStatus] = useState("");
  const counts = useMemo(() => {
    const result: Record<string, number> = { "": runs.length };
    for (const run of runs) result[run.status] = (result[run.status] ?? 0) + 1;
    return result;
  }, [runs]);
  const visible = status ? runs.filter((run) => run.status === status) : runs;

  return (
    <AppShell
      currentUser={currentUser}
      title="Runs"
      subtitle="Everything that has run in this project, newest first."
    >
      {runs.length === 0 ? (
        <EmptyState
          title="Nothing has run yet"
          description="Uploads, database imports, recipes and deliveries all show up here once they run."
          action={
            <Link href={`/projects/${projectId}/sources`} className={buttonClassName("primary", "sm")}>
              Add some data
            </Link>
          }
        />
      ) : (
        <SectionPanel
          title={`${visible.length} run${visible.length === 1 ? "" : "s"}`}
          actions={
            <div className="flex flex-wrap gap-1.5">
              {FILTERS.filter((filter) => filter.key === "" || counts[filter.key]).map((filter) => (
                <button
                  key={filter.key || "all"}
                  type="button"
                  aria-pressed={status === filter.key}
                  onClick={() => setStatus(filter.key)}
                  className={cx(
                    "rounded-full border px-3 py-1 text-[13px] transition",
                    status === filter.key
                      ? "border-[color:var(--accent)] bg-[color:var(--accent-faint)] text-ink"
                      : "border-line text-ink-3 hover:text-ink",
                  )}
                >
                  {filter.label}
                  <span className="ml-1.5 text-muted">{counts[filter.key] ?? 0}</span>
                </button>
              ))}
            </div>
          }
          contentClassName="px-0 py-0"
        >
          <Table edge="panel">
            <TableHead>
              <TableRow>
                <TableHeaderCell>What ran</TableHeaderCell>
                <TableHeaderCell>Result</TableHeaderCell>
                <TableHeaderCell>Started by</TableHeaderCell>
                <TableHeaderCell>When</TableHeaderCell>
                <TableHeaderCell className="text-right">Took</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {visible.map((run) => (
                <TableRow key={run.id}>
                  <TableCell>
                    <Link
                      href={`/projects/${projectId}/runs/${run.id}/audit`}
                      className="font-medium text-ink hover:text-[color:var(--accent-muted)]"
                    >
                      {formatRunTypeLabel(run.run_type)}
                    </Link>
                    <div className="mt-0.5 max-w-md truncate text-[13px] text-ink-3">
                      {getPipelineRunSecondaryText(run)}
                    </div>
                  </TableCell>
                  <TableCell>
                    <StatusBadge value={run.status} />
                  </TableCell>
                  <TableCell className="text-ink-2">{run.triggered_by_username ?? "A schedule"}</TableCell>
                  <TableCell className="text-ink-3">
                    {formatDate(run.started_at ?? run.created_at)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-ink-3">
                    {formatRunDuration(run)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </SectionPanel>
      )}
    </AppShell>
  );
}
