"use client";

import Link from "next/link";
import { useState } from "react";

import type {
  AuthUser,
  ExecutionVersionPin,
  ReplayResult,
  RunAuditSummary,
} from "@platform/shared-types";
import {
  Badge,
  type BadgeTone,
  Button,
  buttonClassName,
  Modal,
  SectionPanel,
  StatusBadge,
} from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { apiFetch } from "@/lib/api/client";
import { downloadFromApi } from "@/lib/api/download";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDateTime, formatDurationMs } from "@/lib/format";
import { recipeHref } from "@/lib/navigation";
import { formatRunTypeLabel, formatStageLabel } from "@/lib/run-labels";
import { STEP_BY_TYPE } from "@/features/studio/step-catalog";

type RunAuditPageProps = {
  currentUser: AuthUser;
  projectId: string;
  audit: RunAuditSummary;
};

/** Runs whose output lands in another system, so "what it made" is not a dataset version. */
const WRITES_OUTSIDE = new Set([
  "database_copy",
  "dataset_delivery",
  "dataset_publish_postgres",
  "dataset_publish_power_bi",
  "dataset_publish_tableau",
]);

type LogEvent = { stage?: string; message?: string; details?: { error?: unknown; step_type?: unknown } };

/**
 * One run, told in words: who started it, what it read, what it made, and
 * each step it went through. The stored record is still here, behind
 * "Technical details", for whoever has to debug it.
 */
