"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type { AuthUser, DatasetRecord, PipelineRunRecord, StreamSource } from "@platform/shared-types";
import {
  Button,
  EmptyState,
  Icon,
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
import { AddDataDialog } from "@/features/datasets/components/add-data-dialog";
import {
  ORIGIN_LABELS,
  groupDatasets,
  originHints,
  type DatasetGroup,
  type DatasetOrigin,
} from "@/lib/dataset-origin";
import { formatDate, formatNumber } from "@/lib/format";
import { cx } from "@/lib/utils";

type DatasetsListPageProps = {
  currentUser: AuthUser;
  projectId: string;
  datasets: DatasetRecord[];
  runs: PipelineRunRecord[];
  feeds: StreamSource[];
};

const FILTERS: { id: DatasetOrigin | "all"; label: string }[] = [
  { id: "all", label: "All" },
  { id: "upload", label: "Uploaded files" },
  { id: "database", label: "Database imports" },
  { id: "recipe", label: "Made by recipes" },
  { id: "feed", label: "Live feeds" },
];

/**
 * Data → Datasets: every table in the project, one row per name. Repeated
 * loads of the same table are folded under it (see `lib/dataset-origin.ts`),
 * so "Orders" appears once with how often it has been loaded.
 */
export function DatasetsListPageView({
  currentUser,
  projectId,
  datasets,
  runs,
  feeds,
}: DatasetsListPageProps) {
  const [uploadOpen, setUploadOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<DatasetOrigin | "all">("all");
  const [expanded, setExpanded] = useState<string | null>(null);

  const groups = useMemo(
    () => groupDatasets(datasets, originHints(runs, feeds)),
    [datasets, runs, feeds],
  );
  const counts = useMemo(() => {
    const result: Record<string, number> = { all: groups.length };
    for (const group of groups) result[group.origin] = (result[group.origin] ?? 0) + 1;
    return result;
  }, [groups]);
  const visible = groups.filter(
    (group) =>
      (filter === "all" || group.origin === filter) &&
      group.name.toLowerCase().includes(query.trim().toLowerCase()),
  );

  const actions = (
    <Button onClick={() => setUploadOpen(true)}>
      <Icon name="plus" size={16} />
      Add data
    </Button>
  );

  return (
    <>
      <AppShell
        currentUser={currentUser}
        title="Datasets"
        subtitle="Every table of data in this project, newest first."
        actions={groups.length > 0 ? actions : undefined}
      >
        {groups.length === 0 ? (
          <EmptyState
            title="No data in this project yet"
            description="Upload a file, connect a database, or start with sample data. It appears here."
            action={<div className="flex flex-wrap justify-center gap-2">{actions}</div>}
          />
        ) : (
          <SectionPanel
            title={`${visible.length} of ${groups.length} dataset${groups.length === 1 ? "" : "s"}`}
            actions={
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Find by name"
                aria-label="Find a dataset by name"
                className="h-9 w-56 rounded-lg border border-line bg-sunken px-3 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)]"
              />
            }
            contentClassName="px-0 py-0"
          >
            <div className="flex flex-wrap gap-1.5 border-b border-line px-5 py-3 lg:px-6">
              {FILTERS.filter((option) => option.id === "all" || counts[option.id]).map((option) => (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => setFilter(option.id)}
                  aria-pressed={filter === option.id}
                  className={cx(
                    "rounded-full border px-3 py-1 text-[13px] transition",
                    filter === option.id
                      ? "border-[color:var(--accent)] bg-[color:var(--accent-faint)] text-ink"
                      : "border-line text-ink-3 hover:text-ink",
                  )}
                >
                  {option.label}
                  <span className="ml-1.5 text-muted">{counts[option.id] ?? 0}</span>
                </button>
              ))}
            </div>
            {visible.length === 0 ? (
              <p className="px-6 py-10 text-center text-[14px] text-muted">
                Nothing matches. Clear the search or pick another filter.
              </p>
            ) : (
              <Table edge="panel">
                <TableHead>
                  <TableRow>
                    <TableHeaderCell>Name</TableHeaderCell>
                    <TableHeaderCell>Came from</TableHeaderCell>
                    <TableHeaderCell className="text-right">Rows</TableHeaderCell>
                    <TableHeaderCell className="text-right">Columns</TableHeaderCell>
                    <TableHeaderCell>Last loaded</TableHeaderCell>
                    <TableHeaderCell>
                      <span className="sr-only">Loads</span>
                    </TableHeaderCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {visible.map((group) => (
                    <DatasetRow
                      key={group.latest.id}
                      group={group}
                      projectId={projectId}
                      open={expanded === group.latest.id}
                      onToggle={() =>
                        setExpanded((current) =>
                          current === group.latest.id ? null : group.latest.id,
                        )
                      }
                    />
                  ))}
                </TableBody>
              </Table>
            )}
          </SectionPanel>
        )}
      </AppShell>
      <AddDataDialog open={uploadOpen} onClose={() => setUploadOpen(false)} projectId={projectId} />
    </>
  );
}

function DatasetRow({
  group,
  projectId,
  open,
  onToggle,
}: {
  group: DatasetGroup;
  projectId: string;
  open: boolean;
  onToggle: () => void;
}) {
  const { latest, versions } = group;
  const failed = latest.ingestion_status === "failed" || latest.status === "failed";
  return (
    <>
      <TableRow>
        <TableCell>
          <Link
            href={`/projects/${projectId}/datasets/${latest.id}`}
            className="font-medium text-ink hover:text-[color:var(--accent-muted)]"
          >
            {group.name}
          </Link>
          {failed ? <StatusBadge value="failed" className="ml-2" /> : null}
        </TableCell>
        <TableCell className="text-ink-2">{ORIGIN_LABELS[group.origin]}</TableCell>
        <TableCell className="text-right tabular-nums text-ink-2">{formatNumber(latest.row_count)}</TableCell>
        <TableCell className="text-right tabular-nums text-ink-2">
          {formatNumber(latest.column_count)}
        </TableCell>
        <TableCell className="text-ink-3">{formatDate(latest.created_at)}</TableCell>
        <TableCell className="text-right">
          {versions.length > 1 ? (
            <button
              type="button"
              onClick={onToggle}
              aria-expanded={open}
              className="inline-flex items-center gap-1 whitespace-nowrap text-[13px] text-ink-3 transition hover:text-ink"
            >
              {versions.length} {group.origin === "recipe" ? "runs" : "loads"}
              <Icon name={open ? "chevronDown" : "chevronRight"} size={13} />
            </button>
          ) : null}
        </TableCell>
      </TableRow>
      {open
        ? versions.slice(1).map((record) => (
            <TableRow key={record.id} className="bg-sunken text-[13px]">
              <TableCell className="!pl-10 lg:!pl-11">
                <Link
                  href={`/projects/${projectId}/datasets/${record.id}`}
                  className="text-ink-2 hover:text-ink"
                >
                  Earlier load
                </Link>
              </TableCell>
              <TableCell className="text-ink-3">{ORIGIN_LABELS[group.origin]}</TableCell>
              <TableCell className="text-right tabular-nums text-ink-3">
                {formatNumber(record.row_count)}
              </TableCell>
              <TableCell className="text-right tabular-nums text-ink-3">
                {formatNumber(record.column_count)}
              </TableCell>
              <TableCell className="text-ink-3">{formatDate(record.created_at)}</TableCell>
              <TableCell />
            </TableRow>
          ))
        : null}
    </>
  );
}
