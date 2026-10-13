"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import type { AuthUser, OperatorDatasetRow } from "@platform/shared-types";
import { Badge, Button, buttonClassName, EmptyState, Input, SectionPanel, Table, TableBody, TableCell, TableHead, TableHeaderCell, TableRow } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { OperationalError } from "@/components/operational/operational-messages";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";

type DatasetsSearchPageProps = {
  currentUser: AuthUser;
  initialDatasets: OperatorDatasetRow[];
};

/**
 * Search datasets across every project you can see. The old route redirected
 * into one project; this answers "where is that dataset again?" without knowing
 * which project it lives in.
 */
export function DatasetsSearchPageView({ currentUser, initialDatasets }: DatasetsSearchPageProps) {
  const [datasets, setDatasets] = useState(initialDatasets);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const search = useCallback(async (q: string) => {
    setLoading(true);
    setError(null);
    try {
      const suffix = q.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
      const response = await apiFetch<{ items: OperatorDatasetRow[] }>(`/datasets${suffix}`);
      setDatasets(response.items);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  // Debounce so typing does not fire a request per keystroke.
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const timer = setTimeout(() => void search(query), 300);
    return () => clearTimeout(timer);
  }, [query, search]);

  return (
    <AppShell
      currentUser={currentUser}
      title="Find a dataset"
      subtitle="Search datasets across every project you can open."
    >
      <div className="mb-4 max-w-md">
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search datasets by name…"
          aria-label="Search datasets by name"
        />
      </div>

      {error ? <OperationalError title="Could not load datasets" message={error} /> : null}

      <SectionPanel
        title="Datasets"
        description={
          loading ? "Searching…" : `${datasets.length} dataset${datasets.length === 1 ? "" : "s"}`
        }
      >
        {datasets.length === 0 ? (
          <EmptyState size="compact"
            title="No datasets found"
            description={query.trim() ? "No dataset matches that name." : "Datasets appear here once you add data to a project."}
            action={
              query.trim() ? (
                <Button variant="secondary" size="sm" onClick={() => setQuery("")}>
                  Clear search
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
            <Table edge="panel" minWidth={720}>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Dataset</TableHeaderCell>
                  <TableHeaderCell>Project</TableHeaderCell>
                  <TableHeaderCell>Rows</TableHeaderCell>
                  <TableHeaderCell>Type</TableHeaderCell>
                  <TableHeaderCell>Added</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {datasets.map((dataset) => (
                  <TableRow key={dataset.id}>
                    <TableCell>
                      <Link
                        href={`/projects/${dataset.project_id}/datasets/${dataset.id}`}
                        className="font-medium text-ink hover:text-accent"
                      >
                        {dataset.name}
                      </Link>
                      {dataset.is_derived ? (
                        <Badge className="ml-2">
                          Made by a recipe
                        </Badge>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <Link
                        href={`/projects/${dataset.project_id}`}
                        className="text-ink-2 hover:text-accent"
                      >
                        {dataset.project_name}
                      </Link>
                    </TableCell>
                    <TableCell className="tabular-nums text-ink-3">
                      {dataset.row_count?.toLocaleString() ?? "—"}
                    </TableCell>
                    <TableCell className="text-ink-3">{dataset.file_type ?? "—"}</TableCell>
                    <TableCell className="text-xs text-ink-3">{formatDate(dataset.created_at)}</TableCell>
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