export function RunAuditPageView({ currentUser, projectId, audit }: RunAuditPageProps) {
  const [technicalOpen, setTechnicalOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [replayOpen, setReplayOpen] = useState(false);
  const [replayBusy, setReplayBusy] = useState(false);
  const [replayResult, setReplayResult] = useState<ReplayResult | null>(null);
  const [replayError, setReplayError] = useState<string | null>(null);
  const context = audit.execution_context;
  const names = audit.dataset_names ?? {};
  const datasetName = (id: string) => names[id] ?? "A dataset that has since been deleted";

  const events: LogEvent[] =
    audit.logs_json && Array.isArray((audit.logs_json as { events?: unknown }).events)
      ? (audit.logs_json as { events: LogEvent[] }).events
      : [];
  const who =
    audit.triggered_by_user_id === currentUser.id ? "You" : (audit.triggered_by_name ?? "Someone who has left");
  const took =
    audit.started_at && audit.completed_at
      ? formatDurationMs(new Date(audit.completed_at).getTime() - new Date(audit.started_at).getTime())
      : null;
  const relatedOnly = audit.output_versions.length === 0 ? audit.related_dataset_ids : [];
  const writesOutside = WRITES_OUTSIDE.has(audit.run_type);
  const hasBeforeAfter = audit.run_type === "dataset_transformation" || audit.run_type === "dataset_ingestion";

  async function onReplay() {
    setReplayBusy(true);
    setReplayError(null);
    setReplayResult(null);
    try {
      setReplayResult(
        await apiFetch<ReplayResult>(`/projects/${projectId}/runs/${audit.id}/replay`, { method: "POST" }),
      );
    } catch (error) {
      setReplayError(extractErrorMessage(error));
    } finally {
      setReplayBusy(false);
    }
  }

  async function onDownload() {
    setExporting(true);
    setExportError(null);
    try {
      await downloadFromApi(`/projects/${projectId}/runs/${audit.id}/audit/export?format=html`, `run-${audit.id}.html`);
    } catch (error) {
      setExportError(extractErrorMessage(error));
    } finally {
      setExporting(false);
    }
  }

  return (
    <AppShell
      currentUser={currentUser}
      title={formatRunTypeLabel(audit.run_type)}
      subtitle="What this run did, what it made, and how to check it again."
      actions={
        <>
          {audit.replayable ? (
            <Button
              onClick={() => {
                setReplayOpen(true);
                setReplayResult(null);
                setReplayError(null);
              }}
            >
              Replay
            </Button>
          ) : null}
          <Button variant="secondary" disabled={exporting} onClick={() => void onDownload()}>
            {exporting ? "Preparing…" : "Download a report"}
          </Button>
          {hasBeforeAfter ? (
            <Link href={`/projects/${projectId}/runs/${audit.id}/comparison`} className={buttonClassName("secondary", "md")}>
              Before and after
            </Link>
          ) : null}
        </>
      }
      meta={
        <>
          <StatusBadge value={audit.status} />
          <span className="text-[13px] text-ink-3">{formatDateTime(audit.created_at)}</span>
        </>
      }
    >
      {exportError ? (
        <p role="alert" className="rounded-xl border border-danger-line bg-danger-soft px-3 py-2 text-[13px] text-danger">
          {exportError}
        </p>
      ) : null}

      <SectionPanel title="What happened">
        <ul className="list-inside list-disc space-y-1 text-[14px] text-ink">
          {audit.warnings.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
        <dl className="mt-4 grid gap-3 text-[14px] sm:grid-cols-2 lg:grid-cols-3">
          <Fact label="Started by">{who}</Fact>
          {audit.pipeline_id ? (
            <Fact label="Recipe">
              <Link href={recipeHref(projectId, audit.pipeline_id)} className="text-accent hover:underline">
                {audit.pipeline_name ?? "A recipe that has since been deleted"}
              </Link>
            </Fact>
          ) : null}
          <Fact label="Started">{audit.started_at ? formatDateTime(audit.started_at) : "Did not start"}</Fact>
          <Fact label="Finished">{audit.completed_at ? formatDateTime(audit.completed_at) : "Not yet"}</Fact>
          {took ? <Fact label="Took">{took}</Fact> : null}
        </dl>
        {!audit.replayable && audit.replay_reason && context ? (
          <p className="mt-4 text-[13px] text-ink-3">It cannot be replayed: {audit.replay_reason}</p>
        ) : null}
      </SectionPanel>

      <div className="grid gap-5 lg:grid-cols-2">
        <SectionPanel title="What it made">
          {audit.output_versions.length > 0 ? (
            <ul className="space-y-2 text-[14px]">
              {audit.output_versions.map((version) => (
                <li key={`${version.dataset_id}-${version.version_number}`} className="flex flex-wrap items-center gap-2">
                  <Link href={`/projects/${projectId}/datasets/${version.dataset_id}`} className="text-accent hover:underline">
                    {version.dataset_name ?? datasetName(version.dataset_id)}
                  </Link>
                  <span className="text-ink-3">version {version.version_number}</span>
                  {version.retention_state === "pruned" ? (
                    <Badge title="The rows were removed by the retention policy; the record of the version stays.">
                      Data removed
                    </Badge>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : relatedOnly.length > 0 ? (
            <ul className="space-y-2 text-[14px]">
              {relatedOnly.map((id) => (
                <li key={id}>
                  <Link href={`/projects/${projectId}/datasets/${id}`} className="text-accent hover:underline">
                    {datasetName(id)}
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[14px] text-ink-3">
              {writesOutside
                ? "It wrote outside Pipewright, not to a dataset. The steps below say where."
                : audit.status === "failed"
                  ? "Nothing. It stopped before saving."
                  : "No dataset versions were recorded for it."}
            </p>
          )}
        </SectionPanel>

        <SectionPanel title="What it read">
          {context && context.inputs.length > 0 ? (
            <ul className="space-y-2 text-[14px]">
              {context.inputs.map((pin, index) => (
                <li key={`${pin.dataset_id}-${index}`}>
                  <PinLine projectId={projectId} pin={pin} name={datasetName(pin.dataset_id)} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[14px] text-ink-3">This kind of run does not record what it read.</p>
          )}
        </SectionPanel>
      </div>

      <SectionPanel title="Steps">
        {events.length === 0 ? (
          <p className="text-[14px] text-ink-3">No steps were recorded.</p>
        ) : (
          <ol className="space-y-2 text-[14px]">
            {events.map((event, index) => (
              <li key={`${event.stage}-${index}`} className="rounded-xl border border-line bg-surface px-3 py-2">
                <span className="text-[13px] font-medium text-ink-2">{formatStageLabel(event.stage)}</span>
                <p className="mt-0.5 text-ink">{eventText(event)}</p>
                {typeof event.details?.error === "string" ? (
                  <p className="mt-1 text-danger">{event.details.error}</p>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </SectionPanel>

      <SectionPanel
        title="Technical details"
        description="Identifiers and the stored record, for whoever has to look deeper."
        actions={
          <Button variant="ghost" size="sm" onClick={() => setTechnicalOpen((open) => !open)}>
            {technicalOpen ? "Hide" : "Show"}
          </Button>
        }
      >
        {technicalOpen ? (
          <div className="space-y-4">
            <dl className="grid gap-3 text-[13px] sm:grid-cols-2">
              <Fact label="Run ID" mono>
                {audit.id}
              </Fact>
              {audit.pipeline_id ? (
                <Fact label="Recipe ID" mono>
                  {audit.pipeline_id}
                </Fact>
              ) : null}
              {context ? (
                <>
                  <Fact label="Clock fixed at">{formatDateTime(context.evaluated_at)}</Fact>
                  <Fact label="Engine version" mono>
                    {context.semantic_version}
                  </Fact>
                  <Fact label="Steps fingerprint" mono>
                    {shortDigest(context.steps_digest)}
                  </Fact>
                  {context.replay_of ? (
                    <Fact label="Replay of">
                      <Link href={`/projects/${projectId}/runs/${context.replay_of}/audit`} className="text-accent hover:underline">
                        The original run
                      </Link>
                    </Fact>
                  ) : null}
                </>
              ) : null}
            </dl>
            <Record title="Run record" value={audit.summary_json} />
            <Record title="Step log" value={audit.logs_json} />
          </div>
        ) : (
          <p className="text-[13px] text-ink-3">Hidden until you need it.</p>
        )}
      </SectionPanel>

      <Modal
        open={replayOpen}
        title="Replay this run"
        description="Runs the same steps on the same input versions and checks the result matches. It makes a new run; nothing is changed."
        onClose={() => setReplayOpen(false)}
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setReplayOpen(false)}>
              Close
            </Button>
            <Button size="sm" disabled={replayBusy} onClick={() => void onReplay()}>
              {replayBusy ? "Replaying…" : replayResult ? "Replay again" : "Run the replay"}
            </Button>
          </div>
        }
      >
        {replayError ? (
          <p role="alert" className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-[14px] text-danger">
            {replayError}
          </p>
        ) : replayResult ? (
          <ReplayOutcome projectId={projectId} result={replayResult} datasetName={datasetName} />
        ) : (
          <p className="text-[14px] text-ink-2">
            {context
              ? `It will use the clock as it was at ${formatDateTime(context.evaluated_at)} and the ${context.inputs.length} input version${context.inputs.length === 1 ? "" : "s"} this run read.`
              : "This run did not record enough to replay it."}
          </p>
        )}
      </Modal>
    </AppShell>
  );
}

/** What a step did. A recipe step is named the way the Studio names it, whatever the log stored. */
function eventText(event: LogEvent): string {
  const stepType = typeof event.details?.step_type === "string" ? event.details.step_type : null;
  if (stepType) {
    return stepType === "tool" ? "A tool from the library." : (STEP_BY_TYPE.get(stepType)?.label ?? "A recipe step.");
  }
  return event.message ?? "";
}

function Fact({ label, mono = false, children }: { label: string; mono?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[12px] text-muted">{label}</dt>
      <dd className={mono ? "mt-0.5 break-all font-mono text-[12px] text-ink-2" : "mt-0.5 text-ink"}>{children}</dd>
    </div>
  );
}

function Record({ title, value }: { title: string; value: unknown }) {
  return (
    <div>
      <h3 className="text-[13px] font-medium text-ink-2">{title}</h3>
      <pre className="mt-1.5 max-h-64 overflow-auto rounded-xl border border-line bg-sunken p-3 text-[12px] text-ink-2">
        {value ? JSON.stringify(value, null, 2) : "Nothing recorded"}
      </pre>
    </div>
  );
}

const REPLAY_OUTCOMES: Record<ReplayResult["status"], { label: string; tone: BadgeTone }> = {
  equivalent: { label: "Same result", tone: "success" },
  divergent: { label: "Different result", tone: "danger" },
  incompatible: { label: "Cannot be compared", tone: "warning" },
  unavailable: { label: "Inputs no longer kept", tone: "warning" },
  failed: { label: "The replay failed", tone: "danger" },
  unverifiable: { label: "Cannot be checked", tone: "warning" },
};

function ReplayOutcome({
  projectId,
  result,
  datasetName,
}: {
  projectId: string;
  result: ReplayResult;
  datasetName: (id: string) => string;
}) {
  const outcome = REPLAY_OUTCOMES[result.status];
  return (
    <div className="space-y-3 text-[14px]">
      <div className="flex flex-wrap items-center gap-3">
        <Badge tone={outcome.tone}>{outcome.label}</Badge>
        {result.replay_run_id ? (
          <Link href={`/projects/${projectId}/runs/${result.replay_run_id}/audit`} className="text-[13px] text-accent hover:underline">
            Open the replay
          </Link>
        ) : null}
        {result.replay_dataset_id ? (
          <Link href={`/projects/${projectId}/datasets/${result.replay_dataset_id}`} className="text-[13px] text-accent hover:underline">
            Open what it made
          </Link>
        ) : null}
      </div>
      {result.reason ? <p className="text-ink-2">{result.reason}</p> : null}
      {result.comparison ? (
        <div className="rounded-xl border border-line bg-sunken px-3 py-2.5">
          <div className="grid gap-2 sm:grid-cols-3">
            <Same label="Columns" same={result.comparison.columns_equal} />
            <Same label="Types" same={result.comparison.types_equal} />
            <Same
              label="Rows"
              same={result.comparison.rows_equal}
              note={
                result.comparison.rows_original !== null && result.comparison.rows_replay !== null
                  ? `${result.comparison.rows_original} then ${result.comparison.rows_replay}`
                  : undefined
              }
            />
          </div>
          {result.comparison.differences.length > 0 ? (
            <ul className="mt-2 list-inside list-disc text-[13px] text-ink-2">
              {result.comparison.differences.map((difference) => (
                <li key={difference}>{difference}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      {result.original_output || result.replay_output ? (
        <div className="grid gap-2 text-[13px] sm:grid-cols-2">
          <div>
            <div className="text-muted">The original made</div>
            {result.original_output ? (
              <PinLine projectId={projectId} pin={result.original_output} name={datasetName(result.original_output.dataset_id)} />
            ) : (
              "Nothing"
            )}
          </div>
          <div>
            <div className="text-muted">The replay made</div>
            {result.replay_output ? (
              <PinLine projectId={projectId} pin={result.replay_output} name={datasetName(result.replay_output.dataset_id)} />
            ) : (
              "Nothing"
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Same({ label, same, note }: { label: string; same: boolean; note?: string }) {
  return (
    <div>
      <div className="text-[12px] text-muted">{label}</div>
      <div className={same ? "text-success" : "text-danger"}>
        {same ? "Same" : "Different"}
        {note ? <span className="ml-1 text-muted">({note})</span> : null}
      </div>
    </div>
  );
}

const PIN_ROLES: Record<string, string> = { base: "Input", step: "Joined in" };

function PinLine({ projectId, pin, name }: { projectId: string; pin: ExecutionVersionPin; name: string }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {pin.role && PIN_ROLES[pin.role] ? <Badge>{PIN_ROLES[pin.role]}</Badge> : null}
      <Link href={`/projects/${projectId}/datasets/${pin.dataset_id}`} className="text-accent hover:underline">
        {name}
      </Link>
      <span className="text-ink-3">
        {pin.version_number === null ? "(no version recorded)" : `version ${pin.version_number}`}
      </span>
    </span>
  );
}

function shortDigest(hash: string | null | undefined): string {
  if (!hash) return "None";
  const hex = hash.includes(":") ? hash.split(":")[1] : hash;
  return hex.slice(0, 12);
}
