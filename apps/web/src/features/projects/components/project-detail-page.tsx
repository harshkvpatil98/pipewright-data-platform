"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type {
  AuthUser,
  DatasetRecord,
  PipelineRunRecord,
  ProjectDetail,
  StreamSource,
} from "@platform/shared-types";
import { Button, EmptyState, SectionPanel, StatusBadge, buttonClassName } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { Icon } from "@/components/ui/icon";
import { AddDataDialog } from "@/features/datasets/components/add-data-dialog";
import { getPipelineRunSecondaryText } from "@/features/datasets/run-summary";
import { ProjectChecklist } from "@/features/projects/components/project-checklist";
import { ORIGIN_LABELS, groupDatasets, originHints } from "@/lib/dataset-origin";
import { formatDate, formatNumber } from "@/lib/format";
import { formatRunTypeLabel } from "@/lib/run-labels";

type ProjectDetailPageViewProps = {
  currentUser: AuthUser;
  project: ProjectDetail;
  datasets: DatasetRecord[];
  runs: PipelineRunRecord[];
  feeds: StreamSource[];
};

const RECENT = 5;

/**
 * Overview → Overview: the project's home. What to do next (the checklist,
 * until it is done), the data that is here and what ran last. Everything else
 * is one tab or one rail item away, so this page does not try to list it.
 */
export function ProjectDetailPageView({
  currentUser,
  project,
  datasets,
  runs,
  feeds,
}: ProjectDetailPageViewProps) {
  const [uploadOpen, setUploadOpen] = useState(false);
  const base = `/projects/${project.id}`;
  const groups = useMemo(
    () => groupDatasets(datasets, originHints(runs, feeds)),
    [datasets, runs, feeds],
  );
  const failedRuns = runs.filter((run) => run.status === "failed").length;

  return (
    <>
      <AppShell
        currentUser={currentUser}
        title={project.name}
        subtitle={project.description ?? "Bring data in, clean it, check it and share it."}
        actions={
          <>
            <Button onClick={() => setUploadOpen(true)}>
              <Icon name="upload" size={16} />
              Add data
            </Button>
            {datasets.length > 0 ? (
              <Link href={`${base}/studio`} className={buttonClassName("secondary")}>
                Open Studio
              </Link>
            ) : null}
          </>
        }
        meta={project.status !== "active" ? <StatusBadge value={project.status} /> : undefined}
      >
        <ProjectChecklist
          projectId={project.id}
          datasetCount={datasets.length}
          onAddData={() => setUploadOpen(true)}
        />

        <div className="grid gap-5 xl:grid-cols-2">
          <SectionPanel
            title="Data"
            description={
              groups.length > 0
                ? `${groups.length} dataset${groups.length === 1 ? "" : "s"} in this project.`
                : undefined
            }
            actions={
              groups.length > 0 ? (
                <Link href={`${base}/datasets`} className={buttonClassName("secondary", "sm")}>
                  All datasets
                </Link>
              ) : null
            }
          >
            {groups.length === 0 ? (
              <EmptyState
                title="No data yet"
                description="Upload a file, connect a database, or start with sample data."
                action={
                  <Button size="sm" onClick={() => setUploadOpen(true)}>
                    Add data
                  </Button>
                }
              />
            ) : (
              <ul className="divide-y divide-line">
                {groups.slice(0, RECENT).map((group) => (
                  <li key={group.latest.id} className="flex items-center justify-between gap-3 py-2.5">
                    <div className="min-w-0">
                      <Link
                        href={`${base}/datasets/${group.latest.id}`}
                        className="block truncate text-[14px] font-medium text-ink hover:text-[color:var(--accent-muted)]"
                      >
                        {group.name}
                      </Link>
                      <div className="text-[13px] text-ink-3">
                        {ORIGIN_LABELS[group.origin]} · {formatNumber(group.latest.row_count)} rows
                      </div>
                    </div>
                    <span className="shrink-0 text-[13px] text-muted">
                      {formatDate(group.latest.created_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </SectionPanel>

          <SectionPanel
            title="Recent runs"
            description={
              runs.length > 0
                ? failedRuns > 0
                  ? `${failedRuns} of the last ${runs.length} failed.`
                  : "Everything recent finished without a failure."
                : undefined
            }
            actions={
              runs.length > 0 ? (
                <Link href={`${base}/runs`} className={buttonClassName("secondary", "sm")}>
                  All runs
                </Link>
              ) : null
            }
          >
            {runs.length === 0 ? (
              <p className="py-6 text-center text-[14px] text-muted">
                Nothing has run yet. Uploads, imports and recipes appear here when they run.
              </p>
            ) : (
              <ul className="divide-y divide-line">
                {runs.slice(0, RECENT).map((run) => (
                  <li key={run.id} className="flex items-center justify-between gap-3 py-2.5">
                    <div className="min-w-0">
                      <Link
                        href={`${base}/runs/${run.id}/audit`}
                        className="block truncate text-[14px] font-medium text-ink hover:text-[color:var(--accent-muted)]"
                      >
                        {formatRunTypeLabel(run.run_type)}
                      </Link>
                      <div className="truncate text-[13px] text-ink-3">
                        {getPipelineRunSecondaryText(run)}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      <span className="text-[13px] text-muted">
                        {formatDate(run.started_at ?? run.created_at)}
                      </span>
                      <StatusBadge value={run.status} />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </SectionPanel>
        </div>
      </AppShell>

      <AddDataDialog open={uploadOpen} onClose={() => setUploadOpen(false)} projectId={project.id} />
    </>
  );
}
