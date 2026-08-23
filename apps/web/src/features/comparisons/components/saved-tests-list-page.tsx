"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { AuthUser, SavedStatisticalTestListItem } from "@platform/shared-types";
import { Button, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { OperationalEmpty, OperationalError } from "@/components/operational/operational-messages";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate, titleCase } from "@/lib/format";

type SavedTestsListPageViewProps = {
  currentUser: AuthUser;
  projectId: string;
  items: SavedStatisticalTestListItem[];
};

export function SavedTestsListPageView({ currentUser, projectId, items }: SavedTestsListPageViewProps) {
  const router = useRouter();
  const [runningId, setRunningId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function runAgain(savedTestId: string) {
    setError(null);
    setRunningId(savedTestId);
    try {
      await apiFetch(`/projects/${projectId}/tests/saved/${savedTestId}/run`, { method: "POST" });
      router.refresh();
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setRunningId(null);
    }
  }

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Testing lab"
      title="Saved statistical tests"
      subtitle="Persisted test definitions and run history. Reruns use the current dataset files and column data."
      actions={
        <Link
          href={`/projects/${projectId}`}
          className="rounded-full border border-line bg-surface px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-ink hover:border-line-strong"
        >
          Back to project
        </Link>
      }
    >
      <SectionPanel
        title="Saved tests"
        description="View, rerun, or open a saved configuration. This is lightweight persistence, not a full experiment platform."
      >
        {error ? (
          <div className="mb-4">
            <OperationalError title="Could not rerun test" message={error} />
          </div>
        ) : null}
        {items.length === 0 ? (
          <OperationalEmpty description="No saved tests yet. Run a statistical test from a dataset comparison, then save the definition to list it here." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] border-collapse text-left text-sm text-ink">
              <thead>
                <tr className="border-b border-line text-xs uppercase tracking-[0.14em] text-muted">
                  <th className="py-2 pr-4 font-medium">Name</th>
                  <th className="py-2 pr-4 font-medium">Type</th>
                  <th className="py-2 pr-4 font-medium">Column</th>
                  <th className="py-2 pr-4 font-medium">Datasets</th>
                  <th className="py-2 pr-4 font-medium">Last run</th>
                  <th className="py-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id} className="border-b border-line">
                    <td className="py-3 pr-4 font-medium text-ink">{row.name}</td>
                    <td className="py-3 pr-4 font-mono text-xs text-ink-2">{titleCase(row.test_type.replace(/_/g, " "))}</td>
                    <td className="py-3 pr-4 font-mono text-xs text-ink-2">{row.column_name}</td>
                    <td className="py-3 pr-4 text-xs text-ink-3">
                      <span className="text-ink-2">{row.left_dataset_name}</span>
                      <span className="mx-1 text-muted">↔</span>
                      <span className="text-ink-2">{row.right_dataset_name}</span>
                    </td>
                    <td className="py-3 pr-4 text-xs text-ink-3">
                      {row.last_run_at ? formatDate(row.last_run_at) : "—"}
                    </td>
                    <td className="py-3">
                      <div className="flex flex-wrap gap-2">
                        <Link
                          href={`/projects/${projectId}/tests/saved/${row.id}`}
                          className="rounded-lg border border-line-strong px-3 py-1.5 text-xs font-medium uppercase tracking-[0.12em] text-ink hover:border-line-strong"
                        >
                          View
                        </Link>
                        <Button
                          variant="secondary"
                          size="sm"
                          disabled={runningId === row.id}
                          onClick={() => void runAgain(row.id)}
                        >
                          {runningId === row.id ? "Running…" : "Run again"}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionPanel>
    </AppShell>
  );
}
