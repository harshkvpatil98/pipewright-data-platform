"use client";

import Link from "next/link";
import { useState } from "react";

import type {
  AuthUser,
  ExecutionVersionPin,
  ReplayResult,
  RunAuditSummary,
} from "@platform/shared-types";
import { Button, SectionPanel, StatusBadge } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { Modal } from "@/components/ui/modal";
import { apiFetch } from "@/lib/api/client";
import { downloadFromApi } from "@/lib/api/download";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { formatRunTypeLabel } from "@/lib/run-labels";

type RunAuditPageProps = {
  currentUser: AuthUser;
  projectId: string;
  audit: RunAuditSummary;
};

export function RunAuditPageView({ currentUser, projectId, audit }: RunAuditPageProps) {
  const [rawOpen, setRawOpen] = useState(false);
  const [exportingHtml, setExportingHtml] = useState(false);
  const [replayOpen, setReplayOpen] = useState(false);
  const [replayBusy, setReplayBusy] = useState(false);
  const [replayResult, setReplayResult] = useState<ReplayResult | null>(null);
  const [replayError, setReplayError] = useState<string | null>(null);
  const h = audit.highlights;
  const context = audit.execution_context;

  async function onReplay() {
    setReplayBusy(true);
    setReplayError(null);
    setReplayResult(null);
    try {
      setReplayResult(
        await apiFetch<ReplayResult>(`/projects/${projectId}/runs/${audit.id}/replay`, {
          method: "POST",
        }),
      );
    } catch (error) {
      setReplayError(extractErrorMessage(error));
    } finally {
      setReplayBusy(false);
    }
  }
  const events =
    audit.logs_json && Array.isArray((audit.logs_json as { events?: unknown }).events)
      ? ((audit.logs_json as { events: { stage?: string; message?: string }[] }).events)
      : [];

  async function onDownloadHtml() {
    try {
      setExportingHtml(true);
      await downloadFromApi(
        `/projects/${projectId}/runs/${audit.id}/audit/export?format=html`,
        `run-audit-${audit.id}.html`,
      );
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Download failed.");
    } finally {
      setExportingHtml(false);
    }
  }

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Pipeline run audit"
      title={`Run ${audit.id.slice(0, 8)}…`}
      subtitle="Read-only summary from persisted run, summary_json, and logs_json."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {audit.replayable ? (
            <Button
              variant="primary"
              onClick={() => {
                setReplayOpen(true);
                setReplayResult(null);
                setReplayError(null);
              }}
            >
              Replay
            </Button>
          ) : audit.replay_reason && audit.execution_context ? (
            <span
              className="rounded-full border border-line bg-surface px-3 py-2 text-xs text-muted"
              title={audit.replay_reason}
            >
              Not replayable
            </span>
          ) : null}
          <Button variant="secondary" disabled={exportingHtml} onClick={() => void onDownloadHtml()}>
            {exportingHtml ? "Preparing…" : "Download HTML"}
          </Button>
          <Link
            href={`/projects/${projectId}/runs/${audit.id}/comparison`}
            className="rounded-full border border-line bg-surface px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-ink hover:border-line-strong"
          >
            View comparison
          </Link>
          <Link
            href={`/projects/${projectId}`}
            className="rounded-full border border-line bg-surface px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-ink hover:border-line-strong"
          >
            Project
          </Link>
        </div>
      }
      meta={
        <>
          <StatusBadge value={audit.status} />
          <span className="rounded-full border border-line bg-surface px-3 py-1 text-xs uppercase tracking-[0.18em] text-ink-2">
            {formatRunTypeLabel(audit.run_type)}
          </span>
        </>
      }
    >
      <SectionPanel title="Audit notes" description="Derived from run status, summary, and logs.">
        <ul className="list-inside list-disc space-y-1 text-sm text-ink">
          {audit.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      </SectionPanel>

      <div className="grid gap-6 lg:grid-cols-2">
        <SectionPanel title="Run identity" description="Core fields from pipeline_runs.">
          <dl className="grid gap-3 text-sm">
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Run id</dt>
              <dd className="mt-1 font-mono text-xs text-ink-2 break-all">{audit.id}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Triggered by</dt>
              <dd className="mt-1 font-mono text-xs text-ink-2">
                {audit.triggered_by_user_id}
                {audit.triggered_by_user_id === currentUser.id ? " (you)" : ""}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Pipeline id</dt>
              <dd className="mt-1 text-ink">
                {audit.pipeline_id ? (
                  <Link
                    href={`/projects/${projectId}/pipelines/${audit.pipeline_id}`}
                    className="text-accent hover:text-accent"
                  >
                    {audit.pipeline_id}
                  </Link>
                ) : (
                  "—"
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Created</dt>
              <dd className="mt-1 text-ink">{formatDate(audit.created_at)}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Started / completed</dt>
              <dd className="mt-1 text-ink">
                {audit.started_at ? formatDate(audit.started_at) : "—"} →{" "}
                {audit.completed_at ? formatDate(audit.completed_at) : "—"}
              </dd>
            </div>
          </dl>
        </SectionPanel>

        <SectionPanel title="Audit highlights" description="Inferred from summary_json and logs.">
          <dl className="grid gap-3 text-sm">
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Logged stages</dt>
              <dd className="mt-1 text-ink">{h.stage_count}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Failed stage</dt>
              <dd className="mt-1 text-ink">{h.failed_stage ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Derived dataset created</dt>
              <dd className="mt-1 text-ink">{h.derived_dataset_created ? "Yes" : "No"}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Ingestion / transformation</dt>
              <dd className="mt-1 text-ink">
                {[h.ingestion_type, h.transformation_type].filter(Boolean).join(" · ") || "—"}
              </dd>
            </div>
          </dl>
        </SectionPanel>
      </div>

      <SectionPanel
        title="Published versions"
        description="The output pin: the exact version this run produced. A later run on the same dataset advances the head, not this."
      >
        {audit.output_versions.length === 0 ? (
          <p className="text-sm text-ink-3">
            This run published no dataset version (it failed, or predates version history).
          </p>
        ) : (
          <ul className="space-y-2 text-sm">
            {audit.output_versions.map((version) => (
              <li key={`${version.dataset_id}-${version.version_number}`} className="flex flex-wrap items-center gap-2">
                <Link
                  href={`/projects/${projectId}/datasets/${version.dataset_id}`}
                  className="text-accent hover:text-accent"
                >
                  {version.dataset_name ?? `Dataset ${version.dataset_id.slice(0, 8)}…`}
                </Link>
                <span className="text-ink-2">version {version.version_number}</span>
                <span className="font-mono text-[11px] text-muted">{shortDigest(version.content_hash)}</span>
                {version.retention_state === "pruned" ? (
                  <span className="rounded-full border border-line bg-sunken px-1.5 py-0.5 text-[10px] text-muted">
                    pruned
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </SectionPanel>

      {context ? (
        <SectionPanel
          title="Execution context"
          description="Recorded so this run can be replayed the same way: the instant every clock-dependent function saw, the engine's semantic version, the exact steps, and the input versions read."
        >
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Evaluated at</dt>
              <dd className="mt-1 text-ink">
                {formatDate(context.evaluated_at)} <span className="text-muted">({context.timezone})</span>
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Engine semantics</dt>
              <dd className="mt-1 font-mono text-xs text-ink-2">{context.semantic_version}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Steps</dt>
              <dd className="mt-1 text-ink">
                {context.steps.length} step{context.steps.length === 1 ? "" : "s"}{" "}
                <span className="font-mono text-[11px] text-muted">{shortDigest(context.steps_digest)}</span>
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Clock-dependent functions</dt>
              <dd className="mt-1 text-ink-2">{context.clock_functions.join(", ")}</dd>
            </div>
            {context.replay_of ? (
              <div className="sm:col-span-2">
                <dt className="text-xs uppercase tracking-[0.18em] text-muted">Replay of</dt>
                <dd className="mt-1">
                  <Link
                    href={`/projects/${projectId}/runs/${context.replay_of}/audit`}
                    className="font-mono text-xs text-accent hover:text-accent"
                  >
                    {context.replay_of}
                  </Link>
                </dd>
              </div>
            ) : null}
          </dl>
          <div className="mt-4">
            <div className="text-xs uppercase tracking-[0.18em] text-muted">Input pins</div>
            {context.inputs.length === 0 ? (
              <p className="mt-1 text-sm text-ink-3">No inputs were recorded.</p>
            ) : (
              <ul className="mt-1 space-y-1 text-sm">
                {context.inputs.map((pin, index) => (
                  <li key={`${pin.dataset_id}-${index}`}>
                    <PinLine projectId={projectId} pin={pin} />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </SectionPanel>
      ) : null}

      <SectionPanel
        title="Related datasets"
        description="Ids extracted from summary_json when present (ingestion or transformation runs)."
      >
        {audit.related_dataset_ids.length === 0 ? (
          <p className="text-sm text-ink-3">No related dataset ids found in summary metadata.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {audit.related_dataset_ids.map((id) => (
              <li key={id}>
                <Link href={`/projects/${projectId}/datasets/${id}/audit`} className="text-accent hover:text-accent">
                  Dataset {id}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </SectionPanel>

      <SectionPanel title="Stage / log overview" description="Latest persisted log events (stage + message).">
        {events.length === 0 ? (
          <p className="text-sm text-ink-3">No log events in logs_json.</p>
        ) : (
          <ol className="space-y-2 text-sm">
            {events.map((ev, idx) => (
              <li key={`${ev.stage}-${idx}`} className="rounded-xl border border-line bg-surface px-3 py-2">
                <span className="text-xs uppercase tracking-[0.16em] text-muted">{ev.stage ?? "event"}</span>
                <p className="mt-1 text-ink">{ev.message ?? "—"}</p>
              </li>
            ))}
          </ol>
        )}
      </SectionPanel>

      <SectionPanel title="Technical details" description="Raw summary and logs for debugging (secondary).">
        <button
          type="button"
          onClick={() => setRawOpen(!rawOpen)}
          className="text-sm text-accent hover:text-accent"
        >
          {rawOpen ? "Hide raw metadata" : "Show raw metadata"}
        </button>
        {rawOpen ? (
          <div className="mt-4 space-y-4">
            <div>
              <h4 className="text-xs uppercase tracking-[0.18em] text-muted">summary_json</h4>
              <pre className="mt-2 max-h-64 overflow-auto rounded-xl border border-line bg-sunken p-3 text-xs text-ink-2">
                {audit.summary_json ? JSON.stringify(audit.summary_json, null, 2) : "null"}
              </pre>
            </div>
            <div>
              <h4 className="text-xs uppercase tracking-[0.18em] text-muted">logs_json</h4>
              <pre className="mt-2 max-h-64 overflow-auto rounded-xl border border-line bg-sunken p-3 text-xs text-ink-2">
                {audit.logs_json ? JSON.stringify(audit.logs_json, null, 2) : "null"}
              </pre>
            </div>
          </div>
        ) : null}
      </SectionPanel>
      <Modal
        open={replayOpen}
        title="Replay this run"
        description="Re-executes the recorded steps against the input versions this run pinned, at the instant it froze — then compares the result with the version it published. The replay is a new run and publishes a new dataset; nothing here is rewritten."
        onClose={() => setReplayOpen(false)}
        widthClassName="max-w-2xl"
        footer={
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setReplayOpen(false)}>
              Close
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={replayBusy}
              onClick={() => void onReplay()}
            >
              {replayBusy ? "Replaying…" : replayResult ? "Replay again" : "Run the replay"}
            </Button>
          </div>
        }
      >
        {replayError ? (
          <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
            {replayError}
          </div>
        ) : replayResult ? (
          <ReplayOutcome projectId={projectId} result={replayResult} />
        ) : (
          <p className="text-[12.5px] text-ink-2">
            {context
              ? `Evaluated at ${formatDate(context.evaluated_at)} against ${context.inputs.length} pinned input${context.inputs.length === 1 ? "" : "s"}.`
              : "No execution context is recorded for this run."}
          </p>
        )}
      </Modal>
    </AppShell>
  );
}

const REPLAY_STATUS_COPY: Record<ReplayResult["status"], { label: string; tone: string }> = {
  equivalent: { label: "Equivalent", tone: "border-success-line bg-success-soft text-success" },
  divergent: { label: "Divergent", tone: "border-danger-line bg-danger-soft text-danger" },
  incompatible: { label: "Incompatible", tone: "border-warning-line bg-warning-soft text-warning" },
  unavailable: { label: "Unavailable", tone: "border-warning-line bg-warning-soft text-warning" },
  failed: { label: "Failed", tone: "border-danger-line bg-danger-soft text-danger" },
  unverifiable: { label: "Unverifiable", tone: "border-warning-line bg-warning-soft text-warning" },
};

function ReplayOutcome({ projectId, result }: { projectId: string; result: ReplayResult }) {
  const copy = REPLAY_STATUS_COPY[result.status];
  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full border px-2.5 py-1 text-xs font-medium ${copy.tone}`}>
          {copy.label}
        </span>
        {result.replay_run_id ? (
          <Link
            href={`/projects/${projectId}/runs/${result.replay_run_id}/audit`}
            className="text-xs text-accent hover:text-accent"
          >
            Open the replay run
          </Link>
        ) : null}
        {result.replay_dataset_id ? (
          <Link
            href={`/projects/${projectId}/datasets/${result.replay_dataset_id}`}
            className="text-xs text-accent hover:text-accent"
          >
            Open the replayed dataset
          </Link>
        ) : null}
      </div>
      {result.reason ? <p className="text-ink-2">{result.reason}</p> : null}
      {result.comparison ? (
        <div className="rounded-xl border border-line bg-sunken px-3 py-2.5">
          <div className="grid gap-2 sm:grid-cols-3">
            <Check label="Columns" ok={result.comparison.columns_equal} />
            <Check label="Types" ok={result.comparison.types_equal} />
            <Check
              label="Rows"
              ok={result.comparison.rows_equal}
              note={
                result.comparison.rows_original !== null && result.comparison.rows_replay !== null
                  ? `${result.comparison.rows_original} → ${result.comparison.rows_replay}`
                  : undefined
              }
            />
          </div>
          {result.comparison.differences.length > 0 ? (
            <ul className="mt-2 list-inside list-disc text-[12px] text-ink-2">
              {result.comparison.differences.map((difference) => (
                <li key={difference}>{difference}</li>
              ))}
            </ul>
          ) : null}
          <p className="mt-2 text-[10.5px] text-muted">{result.comparison.method}.</p>
        </div>
      ) : null}
      {result.original_output || result.replay_output ? (
        <div className="grid gap-2 text-[12px] sm:grid-cols-2">
          <div>
            <div className="text-[10.5px] uppercase tracking-[0.14em] text-muted">Original output</div>
            {result.original_output ? <PinLine projectId={projectId} pin={result.original_output} /> : "—"}
          </div>
          <div>
            <div className="text-[10.5px] uppercase tracking-[0.14em] text-muted">Replay output</div>
            {result.replay_output ? <PinLine projectId={projectId} pin={result.replay_output} /> : "—"}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Check({ label, ok, note }: { label: string; ok: boolean; note?: string }) {
  return (
    <div>
      <div className="text-[10.5px] uppercase tracking-[0.14em] text-muted">{label}</div>
      <div className={ok ? "text-success" : "text-danger"}>
        {ok ? "same" : "differ"}
        {note ? <span className="ml-1 text-muted">({note})</span> : null}
      </div>
    </div>
  );
}

function PinLine({ projectId, pin }: { projectId: string; pin: ExecutionVersionPin }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {pin.role && pin.role !== "output" ? (
        <span className="rounded-full border border-line bg-sunken px-1.5 py-0.5 text-[10px] text-muted">
          {pin.role}
        </span>
      ) : null}
      <Link
        href={`/projects/${projectId}/datasets/${pin.dataset_id}`}
        className="font-mono text-xs text-accent hover:text-accent"
      >
        {pin.dataset_id.slice(0, 8)}…
      </Link>
      <span className="text-ink-2">
        {pin.version_number === null ? "no recorded version" : `version ${pin.version_number}`}
      </span>
      <span className="font-mono text-[11px] text-muted">{shortDigest(pin.content_hash)}</span>
    </span>
  );
}

function shortDigest(hash: string | null | undefined): string {
  if (!hash) return "--";
  const hex = hash.includes(":") ? hash.split(":")[1] : hash;
  return hex.slice(0, 12);
}
