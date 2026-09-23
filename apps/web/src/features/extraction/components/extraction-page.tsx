"use client";

import { useCallback, useEffect, useId, useMemo, useState } from "react";

import type {
  AuthUser,
  ConnectionTestResponse,
  ConnectorCatalogResponse,
  ConnectorSpec,
  ConnectorType,
  DiscoveredTablesResponse,
  ExtractionConnection,
  ExtractionJob,
  ExtractionPreviewResponse,
  ExtractionRunResponse,
  LoadMode,
  StreamSource,
} from "@platform/shared-types";
import { Button, FormField, Input, SectionPanel, Select, StatusBadge } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { LiveSourcesPanel } from "@/features/extraction/components/live-sources-panel";
import { DeleteRowButton } from "@/components/ui/delete-row-button";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { cx } from "@/lib/utils";

type ExtractionPageProps = {
  currentUser: AuthUser;
  projectId: string;
  initialConnections: ExtractionConnection[];
  initialJobs: ExtractionJob[];
  initialStreams: StreamSource[];
};

const CONNECTOR_LABELS: Record<ConnectorType, string> = {
  postgresql: "PostgreSQL",
  mysql: "MySQL",
  sqlite: "SQLite",
};

/**
 * How a connector's tier reads beside a connection.
 *
 * The catalogue page shows this on every card, but the catalogue is not where
 * somebody decides to trust a source — this page is, and a run's numbers are
 * read long after either. Same glyph and same word as the catalogue, so the
 * badge means one thing across the product.
 */
const TIER_STYLE: Record<number, string> = {
  1: "border-success-line bg-success-soft text-success",
  2: "border-success-line bg-success-soft text-success",
  3: "border-line bg-surface-2 text-ink-3",
  4: "border-warning-line bg-warning-soft text-warning",
};

function TierBadge({ spec }: { spec: ConnectorSpec | undefined }) {
  if (!spec) return null;
  return (
    <span
      title={spec.tier_explanation}
      className={cx(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px]",
        TIER_STYLE[spec.tier] ?? TIER_STYLE[4],
      )}
    >
      <span aria-hidden="true">{spec.tier_badge}</span>
      {spec.tier_label}
    </span>
  );
}

const LOAD_MODE_LABELS: Record<LoadMode, string> = {
  full_refresh: "Full refresh",
  incremental_append: "Incremental · append",
  incremental_merge: "Incremental · merge",
};

const LOAD_MODE_HELP: Record<LoadMode, string> = {
  full_refresh: "Replaces the dataset with everything the query returns.",
  incremental_append: "Fetches only rows past the watermark and appends them.",
  incremental_merge: "Fetches new rows and upserts them on the primary key.",
};

