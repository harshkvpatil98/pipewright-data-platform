"use client";

import { useCallback, useEffect, useState } from "react";

import type {
  AuthUser,
  ConnectorSweepReport,
  ConnectorWatchStatus,
  DriftSeverity,
  SchemaDriftEvent,
} from "@platform/shared-types";
import { Button, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { cx } from "@/lib/utils";

type SchemaDriftPageProps = {
  currentUser: AuthUser;
  projectId: string;
  initialEvents: SchemaDriftEvent[];
};

const SEVERITY_TONE: Record<DriftSeverity, string> = {
  breaking: "border-danger-line bg-danger-soft text-danger",
  risky: "border-warning-line bg-warning-soft text-warning",
  compatible: "border-success-line bg-success-soft text-success",
  none: "border-line bg-surface-2 text-ink-2",
};

const SEVERITY_HELP: Record<DriftSeverity, string> = {
  breaking: "A column was removed or changed to an incompatible type. Downstream steps will break.",
  risky: "A type widened or narrowed. Usually still works, but results can change silently.",
  compatible: "New columns only. Existing consumers are unaffected.",
  none: "No structural change.",
};

export function SchemaDriftPageView({
  currentUser,
  projectId,
  initialEvents,
}: SchemaDriftPageProps) {
  const [events, setEvents] = useState(initialEvents);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const acknowledge = useCallback(
    async (eventId: string) => {
      setBusy(eventId);
      setError(null);
      try {
        const updated = await apiFetch<SchemaDriftEvent>(
          `/projects/${projectId}/schema-drift/events/${eventId}/acknowledge`,
          { method: "POST" },
        );
        setEvents((current) =>
          current.map((event) => (event.id === eventId ? updated : event)),
        );
      } catch (caught) {
        setError(extractErrorMessage(caught));
      } finally {
        setBusy(null);
      }
    },
    [projectId],
  );

  const unacknowledged = events.filter((event) => !event.acknowledged);

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Govern"
      title="Schema drift"
      subtitle="Every extraction compares the incoming schema against the last one it produced. Structural changes are recorded here before they reach downstream pipelines."
    >
      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-3">
        {(
          [
            ["Unacknowledged", unacknowledged.length],
            ["Breaking", events.filter((e) => e.severity === "breaking" && !e.acknowledged).length],
            ["Total recorded", events.length],
          ] as const
        ).map(([label, value]) => (
          <div key={label} className="rounded-2xl border border-line bg-[color:var(--panel)] px-5 py-4">
            <div className="text-[11px] uppercase tracking-[0.2em] text-muted">{label}</div>
            <div className="mt-2 text-3xl font-semibold tabular tracking-tight text-ink">{value}</div>
          </div>
        ))}
      </div>

      <SectionPanel
        title="Drift events"
        description="Newest first. Acknowledging an event keeps it in history but clears it from the outstanding count."
      >
        {events.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-line px-4 py-10 text-center text-sm text-muted">
            No schema drift detected yet. Events appear here after an extraction job runs a second
            time with a changed source schema.
          </p>
        ) : (
          <div className="space-y-3">
            {events.map((event) => (
              <article
                key={event.id}
                className={cx(
                  "rounded-2xl border px-4 py-4 transition duration-[var(--duration-base)]",
                  event.acknowledged
                    ? "border-line bg-surface opacity-70"
                    : "border-line bg-surface",
                )}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={cx(
                          "rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.18em]",
                          SEVERITY_TONE[event.severity],
                        )}
                      >
                        {event.severity}
                      </span>
                      <h3 className="text-sm font-semibold text-ink">{event.summary}</h3>
                    </div>
                    <p className="mt-1 text-xs text-muted">
                      {formatDate(event.created_at)}
                      {event.extraction_job_id ? " · detected during extraction" : ""}
                    </p>
                    <p className="mt-2 text-xs text-ink-3">{SEVERITY_HELP[event.severity]}</p>

                    <div className="mt-3 flex flex-wrap gap-4 text-xs">
                      {event.added_columns && event.added_columns.length > 0 ? (
                        <div>
                          <div className="text-[10px] uppercase tracking-[0.16em] text-success">
                            Added
                          </div>
                          <div className="mt-1 font-mono text-ink-2">
                            {event.added_columns.join(", ")}
                          </div>
                        </div>
                      ) : null}
                      {event.removed_columns && event.removed_columns.length > 0 ? (
                        <div>
                          <div className="text-[10px] uppercase tracking-[0.16em] text-danger">
                            Removed
                          </div>
                          <div className="mt-1 font-mono text-ink-2">
                            {event.removed_columns.join(", ")}
                          </div>
                        </div>
                      ) : null}
                      {event.type_changes && event.type_changes.length > 0 ? (
                        <div>
                          <div className="text-[10px] uppercase tracking-[0.16em] text-warning">
                            Type changes
                          </div>
                          <div className="mt-1 space-y-0.5 font-mono text-ink-2">
                            {event.type_changes.map((change) => (
                              <div key={change.column}>
                                {change.column}: {change.previous_type} → {change.current_type}
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  </div>

                  {event.acknowledged ? (
                    <span className="text-xs text-muted">
                      Acknowledged
                      {event.acknowledged_at ? ` ${formatDate(event.acknowledged_at)}` : ""}
                    </span>
                  ) : (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => acknowledge(event.id)}
                      disabled={busy === event.id}
                    >
                      {busy === event.id ? "Saving…" : "Acknowledge"}
                    </Button>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </SectionPanel>

      <ConnectorWatchPanel projectId={projectId} />
    </AppShell>
  );
}


/**
 * The watch over *sources*, as opposed to the events above.
 *
 * The drift events above are produced by extractions that ran. This is the
 * other half: a vendor can change an API between runs, and the first sign is
 * usually a pipeline failing at three in the morning. The watch re-reads each
 * connection's schema on a schedule and files an incident instead.
 */
function ConnectorWatchPanel({ projectId }: { projectId: string }) {
  const [status, setStatus] = useState<ConnectorWatchStatus | null>(null);
  const [report, setReport] = useState<ConnectorSweepReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"preview" | "run" | null>(null);

  const load = useCallback(async () => {
    try {
      setStatus(await apiFetch<ConnectorWatchStatus>(`/projects/${projectId}/connectors/watch`));
    } catch (caught) {
      setError(extractErrorMessage(caught));
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const sweep = useCallback(
    async (apply: boolean) => {
      setBusy(apply ? "run" : "preview");
      setError(null);
      try {
        const result = await apiFetch<ConnectorSweepReport>(
          `/projects/${projectId}/connectors/watch`,
          { method: "POST", body: JSON.stringify({ apply }) },
        );
        setReport(result);
        if (apply) await load();
      } catch (caught) {
        setError(extractErrorMessage(caught));
      } finally {
        setBusy(null);
      }
    },
    [projectId, load],
  );

  return (
    <SectionPanel
      title="Connector schema watch"
      description="Re-reads each connection's schema and compares it with the last one seen. Run it on a schedule — create a “Connector schema watch” schedule — and a vendor changing an API becomes an incident rather than a pipeline failing overnight."
    >
      {error ? (
        <div className="mb-3 rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Button type="button" onClick={() => void sweep(false)} disabled={busy !== null}>
          {busy === "preview" ? "Checking…" : "Check without recording"}
        </Button>
        <Button type="button" onClick={() => void sweep(true)} disabled={busy !== null}>
          {busy === "run" ? "Running…" : "Run the watch now"}
        </Button>
        <span className="text-[11.5px] text-muted">
          Checking records nothing and opens no incidents — useful the first time, when
          everything looks like a change.
        </span>
      </div>

      {report ? (
        <div className="mb-4 rounded-2xl border border-line bg-surface-2 px-4 py-3 text-[12.5px] text-ink-2">
          <p>
            Checked {report.streams_checked} stream
            {report.streams_checked === 1 ? "" : "s"} across {report.connections} connection
            {report.connections === 1 ? "" : "s"}. {report.drifted} changed
            {report.breaking > 0 ? `, ${report.breaking} breaking` : ""}.
            {report.streams_skipped > 0
              ? ` ${report.streams_skipped} could not be read.`
              : ""}
          </p>
          {report.results
            .filter((row) => row.added_columns.length || row.removed_columns.length || row.type_changes.length)
            .map((row) => (
              <p key={`${row.connection_id}:${row.stream}`} className="mt-1.5">
                <span
                  className={cx(
                    "mr-2 rounded-full border px-2 py-0.5 text-[10.5px]",
                    SEVERITY_TONE[(row.severity as DriftSeverity) ?? "none"] ?? SEVERITY_TONE.none,
                  )}
                >
                  {row.severity}
                </span>
                <code className="text-ink">{row.connection_name}</code> · {row.stream} —{" "}
                {row.summary}
              </p>
            ))}
          {report.skipped_connections.map((skipped) => (
            <p key={skipped.connection_id} className="mt-1.5 text-muted">
              {skipped.name}: {skipped.reason}
            </p>
          ))}
        </div>
      ) : null}

      {status && status.items.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[12.5px]">
            <thead className="text-[11px] uppercase tracking-[0.14em] text-muted">
              <tr>
                <th className="cell-pad">Stream</th>
                <th className="cell-pad">Connector</th>
                <th className="cell-pad">Columns</th>
                <th className="cell-pad">Last checked</th>
                <th className="cell-pad">Changes seen</th>
              </tr>
            </thead>
            <tbody className="text-ink-2">
              {status.items.map((row) => (
                <tr key={`${row.connection_id}:${row.stream}`} className="border-t border-line">
                  <td className="cell-pad text-ink">{row.stream}</td>
                  <td className="cell-pad">
                    {row.connector_type}
                    {row.source === "declared" ? (
                      <span className="ml-1.5 text-muted">· from its manifest</span>
                    ) : null}
                  </td>
                  <td className="cell-pad tabular-nums">{row.columns}</td>
                  <td className="cell-pad">{row.observed_at ? formatDate(row.observed_at) : "—"}</td>
                  <td className="cell-pad tabular-nums">{row.drift_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="rounded-2xl border border-dashed border-line px-4 py-8 text-center text-sm text-muted">
          Nothing is being watched yet. Run the watch once to record what each connection&rsquo;s
          streams look like today; from then on a change is something it can tell you about.
          {status && status.describable.length > 0 ? (
            <span className="mt-1 block text-[11.5px]">
              {status.describable.length} connector
              {status.describable.length === 1 ? "" : "s"} in the catalogue can describe their
              columns without a live credential.
            </span>
          ) : null}
        </p>
      )}
    </SectionPanel>
  );
}
