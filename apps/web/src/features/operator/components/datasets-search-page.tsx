"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import type { AuthUser, OperatorDatasetRow } from "@platform/shared-types";
import { Input, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { OperationalEmpty, OperationalError } from "@/components/operational/operational-messages";
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
      eyebrow="Operate"
      title="Datasets"
      subtitle="Every dataset across the projects you can see. Search by name to find one without knowing its project."
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
          <OperationalEmpty
            title="No datasets found"
            description={query.trim() ? "No dataset matches that name." : "Datasets appear here once you add data to a project."}
          />
        ) : (
          <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] border-collapse text-left text-sm text-ink">
                <thead className="border-b border-line text-xs uppercase tracking-[0.14em] text-muted">
                  <tr>
                    <th className="py-2 pr-3 font-medium">Dataset</th>
                    <th className="py-2 pr-3 font-medium">Project</th>
                    <th className="py-2 pr-3 font-medium">Rows</th>
                    <th className="py-2 pr-3 font-medium">Type</th>
                    <th className="py-2 font-medium">Added</th>
                  </tr>
                </thead>
                <tbody>
                  {datasets.map((dataset) => (
                    <tr key={dataset.id} className="border-b border-line">
                      <td className="py-2 pr-3">
                        <Link
                          href={`/projects/${dataset.project_id}/datasets/${dataset.id}`}
                          className="font-medium text-ink hover:text-accent"
                        >
                          {dataset.name}
                        </Link>
                        {dataset.is_derived ? (
                          <span className="ml-2 rounded bg-surface-2 px-1.5 py-0.5 text-[10px] uppercase text-ink-3">
                            derived
                          </span>
                        ) : null}
                      </td>
                      <td className="py-2 pr-3">
                        <Link
                          href={`/projects/${dataset.project_id}`}
                          className="text-ink-2 hover:text-accent"
                        >
                          {dataset.project_name}
                        </Link>
                      </td>
                      <td className="py-2 pr-3 tabular-nums text-ink-3">
                        {dataset.row_count?.toLocaleString() ?? "—"}
                      </td>
                      <td className="py-2 pr-3 text-ink-3">{dataset.file_type ?? "—"}</td>
                      <td className="py-2 text-xs text-ink-3">{formatDate(dataset.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </SectionPanel>
    </AppShell>
  );
}