export function ExtractionPageView({
  currentUser,
  projectId,
  initialConnections,
  initialJobs,
  initialStreams,
}: ExtractionPageProps) {
  const fieldPrefix = useId();
  const [connections, setConnections] = useState(initialConnections);
  const [jobs, setJobs] = useState(initialJobs);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [connectorType, setConnectorType] = useState<ConnectorType>("postgresql");
  const [catalogue, setCatalogue] = useState<Map<string, ConnectorSpec>>(new Map());

  useEffect(() => {
    apiFetch<ConnectorCatalogResponse>("/connectors")
      .then((response) =>
        setCatalogue(new Map(response.items.map((spec) => [spec.type, spec]))),
      )
      // The tier is an annotation, not a prerequisite: a catalogue that will
      // not load must not stop somebody creating a connection.
      .catch(() => setCatalogue(new Map()));
  }, []);
  const [connectionForm, setConnectionForm] = useState({
    name: "",
    host: "",
    port: "5432",
    database: "",
    username: "",
    password: "",
    filePath: "",
  });

  const [selectedConnectionId, setSelectedConnectionId] = useState<string>(
    initialConnections[0]?.id ?? "",
  );
  const [tables, setTables] = useState<DiscoveredTablesResponse["items"]>([]);
  const [preview, setPreview] = useState<ExtractionPreviewResponse | null>(null);
  const [lastRun, setLastRun] = useState<ExtractionRunResponse | null>(null);

  const [jobForm, setJobForm] = useState({
    name: "",
    table: "",
    loadMode: "full_refresh" as LoadMode,
    cursorColumn: "",
    primaryKeyColumns: "",
    // Recipe YAML (the same format the workbench exports); parsed server-side
    // into steps when the job is created.
    shapeYaml: "",
  });

  const selectedConnection = useMemo(
    () => connections.find((connection) => connection.id === selectedConnectionId) ?? null,
    [connections, selectedConnectionId],
  );

  const run = useCallback(
    async <T,>(key: string, action: () => Promise<T>, successMessage?: string): Promise<T | null> => {
      setBusy(key);
      setError(null);
      setFeedback(null);
      try {
        const result = await action();
        if (successMessage) setFeedback(successMessage);
        return result;
      } catch (caught) {
        setError(extractErrorMessage(caught));
        return null;
      } finally {
        setBusy(null);
      }
    },
    [],
  );

  const createConnection = async () => {
    const config: Record<string, string> =
      connectorType === "sqlite"
        ? { file_path: connectionForm.filePath }
        : {
            host: connectionForm.host,
            port: connectionForm.port,
            database: connectionForm.database,
            username: connectionForm.username,
            password: connectionForm.password,
          };

    const created = await run(
      "create-connection",
      () =>
        apiFetch<ExtractionConnection>(`/projects/${projectId}/extraction/connections`, {
          method: "POST",
          body: JSON.stringify({
            name: connectionForm.name,
            connector_type: connectorType,
            config,
          }),
        }),
      "Connection saved.",
    );

    if (created) {
      setConnections((current) => [created, ...current]);
      setSelectedConnectionId(created.id);
      setConnectionForm((form) => ({ ...form, name: "", password: "" }));
    }
  };

  const testConnection = async (connectionId: string) => {
    const result = await run(`test-${connectionId}`, () =>
      apiFetch<ConnectionTestResponse>(
        `/projects/${projectId}/extraction/connections/${connectionId}/test`,
        { method: "POST" },
      ),
    );
    if (!result) return;

    if (result.success) {
      setFeedback(
        `${result.message}${result.latency_ms ? ` (${result.latency_ms.toFixed(0)}ms)` : ""}`,
      );
    } else {
      setError(result.message);
    }
    setConnections((current) =>
      current.map((connection) =>
        connection.id === connectionId
          ? {
              ...connection,
              last_test_status: result.success ? "succeeded" : "failed",
              last_test_message: result.message,
              last_tested_at: new Date().toISOString(),
            }
          : connection,
      ),
    );
  };

  const discoverTables = async (connectionId: string) => {
    const result = await run(`tables-${connectionId}`, () =>
      apiFetch<DiscoveredTablesResponse>(
        `/projects/${projectId}/extraction/connections/${connectionId}/tables`,
      ),
    );
    if (result) {
      setTables(result.items);
      setPreview(null);
      setFeedback(`Found ${result.items.length} relation(s).`);
    }
  };

  const previewTable = async (table: string) => {
    if (!selectedConnectionId) return;
    const result = await run(`preview-${table}`, () =>
      apiFetch<ExtractionPreviewResponse>(
        `/projects/${projectId}/extraction/connections/${selectedConnectionId}/preview`,
        { method: "POST", body: JSON.stringify({ source_kind: "table", table, limit: 10 }) },
      ),
    );
    if (result) setPreview(result);
  };

  const createJob = async () => {
    if (!selectedConnectionId) {
      setError("Select a connection first.");
      return;
    }
    const created = await run(
      "create-job",
      async () => {
        let steps: unknown[] = [];
        if (jobForm.shapeYaml.trim()) {
          const parsed = await apiFetch<{ steps: unknown[] }>("/workbench/recipe/parse", {
            method: "POST",
            body: JSON.stringify({ yaml: jobForm.shapeYaml }),
          });
          steps = parsed.steps;
        }
        return apiFetch<ExtractionJob>(`/projects/${projectId}/extraction/jobs`, {
          method: "POST",
          body: JSON.stringify({
            connection_id: selectedConnectionId,
            name: jobForm.name,
            source_kind: "table",
            table: jobForm.table,
            load_mode: jobForm.loadMode,
            cursor_column: jobForm.cursorColumn || null,
            primary_key_columns: jobForm.primaryKeyColumns
              ? jobForm.primaryKeyColumns.split(",").map((value) => value.trim()).filter(Boolean)
              : [],
            steps,
          }),
        });
      },
      "Extraction job created.",
    );
    if (created) {
      setJobs((current) => [created, ...current]);
      setJobForm({
        name: "",
        table: "",
        loadMode: "full_refresh",
        cursorColumn: "",
        primaryKeyColumns: "",
        shapeYaml: "",
      });
    }
  };

  const runJob = async (jobId: string) => {
    const result = await run(`run-${jobId}`, () =>
      apiFetch<ExtractionRunResponse>(`/projects/${projectId}/extraction/jobs/${jobId}/run`, {
        method: "POST",
      }),
    );
    if (result) {
      setLastRun(result);
      setJobs((current) => current.map((job) => (job.id === jobId ? result.job : job)));
      const shaping = result.shaping
        ? result.shaping.pushed_steps > 0
          ? ` The ${result.shaping.surface} source ran ${result.shaping.pushed_steps} of ${result.shaping.pushed_steps + result.shaping.local_steps} step(s) as SQL; ${result.shaping.local_steps} ran here.`
          : ` All ${result.shaping.local_steps} step(s) ran here (${result.shaping.note || "the source could not run them"}).`
        : "";
      setFeedback(
        `Extracted ${result.rows_extracted} row(s): ${result.rows_added} added, ${result.rows_updated} updated, ${result.total_rows} total.${shaping}`,
      );
    }
  };

  const resetWatermark = async (jobId: string) => {
    const updated = await run(
      `reset-${jobId}`,
      () =>
        apiFetch<ExtractionJob>(`/projects/${projectId}/extraction/jobs/${jobId}/reset-watermark`, {
          method: "POST",
        }),
      "Watermark cleared. The next run reloads from the beginning.",
    );
    if (updated) setJobs((current) => current.map((job) => (job.id === jobId ? updated : job)));
  };

  const isSqlite = connectorType === "sqlite";

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Ingest"
      title="Extraction"
      subtitle="Connect to a source database, discover its tables, and run repeatable loads. Incremental modes track a watermark so each run reads only what changed."
    >
      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}
      {feedback ? (
        <div className="rounded-2xl border border-success-line bg-success-soft px-4 py-3 text-sm text-success">
          {feedback}
        </div>
      ) : null}

      <SectionPanel
        title="Connections"
        description="Credentials are encrypted at rest and never returned by the API."
      >
        <div className="grid gap-6 lg:grid-cols-[minmax(0,360px)_1fr]">
          <div className="space-y-3 rounded-2xl border border-line bg-surface p-4">
            <FormField label="Name" htmlFor={`${fieldPrefix}-name`}>
              <Input
                id={`${fieldPrefix}-name`}
                value={connectionForm.name}
                onChange={(event) =>
                  setConnectionForm((form) => ({ ...form, name: event.target.value }))
                }
                placeholder="Production warehouse"
              />
            </FormField>
            <FormField label="Type" htmlFor={`${fieldPrefix}-type`}>
              <Select
                id={`${fieldPrefix}-type`}
                value={connectorType}
                onChange={(event) => {
                  const next = event.target.value as ConnectorType;
                  setConnectorType(next);
                  setConnectionForm((form) => ({
                    ...form,
                    port: next === "mysql" ? "3306" : "5432",
                  }));
                }}
              >
                {Object.entries(CONNECTOR_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
              {catalogue.get(connectorType) && !catalogue.get(connectorType)!.verified ? (
                <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
                  <TierBadge spec={catalogue.get(connectorType)} />
                  {catalogue.get(connectorType)!.tier_explanation}
                </p>
              ) : (
                <p className="mt-1.5">
                  <TierBadge spec={catalogue.get(connectorType)} />
                </p>
              )}
            </FormField>

            {isSqlite ? (
              <FormField label="Database file path" htmlFor={`${fieldPrefix}-file`}>
                <Input
                  id={`${fieldPrefix}-file`}
                  value={connectionForm.filePath}
                  onChange={(event) =>
                    setConnectionForm((form) => ({ ...form, filePath: event.target.value }))
                  }
                  placeholder="/data/warehouse.db"
                />
              </FormField>
            ) : (
              <>
                <div className="grid grid-cols-[1fr_110px] gap-3">
                  <FormField label="Host" htmlFor={`${fieldPrefix}-host`}>
                    <Input
                      id={`${fieldPrefix}-host`}
                      value={connectionForm.host}
                      onChange={(event) =>
                        setConnectionForm((form) => ({ ...form, host: event.target.value }))
                      }
                      placeholder="db.internal"
                    />
                  </FormField>
                  <FormField label="Port" htmlFor={`${fieldPrefix}-port`}>
                    <Input
                      id={`${fieldPrefix}-port`}
                      value={connectionForm.port}
                      onChange={(event) =>
                        setConnectionForm((form) => ({ ...form, port: event.target.value }))
                      }
                    />
                  </FormField>
                </div>
                <FormField label="Database" htmlFor={`${fieldPrefix}-db`}>
                  <Input
                    id={`${fieldPrefix}-db`}
                    value={connectionForm.database}
                    onChange={(event) =>
                      setConnectionForm((form) => ({ ...form, database: event.target.value }))
                    }
                  />
                </FormField>
                <FormField label="Username" htmlFor={`${fieldPrefix}-user`}>
                  <Input
                    id={`${fieldPrefix}-user`}
                    value={connectionForm.username}
                    onChange={(event) =>
                      setConnectionForm((form) => ({ ...form, username: event.target.value }))
                    }
                  />
                </FormField>
                <FormField label="Password" htmlFor={`${fieldPrefix}-pass`}>
                  <Input
                    id={`${fieldPrefix}-pass`}
                    type="password"
                    value={connectionForm.password}
                    onChange={(event) =>
                      setConnectionForm((form) => ({ ...form, password: event.target.value }))
                    }
                  />
                </FormField>
              </>
            )}

            <Button
              className="w-full"
              onClick={createConnection}
              disabled={busy === "create-connection" || !connectionForm.name.trim()}
            >
              {busy === "create-connection" ? "Saving…" : "Save connection"}
            </Button>
          </div>

          <div className="space-y-3">
            {connections.length === 0 ? (
              <p className="rounded-2xl border border-dashed border-line px-4 py-8 text-center text-sm text-muted">
                No connections yet. Add one to begin extracting.
              </p>
            ) : (
              connections.map((connection) => (
                <article
                  key={connection.id}
                  className={cx(
                    "rounded-2xl border px-4 py-4 transition duration-[var(--duration-base)] ease-[var(--ease-out)]",
                    connection.id === selectedConnectionId
                      ? "border-[color:var(--accent-soft)] bg-[color:var(--accent-faint)]"
                      : "border-line bg-surface hover:border-line-strong",
                  )}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-sm font-semibold text-ink">{connection.name}</h3>
                        <span className="rounded-full border border-line px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-ink-3">
                          {CONNECTOR_LABELS[connection.connector_type]}
                        </span>
                        <TierBadge spec={catalogue.get(connection.connector_type)} />
                        {connection.last_test_status ? (
                          <StatusBadge
                            value={connection.last_test_status === "succeeded" ? "succeeded" : "failed"}
                          />
                        ) : null}
                      </div>
                      <p className="mt-1 text-xs text-muted">
                        {connection.last_tested_at
                          ? `Tested ${formatDate(connection.last_tested_at)}`
                          : "Never tested"}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => testConnection(connection.id)}
                        disabled={busy === `test-${connection.id}`}
                      >
                        {busy === `test-${connection.id}` ? "Testing…" : "Test"}
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => {
                          setSelectedConnectionId(connection.id);
                          discoverTables(connection.id);
                        }}
                        disabled={busy === `tables-${connection.id}`}
                      >
                        {busy === `tables-${connection.id}` ? "Reading…" : "Discover"}
                      </Button>
                      <DeleteRowButton
                        path={`/projects/${projectId}/extraction/connections/${connection.id}`}
                        name={connection.name}
                        kind="extraction connection"
                        consequences={[
                          "Its stored credentials go with it.",
                          "Extraction jobs configured against it will no longer have a source.",
                        ]}
                        onDeleted={() => {
                          const left = connections.filter((row) => row.id !== connection.id);
                          setConnections(left);
                          // "" is this page's "nothing selected"; falling back
                          // to whatever survives keeps the table panel useful.
                          if (selectedConnectionId === connection.id) {
                            setSelectedConnectionId(left[0]?.id ?? "");
                          }
                        }}
                      />
                    </div>
                  </div>
                </article>
              ))
            )}
          </div>
        </div>
      </SectionPanel>

      {tables.length > 0 ? (
        <SectionPanel
          title="Discovered relations"
          description={`${tables.length} relation(s) visible to ${selectedConnection?.name ?? "this connection"}. Select one to preview and prefill a job.`}
        >
          <div className="flex flex-wrap gap-2">
            {tables.map((table) => (
              <button
                key={table.qualified_name}
                type="button"
                onClick={() => {
                  setJobForm((form) => ({ ...form, table: table.name }));
                  previewTable(table.name);
                }}
                className="rounded-xl border border-line bg-surface px-3 py-2 text-xs text-ink transition duration-[var(--duration-fast)] hover:border-[color:var(--accent-soft)] hover:bg-[color:var(--accent-faint)]"
              >
                <span className="font-medium">{table.qualified_name}</span>
                <span className="ml-2 text-[10px] uppercase tracking-[0.14em] text-muted">
                  {table.kind}
                </span>
              </button>
            ))}
          </div>

          {preview ? (
            <div className="mt-5 overflow-x-auto rounded-2xl border border-line">
              <table className="w-full min-w-max text-left text-xs">
                <thead className="bg-surface text-ink-3">
                  <tr>
                    {preview.columns.map((column) => (
                      <th key={column} className="whitespace-nowrap cell-pad font-medium">
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {preview.rows.map((row, index) => (
                    <tr key={index} className="text-ink-2">
                      {preview.columns.map((column) => (
                        <td key={column} className="whitespace-nowrap cell-pad tabular">
                          {row[column] === null || row[column] === undefined
                            ? "—"
                            : String(row[column])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </SectionPanel>
      ) : null}

      <SectionPanel
        title="Extraction jobs"
        description="A job is a saved, repeatable load. Incremental jobs remember where they stopped."
      >
        <div className="grid gap-6 lg:grid-cols-[minmax(0,360px)_1fr]">
          <div className="space-y-3 rounded-2xl border border-line bg-surface p-4">
            <FormField label="Job name" htmlFor={`${fieldPrefix}-job-name`}>
              <Input
                id={`${fieldPrefix}-job-name`}
                value={jobForm.name}
                onChange={(event) => setJobForm((form) => ({ ...form, name: event.target.value }))}
                placeholder="Orders nightly"
              />
            </FormField>
            <FormField label="Table" htmlFor={`${fieldPrefix}-job-table`}>
              <Input
                id={`${fieldPrefix}-job-table`}
                value={jobForm.table}
                onChange={(event) => setJobForm((form) => ({ ...form, table: event.target.value }))}
                placeholder="orders"
              />
            </FormField>
            <FormField
              label="Load mode"
              htmlFor={`${fieldPrefix}-job-mode`}
              description={LOAD_MODE_HELP[jobForm.loadMode]}
            >
              <Select
                id={`${fieldPrefix}-job-mode`}
                value={jobForm.loadMode}
                onChange={(event) =>
                  setJobForm((form) => ({ ...form, loadMode: event.target.value as LoadMode }))
                }
              >
                {Object.entries(LOAD_MODE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </FormField>
            {jobForm.loadMode !== "full_refresh" ? (
              <FormField
                label="Cursor column"
                htmlFor={`${fieldPrefix}-job-cursor`}
                description="Rows with a greater value are treated as new."
              >
                <Input
                  id={`${fieldPrefix}-job-cursor`}
                  value={jobForm.cursorColumn}
                  onChange={(event) =>
                    setJobForm((form) => ({ ...form, cursorColumn: event.target.value }))
                  }
                  placeholder="updated_at"
                />
              </FormField>
            ) : null}
            {jobForm.loadMode === "incremental_merge" ? (
              <FormField
                label="Primary key column(s)"
                htmlFor={`${fieldPrefix}-job-keys`}
                description="Comma separated. Restated rows replace the stored version."
              >
                <Input
                  id={`${fieldPrefix}-job-keys`}
                  value={jobForm.primaryKeyColumns}
                  onChange={(event) =>
                    setJobForm((form) => ({ ...form, primaryKeyColumns: event.target.value }))
                  }
                  placeholder="id"
                />
              </FormField>
            ) : null}
            <FormField
              label="Shape at the source (optional)"
              htmlFor={`${fieldPrefix}-job-shape`}
              description="Recipe YAML, as the workbench exports it. Steps the database can run are pushed down as SQL around the extract; the rest run here before the dataset is written. Incremental loads accept row-wise steps only."
            >
              <textarea
                id={`${fieldPrefix}-job-shape`}
                value={jobForm.shapeYaml}
                onChange={(event) => setJobForm((form) => ({ ...form, shapeYaml: event.target.value }))}
                rows={5}
                spellCheck={false}
                placeholder={"steps:\n  - type: filter_rows\n    config:\n      conditions:\n        - {column: amount, operator: greater_than, value: 0}"}
                className="w-full rounded-xl border border-line bg-sunken px-3 py-2 font-mono text-[12px] text-ink outline-none transition focus:border-[color:var(--accent)]"
              />
            </FormField>
            <Button
              className="w-full"
              onClick={createJob}
              disabled={busy === "create-job" || !jobForm.name.trim() || !jobForm.table.trim()}
            >
              {busy === "create-job" ? "Creating…" : "Create job"}
            </Button>
          </div>

          <div className="space-y-3">
            {jobs.length === 0 ? (
              <p className="rounded-2xl border border-dashed border-line px-4 py-8 text-center text-sm text-muted">
                No extraction jobs yet.
              </p>
            ) : (
              jobs.map((job) => (
                <article
                  key={job.id}
                  className="rounded-2xl border border-line bg-surface px-4 py-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-sm font-semibold text-ink">{job.name}</h3>
                        <span className="rounded-full border border-line px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-ink-3">
                          {LOAD_MODE_LABELS[job.load_mode]}
                        </span>
                        {job.last_run_status ? <StatusBadge value={job.last_run_status} /> : null}
                        {job.steps && job.steps.length > 0 ? (
                          <span
                            className="rounded-full border border-line bg-sunken px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] text-ink-3"
                            title={job.steps.map((step) => step.step_type).join(" → ")}
                          >
                            shapes {job.steps.length} step{job.steps.length === 1 ? "" : "s"}
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-1 text-xs text-muted">
                        {job.source_table ?? "custom query"}
                        {job.cursor_column ? ` · cursor ${job.cursor_column}` : ""}
                        {job.execution_count ? ` · ${job.execution_count} run(s)` : ""}
                      </p>
                      {job.watermark_value ? (
                        <p className="mt-1 text-xs tabular text-[color:var(--accent-muted)]">
                          watermark: {job.watermark_value}
                        </p>
                      ) : null}
                      {job.last_error_message ? (
                        <p className="mt-1 text-xs text-danger">{job.last_error_message}</p>
                      ) : null}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button size="sm" onClick={() => runJob(job.id)} disabled={busy === `run-${job.id}`}>
                        {busy === `run-${job.id}` ? "Running…" : "Run now"}
                      </Button>
                      {job.load_mode !== "full_refresh" ? (
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => resetWatermark(job.id)}
                          disabled={busy === `reset-${job.id}`}
                        >
                          Reset watermark
                        </Button>
                      ) : null}
                      <DeleteRowButton
                        path={`/projects/${projectId}/extraction/jobs/${job.id}`}
                        name={job.name}
                        kind="extraction job"
                        consequences={["Its watermark and run history go with it."]}
                        onDeleted={() =>
                          setJobs((current) => current.filter((row) => row.id !== job.id))
                        }
                      />
                    </div>
                  </div>
                </article>
              ))
            )}
          </div>
        </div>
      </SectionPanel>

      {lastRun ? (
        <SectionPanel title="Last run" description={`Run ${lastRun.run_id}`}>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {(
              [
                ["Rows extracted", lastRun.rows_extracted],
                ["Added", lastRun.rows_added],
                ["Updated", lastRun.rows_updated],
                ["Total in dataset", lastRun.total_rows],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="rounded-2xl border border-line bg-surface px-4 py-3">
                <div className="text-[11px] uppercase tracking-[0.18em] text-muted">{label}</div>
                <div className="mt-1 text-2xl font-semibold tabular text-ink">{value}</div>
              </div>
            ))}
          </div>
          {lastRun.warnings.length > 0 ? (
            <ul className="mt-4 space-y-1 text-xs text-warning">
              {lastRun.warnings.map((warning) => (
                <li key={warning}>• {warning}</li>
              ))}
            </ul>
          ) : null}
        </SectionPanel>
      ) : null}
      <LiveSourcesPanel
        projectId={projectId}
        connections={connections}
        initial={initialStreams}
      />
    </AppShell>
  );
}
