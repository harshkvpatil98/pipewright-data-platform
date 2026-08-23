"use client";

import Link from "next/link";
import { useCallback, useState } from "react";

import type { AuthUser, ColumnTrace, DatasetLineage } from "@platform/shared-types";
import { Button, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";

import { ImpactDialog } from "./impact-dialog";
import { LineageGraph } from "./lineage-graph";

type LineagePageProps = {
  currentUser: AuthUser;
  projectId: string;
  datasetId: string;
  initial: DatasetLineage;
};

export function LineagePageView({
  currentUser,
  projectId,
  datasetId,
  initial,
}: LineagePageProps) {
  const [selected, setSelected] = useState<string[]>([]);
  const [trace, setTrace] = useState<ColumnTrace | null>(null);
  const [showImpact, setShowImpact] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = useCallback((column: string) => {
    setSelected((current) =>
      current.includes(column)
        ? current.filter((name) => name !== column)
        : [...current, column],
    );
  }, []);

  const loadTrace = useCallback(
    async (column: string) => {
      setError(null);
      try {
        setTrace(
          await apiFetch<ColumnTrace>(
            `/projects/${projectId}/datasets/${datasetId}/lineage/columns/${encodeURIComponent(column)}`,
          ),
        );
      } catch (caught) {
        setError(extractErrorMessage(caught));
      }
    },
    [projectId, datasetId],
  );

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Trust"
      title={`Lineage · ${initial.dataset_name}`}
      subtitle="Where every column came from, and what would break if it changed. Derived from the pipeline definitions rather than stored, so it cannot go stale."
    >
      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <Link
          href={`/projects/${projectId}/datasets/${datasetId}`}
          className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1.5 text-[12px] text-ink-2 transition hover:bg-surface-2"
        >
          <Icon name="chevronLeft" size={12} />
          Dataset
        </Link>
        <Link
          href={`/projects/${projectId}/datasets/${datasetId}/metrics`}
          className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1.5 text-[12px] text-ink-2 transition hover:bg-surface-2"
        >
          <Icon name="activity" size={12} />
          Metrics
        </Link>
      </div>

      <SectionPanel
        title="How this dataset came to exist"
        description="Upstream to the left, downstream to the right. Dashed edges are joins and unions — a second input rather than the main one."
      >
        <LineageGraph lineage={initial} />
        {initial.notes.length > 0 ? (
          <ul className="mt-3 space-y-1">
            {initial.notes.map((note) => (
              <li key={note} className="flex items-start gap-1.5 text-[11.5px] text-muted">
                <Icon name="info" size={11} className="mt-0.5 shrink-0" />
                {note}
              </li>
            ))}
          </ul>
        ) : null}
      </SectionPanel>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <SectionPanel
          title="Columns"
          description="Select one or more, then check what depends on them before you change anything."
          actions={
            <Button
              variant="secondary"
              disabled={selected.length === 0}
              onClick={() => setShowImpact(true)}
            >
              Check impact{selected.length > 0 ? ` (${selected.length})` : ""}
            </Button>
          }
        >
          <ul className="divide-y divide-line">
            {initial.columns.map((column) => (
              <li key={column.column} className="flex items-center gap-3 py-2">
                <input
                  type="checkbox"
                  id={`column-${column.column}`}
                  checked={selected.includes(column.column)}
                  onChange={() => toggle(column.column)}
                  className="h-3.5 w-3.5 shrink-0 accent-[color:var(--accent)]"
                />
                <label
                  htmlFor={`column-${column.column}`}
                  className="min-w-0 flex-1 cursor-pointer"
                >
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[12.5px] text-ink">{column.column}</span>
                    <span
                      className={cx(
                        "rounded px-1.5 py-0.5 text-[10px]",
                        column.derived
                          ? "bg-accent-soft text-accent"
                          : "bg-surface-2 text-ink-3",
                      )}
                    >
                      {column.derived ? "derived" : "source"}
                    </span>
                  </div>
                  {column.origins.length > 0 ? (
                    <div className="mt-0.5 truncate text-[11px] text-muted">
                      from{" "}
                      {column.origins
                        .map((origin) =>
                          origin.dataset_name
                            ? `${origin.column} · ${origin.dataset_name}`
                            : origin.column,
                        )
                        .join(", ")}
                    </div>
                  ) : null}
                </label>
                <button
                  type="button"
                  onClick={() => void loadTrace(column.column)}
                  className="shrink-0 rounded-lg border border-line px-2 py-1 text-[11px] text-ink-3 transition hover:text-ink"
                >
                  Trace
                </button>
              </li>
            ))}
          </ul>
        </SectionPanel>

        <SectionPanel title="Trace" description="Follow one column back through every step.">
          {!trace ? (
            <p className="text-[12.5px] text-muted">
              Pick a column and choose <span className="text-ink-2">Trace</span> to see each
              step it passed through.
            </p>
          ) : (
            <>
              <p className="rounded-lg border border-line bg-surface px-3 py-2.5 text-[12.5px] text-ink">
                {trace.summary}
              </p>
              {trace.edges.length > 0 ? (
                <ol className="mt-3 space-y-2">
                  {trace.edges
                    .slice()
                    .sort((a, b) => a.step_index - b.step_index)
                    .map((edge, index) => (
                      <li
                        key={`${edge.step_index}-${edge.to_column}-${index}`}
                        className="rounded-lg border border-line px-2.5 py-2 text-[11.5px]"
                      >
                        <div className="text-ink-2">
                          Step {edge.step_index + 1} · {edge.step_type.replace(/_/g, " ")}
                        </div>
                        <div className="mt-0.5 font-mono text-[11px] text-muted">
                          {edge.from_column ?? "(literal)"} → {edge.to_column}
                          <span className="ml-1.5 text-muted">{edge.kind}</span>
                        </div>
                      </li>
                    ))}
                </ol>
              ) : (
                <p className="mt-3 text-[11.5px] text-muted">
                  No step touched this column; it is carried straight through.
                </p>
              )}
            </>
          )}
        </SectionPanel>
      </div>

      {showImpact ? (
        <ImpactDialog
          projectId={projectId}
          datasetId={datasetId}
          columns={selected}
          onClose={() => setShowImpact(false)}
        />
      ) : null}
    </AppShell>
  );
}
