"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { AuthUser, SavedStatisticalTestListItem } from "@platform/shared-types";
import { Button, buttonClassName, EmptyState, SectionPanel, Table, TableBody, TableCell, TableHead, TableHeaderCell, TableRow } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { DeleteRowButton } from "@/components/ui/delete-row-button";
import { OperationalError } from "@/components/operational/operational-messages";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate, titleCase } from "@/lib/format";

type SavedTestsListPageViewProps = {
  currentUser: AuthUser;
  projectId: string;
  items: SavedStatisticalTestListItem[];
};

export function SavedTestsListPageView({
  currentUser,
  projectId,
  items: initialItems,
}: SavedTestsListPageViewProps) {
  // Held locally so a deleted row leaves the table without a reload.
  const [items, setItems] = useState(initialItems);
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
      title="Comparisons"
      subtitle="Saved statistical comparisons between two datasets, ready to run again."
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
          <EmptyState size="compact"
            title="No comparisons saved yet"
            description="Open a dataset made by a recipe and choose Compare the two, then save the comparison to run it again later."
            action={
              <Link href={`/projects/${projectId}/datasets`} className={buttonClassName("secondary", "sm")}>
                Choose a dataset
              </Link>
            }
          />
        ) : (
          <Table minWidth={640}>
            <TableHead>
              <TableRow className="text-xs text-muted">
                <TableHeaderCell>Name</TableHeaderCell>
                <TableHeaderCell>Type</TableHeaderCell>
                <TableHeaderCell>Column</TableHeaderCell>
                <TableHeaderCell>Datasets</TableHeaderCell>
                <TableHeaderCell>Last run</TableHeaderCell>
                <TableHeaderCell>Actions</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {items.map((row) => (
                <TableRow key={row.id}>
                  <TableCell className="font-medium text-ink">{row.name}</TableCell>
                  <TableCell className="font-mono text-xs text-ink-2">{titleCase(row.test_type.replace(/_/g, " "))}</TableCell>
                  <TableCell className="font-mono text-xs text-ink-2">{row.column_name}</TableCell>
                  <TableCell className="text-xs text-ink-3">
                    <span className="text-ink-2">{row.left_dataset_name}</span>
                    <span className="mx-1 text-muted">↔</span>
                    <span className="text-ink-2">{row.right_dataset_name}</span>
                  </TableCell>
                  <TableCell className="text-xs text-ink-3">
                    {row.last_run_at ? formatDate(row.last_run_at) : "—"}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-2">
                      <Link
                        href={`/projects/${projectId}/tests/saved/${row.id}`}
                        className="rounded-lg border border-line-strong px-3 py-1.5 text-xs font-medium text-ink hover:border-line-strong"
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
                      <DeleteRowButton
                        path={`/projects/${projectId}/tests/saved/${row.id}`}
                        name={row.name}
                        kind="saved test"
                        consequences={["Every recorded run of this test goes with it."]}
                        onDeleted={() =>
                          setItems((current) => current.filter((item) => item.id !== row.id))
                        }
                      />
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </SectionPanel>
    </AppShell>
  );
}
