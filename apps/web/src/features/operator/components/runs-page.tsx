"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import type { AuthUser, OperatorRunRow } from "@platform/shared-types";
import { Button, buttonClassName, EmptyState, SectionPanel, StatusBadge, Table, TableBody, TableCell, TableHead, TableHeaderCell, TableRow } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { OperationalError } from "@/components/operational/operational-messages";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { formatRunTypeLabel } from "@/lib/run-labels";
import { cx } from "@/lib/utils";

type RunsPageProps = {
  currentUser: AuthUser;
  initialRuns: OperatorRunRow[];
};

const FILTERS: { key: string; label: string }[] = [
  { key: "", label: "All" },
  { key: "running", label: "Running" },
  { key: "queued", label: "Queued" },
  { key: "succeeded", label: "Succeeded" },
  { key: "failed", label: "Failed" },
];

/**
 * Every recent run across every project you can see, newest first. The old
 * route redirected into one project, which is no help to an operator watching
 * forty; this is the single place to answer "what just failed, anywhere?".
 */
export function RunsPageView({ currentUser, initialRuns }: RunsPageProps) {
  const [runs, setRuns] = useState(initialRuns);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (nextStatus: string) => {
    setLoading(true);
    setError(null);
    try {
      const query = nextStatus ? `?status=${encodeURIComponent(nextStatus)}` : "";
      const response = await apiFetch<{ items: OperatorRunRow[] }>(`/runs${query}`);
      setRuns(response.items);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  // Skip the first load: the server already handed us the unfiltered list.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    if (!mounted) {
      setMounted(true);
      return;
    }
    void load(status);
  }, [status, mounted, load]);

  return (
    <AppShell
      currentUser={currentUser}
      title="All runs"
      subtitle="Recent runs across every project you can open."
    >
      <div className="mb-4 flex flex-wrap gap-1.5">
        {FILTERS.map((filter) => (
          <button
            key={filter.key || "all"}
            type="button"
            onClick={() => setStatus(filter.key)}
            className={cx(
              "rounded-full border px-3 py-1.5 text-[12px] font-medium transition",
              status === filter.key
                ? "border-[color:var(--accent-soft)] bg-[color:var(--accent-faint)] text-ink"
                : "border-line bg-surface text-ink-2 hover:border-line-strong",
            )}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {error ? <OperationalError title="Could not load runs" message={error} /> : null}

      <SectionPanel
        title="Recent runs"
        description={loading ? "Loading…" : `${runs.length} run${runs.length === 1 ? "" : "s"}`}
      >
        {runs.length === 0 ? (
          <EmptyState size="compact"
            title="No runs to show"
            description={
              status
                ? "Nothing with this status. Try another filter."
                : "Uploads, imports, recipes and deliveries appear here once they run."
            }
            action={
              status ? (
                <Button variant="secondary" size="sm" onClick={() => setStatus("")}>
                  Show all
                </Button>
              ) : (
                <Link href="/projects" className={buttonClassName("primary", "sm")}>
                  Open a project
                </Link>
              )
            }
          />
        ) : (
          <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
            <Table minWidth={720}>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Project</TableHeaderCell>
                  <TableHeaderCell>Type</TableHeaderCell>
                  <TableHeaderCell>Pipeline</TableHeaderCell>
                  <TableHeaderCell>Status</TableHeaderCell>
                  <TableHeaderCell>Started</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {runs.map((run) => (
                  <TableRow key={run.id}>
                    <TableCell>
                      <Link
                        href={`/projects/${run.project_id}`}
                        className="font-medium text-ink hover:text-accent"
                      >
                        {run.project_name}
                      </Link>
                    </TableCell>
                    <TableCell className="text-ink-2">{formatRunTypeLabel(run.run_type)}</TableCell>
                    <TableCell className="text-ink-3">{run.pipeline_name ?? "—"}</TableCell>
                    <TableCell>
                      <StatusBadge value={run.status} />
                    </TableCell>
                    <TableCell className="text-xs text-ink-3">
                      {run.started_at ? formatDate(run.started_at) : formatDate(run.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </SectionPanel>
    </AppShell>
  );
}
