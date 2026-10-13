"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useMemo, useState } from "react";

import type {
  AuthUser,
  ConnectionTestResponse,
  DatasetRecord,
  PipelineRunRecord,
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
import {
  Button,
  EmptyState,
  FormField,
  Input,
  Modal,
  SectionPanel,
  Select,
  StatusBadge,
} from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { DeleteRowButton } from "@/components/ui/delete-row-button";
import { Icon } from "@/components/ui/icon";
import { AddDataDialog } from "@/features/datasets/components/add-data-dialog";
import { UploadDatasetModal } from "@/features/datasets/components/upload-dataset-modal";
import { LiveSourcesPanel } from "@/features/extraction/components/live-sources-panel";
import { groupDatasets, originHints } from "@/lib/dataset-origin";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate, formatNumber } from "@/lib/format";
import { cx } from "@/lib/utils";

type ExtractionPageProps = {
  currentUser: AuthUser;
  projectId: string;
  initialConnections: ExtractionConnection[];
  initialJobs: ExtractionJob[];
  initialStreams: StreamSource[];
  /** For the uploaded-files list: datasets and the runs that made them. */
  datasets: DatasetRecord[];
  runs: PipelineRunRecord[];
  /** Open "Connect a database" straight away (`?connect=1`). */
  startConnecting?: boolean;
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
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[12px]",
        TIER_STYLE[spec.tier] ?? TIER_STYLE[4],
      )}
    >
      <span aria-hidden="true">{spec.tier_badge}</span>
      {spec.tier_label}
    </span>
  );
}

const LOAD_MODE_LABELS: Record<LoadMode, string> = {
  full_refresh: "The whole table, every time",
  incremental_append: "Only new rows",
  incremental_merge: "New and changed rows",
};

const LOAD_MODE_HELP: Record<LoadMode, string> = {
  full_refresh: "Each run replaces the dataset with the whole table.",
  incremental_append: "Each run adds only rows newer than the last run.",
  incremental_merge:
    "Each run adds new rows and updates changed ones, matched on a key.",
};

const EMPTY_JOB_FORM = {
  name: "",
  table: "",
  loadMode: "full_refresh" as LoadMode,
  cursorColumn: "",
  primaryKeyColumns: "",
  // Recipe YAML (the same format the workbench exports); parsed server-side
  // into steps when the job is created.
  shapeYaml: "",
};

export function ExtractionPageView({
  currentUser,
  projectId,
  initialConnections,
  initialJobs,
  initialStreams,
  datasets,
  runs,
  startConnecting = false,
}: ExtractionPageProps) {
  const fieldPrefix = useId();
  const [connections, setConnections] = useState(initialConnections);
  const [jobs, setJobs] = useState(initialJobs);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [connectorType, setConnectorType] =
    useState<ConnectorType>("postgresql");
  const [catalogue, setCatalogue] = useState<Map<string, ConnectorSpec>>(
    new Map(),
  );

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
  const [preview, setPreview] = useState<ExtractionPreviewResponse | null>(
    null,
  );
  // Kept apart from the import form, which resets after an import is created.
  const [previewedTable, setPreviewedTable] = useState("");
  const [lastRun, setLastRun] = useState<ExtractionRunResponse | null>(null);

  const [jobForm, setJobForm] = useState(EMPTY_JOB_FORM);
  // Creating things happens in dialogs; the page itself is the list of what
  // exists (A0 page template: no form-first pages).
  const [connectionDialogOpen, setConnectionDialogOpen] = useState(startConnecting);
  const [addDataOpen, setAddDataOpen] = useState(false);
  const [jobDialogOpen, setJobDialogOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);

  const uploadedFiles = useMemo(
    () =>
      groupDatasets(datasets, originHints(runs, initialStreams)).filter(
        (group) => group.origin === "upload",
      ),
    [datasets, runs, initialStreams],
  );

  const selectedConnection = useMemo(
    () =>
      connections.find(
        (connection) => connection.id === selectedConnectionId,
      ) ?? null,
    [connections, selectedConnectionId],
  );

  const run = useCallback(
    async <T,>(
      key: string,
      action: () => Promise<T>,
      successMessage?: string,
    ): Promise<T | null> => {
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
        apiFetch<ExtractionConnection>(
          `/projects/${projectId}/extraction/connections`,
          {
            method: "POST",
            body: JSON.stringify({
              name: connectionForm.name,
              connector_type: connectorType,
              config,
            }),
          },
        ),
      "Database connected. Browse its tables to set up an import.",
    );

    if (created) {
      setConnections((current) => [created, ...current]);
      setSelectedConnectionId(created.id);
      setConnectionForm((form) => ({ ...form, name: "", password: "" }));
      setConnectionDialogOpen(false);
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
      setFeedback(
        `Found ${result.items.length} table${result.items.length === 1 ? "" : "s"}. Pick one to preview it.`,
      );
    }
  };

  const previewTable = async (table: string) => {
    if (!selectedConnectionId) return;
    const result = await run(`preview-${table}`, () =>
      apiFetch<ExtractionPreviewResponse>(
        `/projects/${projectId}/extraction/connections/${selectedConnectionId}/preview`,
        {
          method: "POST",
          body: JSON.stringify({ source_kind: "table", table, limit: 10 }),
        },
      ),
    );
    if (result) {
      setPreview(result);
      setPreviewedTable(table);
    }
  };

  const createJob = async () => {
    if (!selectedConnectionId) {
      setError("Choose which database to import from first.");
      return;
    }
    const created = await run(
      "create-job",
      async () => {
        let steps: unknown[] = [];
        if (jobForm.shapeYaml.trim()) {
          const parsed = await apiFetch<{ steps: unknown[] }>(
            "/workbench/recipe/parse",
            {
              method: "POST",
              body: JSON.stringify({ yaml: jobForm.shapeYaml }),
            },
          );
          steps = parsed.steps;
        }
        return apiFetch<ExtractionJob>(
          `/projects/${projectId}/extraction/jobs`,
          {
            method: "POST",
            body: JSON.stringify({
              connection_id: selectedConnectionId,
              name: jobForm.name,
              source_kind: "table",
              table: jobForm.table,
              load_mode: jobForm.loadMode,
              cursor_column: jobForm.cursorColumn || null,
              primary_key_columns: jobForm.primaryKeyColumns
                ? jobForm.primaryKeyColumns
                    .split(",")
                    .map((value) => value.trim())
                    .filter(Boolean)
                : [],
              steps,
            }),
          },
        );
      },
      "Import created. Run it now, or put it on a schedule.",
    );
    if (created) {
      setJobs((current) => [created, ...current]);
      setJobForm(EMPTY_JOB_FORM);
      setJobDialogOpen(false);
    }
  };

  const runJob = async (jobId: string) => {
    const result = await run(`run-${jobId}`, () =>
      apiFetch<ExtractionRunResponse>(
        `/projects/${projectId}/extraction/jobs/${jobId}/run`,
        {
          method: "POST",
        },
      ),
    );
    if (result) {
      setLastRun(result);
      setJobs((current) =>
        current.map((job) => (job.id === jobId ? result.job : job)),
      );
      const plan = result.shaping;
      const placement = plan
        ? plan.pushed_steps > 0
          ? ` The ${plan.surface} source ran ${plan.pushed_steps} of ${plan.pushed_steps + plan.local_steps} step(s) as SQL; ${plan.local_steps} ran here.`
          : ` All ${plan.local_steps} step(s) ran here (${plan.note || "the source could not run them"}).`
        : "";
      const rewritten =
        plan && plan.rewrites && plan.rewrites.length > 0
          ? ` Rewritten first without changing the result: ${plan.rewrites.join("; ")}.`
          : "";
      const shaping = placement + rewritten;
      setFeedback(
        `Imported ${result.rows_extracted} row(s): ${result.rows_added} added, ${result.rows_updated} updated. The dataset now has ${result.total_rows}.${shaping}`,
      );
    }
  };

  const resetWatermark = async (jobId: string) => {
    const updated = await run(
      `reset-${jobId}`,
      () =>
        apiFetch<ExtractionJob>(
          `/projects/${projectId}/extraction/jobs/${jobId}/reset-watermark`,
          {
            method: "POST",
          },
        ),
      "Done. The next run imports the whole table again.",
    );
    if (updated)
      setJobs((current) =>
        current.map((job) => (job.id === jobId ? updated : job)),
      );
  };

  const isSqlite = connectorType === "sqlite";

  const openImportFor = (table: string) => {
    setJobForm((form) => ({
      ...form,
      table,
      name:
        form.name ||
        table.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase()),
    }));
    setJobDialogOpen(true);
  };

  // Sections with something in them come first: a project that connected a
  // database but uploaded nothing should see its database without scrolling
  // past an empty files panel.
  const filesFirst = uploadedFiles.length > 0 || connections.length === 0;
  const uploadedFilesPanel = (
    <SectionPanel
      title="Uploaded files"
      description="Spreadsheets and data files added by hand. Each becomes a dataset."
      actions={
        uploadedFiles.length > 0 ? (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setUploadOpen(true)}
          >
            Upload another
          </Button>
        ) : null
      }
    >
      {uploadedFiles.length === 0 ? (
        <div className="border-line flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-dashed px-4 py-5">
          <p className="text-ink-3 text-[14px]">
            No files yet. CSV, Excel, JSON and Parquet all work, or start with sample data.
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="secondary" onClick={() => setAddDataOpen(true)}>
                    Try sample data
                  </Button>
                  <Button size="sm" onClick={() => setUploadOpen(true)}>
                    Upload a file
                  </Button>
                </div>
        </div>
      ) : (
        <ul className="divide-line divide-y">
          {uploadedFiles.map((group) => (
            <li
              key={group.latest.id}
              className="flex items-center justify-between gap-3 py-2.5"
            >
              <div className="min-w-0">
                <Link
                  href={`/projects/${projectId}/datasets/${group.latest.id}`}
                  className="text-ink block truncate text-[14px] font-medium hover:text-[color:var(--accent-muted)]"
                >
                  {group.name}
                </Link>
                <div className="text-ink-3 truncate text-[13px]">
                  {group.latest.original_filename ?? "Uploaded file"} ·{" "}
                  {formatNumber(group.latest.row_count)} rows
                </div>
              </div>
              <span className="text-muted shrink-0 text-[13px]">
                {formatDate(group.latest.created_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </SectionPanel>
  );

  return (
    <>
      <AppShell
        currentUser={currentUser}
        title="Sources"
        subtitle="Upload files, connect databases and receive live data."
        actions={
          <>
            <Button onClick={() => setUploadOpen(true)}>
              <Icon name="upload" size={16} />
              Upload a file
            </Button>
            <Button
              variant="secondary"
              onClick={() => setConnectionDialogOpen(true)}
            >
              <Icon name="database" size={16} />
              Connect a database
            </Button>
          </>
        }
      >
        {error ? (
          <div
            role="alert"
            className="border-danger-line bg-danger-soft text-danger rounded-2xl border px-4 py-3 text-sm"
          >
            {error}
          </div>
        ) : null}
        {feedback ? (
          <div
            role="status"
            className="border-success-line bg-success-soft text-success flex flex-wrap items-center justify-between gap-3 rounded-2xl border px-4 py-3 text-sm"
          >
            <span>{feedback}</span>
            {lastRun && feedback.startsWith("Imported") ? (
              <Link
                href={`/projects/${projectId}/datasets/${lastRun.dataset_id}`}
                className="shrink-0 font-medium underline underline-offset-4"
              >
                Open the dataset
              </Link>
            ) : null}
          </div>
        ) : null}

        {filesFirst ? uploadedFilesPanel : null}

        <SectionPanel
          title="Databases"
          description="Live connections to your databases. Passwords are encrypted and never shown again."
          actions={
            connections.length > 0 ? (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setConnectionDialogOpen(true)}
              >
                Connect another
              </Button>
            ) : null
          }
        >
          {connections.length === 0 ? (
            <EmptyState
              title="No databases connected"
              description="Connect PostgreSQL, MySQL or SQLite to import tables and keep them up to date."
              action={
                <Button size="sm" onClick={() => setConnectionDialogOpen(true)}>
                  Connect a database
                </Button>
              }
            />
          ) : (
            <div className="space-y-3">
              {connections.map((connection) => (
                <article
                  key={connection.id}
                  className={cx(
                    "rounded-2xl border px-4 py-4 transition duration-[var(--duration-base)] ease-[var(--ease-out)]",
                    connection.id === selectedConnectionId && tables.length > 0
                      ? "border-[color:var(--accent-soft)] bg-[color:var(--accent-faint)]"
                      : "border-line bg-surface hover:border-line-strong",
                  )}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-ink text-[15px] font-semibold">
                          {connection.name}
                        </h3>
                        <span className="border-line text-ink-3 rounded-full border px-2 py-0.5 text-[12px]">
                          {CONNECTOR_LABELS[connection.connector_type]}
                        </span>
                        {catalogue.get(connection.connector_type) &&
                        !catalogue.get(connection.connector_type)!.verified ? (
                          <TierBadge
                            spec={catalogue.get(connection.connector_type)}
                          />
                        ) : null}
                        {connection.last_test_status ? (
                          <StatusBadge
                            value={
                              connection.last_test_status === "succeeded"
                                ? "succeeded"
                                : "failed"
                            }
                          />
                        ) : null}
                      </div>
                      <p className="text-muted mt-1 text-[13px]">
                        {connection.last_tested_at
                          ? `Last checked ${formatDate(connection.last_tested_at)}`
                          : "Not checked yet"}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        size="sm"
                        onClick={() => {
                          setSelectedConnectionId(connection.id);
                          discoverTables(connection.id);
                        }}
                        disabled={busy === `tables-${connection.id}`}
                      >
                        {busy === `tables-${connection.id}`
                          ? "Reading…"
                          : "Browse tables"}
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => testConnection(connection.id)}
                        disabled={busy === `test-${connection.id}`}
                      >
                        {busy === `test-${connection.id}`
                          ? "Checking…"
                          : "Check connection"}
                      </Button>
                      <DeleteRowButton
                        path={`/projects/${projectId}/extraction/connections/${connection.id}`}
                        name={connection.name}
                        kind="database connection"
                        consequences={[
                          "Its stored password goes with it.",
                          "Imports set up from it will no longer have a database to read.",
                        ]}
                        onDeleted={() => {
                          const left = connections.filter(
                            (row) => row.id !== connection.id,
                          );
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
              ))}
            </div>
          )}
        </SectionPanel>

        {tables.length > 0 ? (
          <SectionPanel
            title={`Tables in ${selectedConnection?.name ?? "this database"}`}
            description="Pick a table to see its first rows, then import it."
            actions={
              <Button variant="ghost" size="sm" onClick={() => setTables([])}>
                Close
              </Button>
            }
          >
            <div className="flex flex-wrap gap-2">
              {tables.map((table) => (
                <button
                  key={table.qualified_name}
                  type="button"
                  aria-pressed={
                    previewedTable === table.name && preview !== null
                  }
                  onClick={() => {
                    setJobForm((form) => ({ ...form, table: table.name }));
                    previewTable(table.name);
                  }}
                  className={cx(
                    "text-ink rounded-xl border px-3 py-2 text-[13px] transition duration-[var(--duration-fast)] hover:border-[color:var(--accent-soft)] hover:bg-[color:var(--accent-faint)]",
                    previewedTable === table.name && preview !== null
                      ? "border-[color:var(--accent)] bg-[color:var(--accent-faint)]"
                      : "border-line bg-surface",
                  )}
                >
                  <span className="font-medium">{table.qualified_name}</span>
                  {table.kind !== "table" ? (
                    <span className="text-muted ml-2 text-[12px]">
                      {table.kind}
                    </span>
                  ) : null}
                </button>
              ))}
            </div>

            {preview ? (
              <>
                <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
                  <p className="text-ink-3 text-[13px]">
                    The first {preview.rows.length} rows of {previewedTable}.
                  </p>
                  <Button
                    size="sm"
                    onClick={() => openImportFor(previewedTable)}
                  >
                    Import this table
                  </Button>
                </div>
                <div className="border-line mt-3 overflow-x-auto rounded-2xl border">
                  <table className="w-full min-w-max text-left text-[13px]">
                    <thead className="bg-surface text-ink-3">
                      <tr>
                        {preview.columns.map((column) => (
                          <th
                            key={column}
                            className="cell-pad font-medium whitespace-nowrap"
                          >
                            {column}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-line divide-y">
                      {preview.rows.map((row, index) => (
                        <tr key={index} className="text-ink-2">
                          {preview.columns.map((column) => (
                            <td
                              key={column}
                              className="cell-pad tabular whitespace-nowrap"
                            >
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
              </>
            ) : null}
          </SectionPanel>
        ) : null}

        {connections.length > 0 ? (
          <SectionPanel
            title="Imports"
            description="Saved imports that copy a table into a dataset. Run them by hand or on a schedule."
            actions={
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setJobDialogOpen(true)}
              >
                New import
              </Button>
            }
          >
            {jobs.length === 0 ? (
              <p className="border-line text-muted rounded-2xl border border-dashed px-4 py-6 text-center text-[14px]">
                No imports yet. Browse a database&apos;s tables and pick one to
                import.
              </p>
            ) : (
              <div className="space-y-3">
                {jobs.map((job) => (
                  <article
                    key={job.id}
                    className="border-line bg-surface rounded-2xl border px-4 py-4"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-ink text-[15px] font-semibold">
                            {job.name}
                          </h3>
                          <span className="border-line text-ink-3 rounded-full border px-2 py-0.5 text-[12px]">
                            {LOAD_MODE_LABELS[job.load_mode]}
                          </span>
                          {job.last_run_status ? (
                            <StatusBadge value={job.last_run_status} />
                          ) : null}
                          {job.steps && job.steps.length > 0 ? (
                            <span
                              className="border-line bg-sunken text-ink-3 rounded-full border px-2 py-0.5 text-[12px]"
                              title={job.steps
                                .map((step) => step.step_type)
                                .join(" → ")}
                            >
                              cleans {job.steps.length} step
                              {job.steps.length === 1 ? "" : "s"} on the way in
                            </span>
                          ) : null}
                        </div>
                        <p className="text-muted mt-1 text-[13px]">
                          {job.source_table
                            ? `Table ${job.source_table}`
                            : "Custom query"}
                          {job.cursor_column
                            ? ` · new rows found by ${job.cursor_column}`
                            : ""}
                          {job.execution_count
                            ? ` · run ${job.execution_count} time${job.execution_count === 1 ? "" : "s"}`
                            : " · not run yet"}
                        </p>
                        {job.watermark_value ? (
                          <p className="tabular mt-1 text-[13px] text-[color:var(--accent-muted)]">
                            Loaded up to {job.watermark_value}
                          </p>
                        ) : null}
                        {job.last_error_message ? (
                          <p className="text-danger mt-1 text-[13px]">
                            {job.last_error_message}
                          </p>
                        ) : null}
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Button
                          size="sm"
                          onClick={() => runJob(job.id)}
                          disabled={busy === `run-${job.id}`}
                        >
                          {busy === `run-${job.id}` ? "Importing…" : "Run now"}
                        </Button>
                        {job.load_mode !== "full_refresh" &&
                        job.watermark_value ? (
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => resetWatermark(job.id)}
                            disabled={busy === `reset-${job.id}`}
                            title="Forget where the last run stopped, so the next run imports everything again."
                          >
                            Start over
                          </Button>
                        ) : null}
                        <DeleteRowButton
                          path={`/projects/${projectId}/extraction/jobs/${job.id}`}
                          name={job.name}
                          kind="import"
                          consequences={[
                            "Its run history and where it last stopped go with it. Datasets it made stay.",
                          ]}
                          onDeleted={() =>
                            setJobs((current) =>
                              current.filter((row) => row.id !== job.id),
                            )
                          }
                        />
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </SectionPanel>
        ) : null}

        {lastRun ? (
          <SectionPanel title="Last import" description={lastRun.job.name}>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {(
                [
                  ["Rows read", lastRun.rows_extracted],
                  ["Added", lastRun.rows_added],
                  ["Updated", lastRun.rows_updated],
                  ["Now in the dataset", lastRun.total_rows],
                ] as const
              ).map(([label, value]) => (
                <div
                  key={label}
                  className="border-line bg-surface rounded-2xl border px-4 py-3"
                >
                  <div className="text-muted text-[13px]">{label}</div>
                  <div className="tabular text-ink mt-1 text-2xl font-semibold">
                    {value}
                  </div>
                </div>
              ))}
            </div>
            {lastRun.warnings.length > 0 ? (
              <ul className="text-warning mt-4 space-y-1 text-[13px]">
                {lastRun.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : null}
          </SectionPanel>
        ) : null}

        {filesFirst ? null : uploadedFilesPanel}

        <LiveSourcesPanel
          projectId={projectId}
          connections={connections}
          initial={initialStreams}
        />

        <p className="text-ink-3 text-[14px]">
          Need a different kind of source?{" "}
          <Link
            href="/connectors"
            className="font-medium text-[color:var(--accent-muted)] hover:underline"
          >
            See every connector
          </Link>
        </p>
      </AppShell>

      <AddDataDialog

        open={addDataOpen}

        onClose={() => setAddDataOpen(false)}

        projectId={projectId}

      />

      <UploadDatasetModal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        projectId={projectId}
      />

      <Modal
        open={connectionDialogOpen}
        title="Connect a database"
        description="Pipewright reads from it; it never changes your data unless you use the Table editor."
        onClose={() => setConnectionDialogOpen(false)}
        widthClassName="max-w-lg"
        footer={
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setConnectionDialogOpen(false)}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={createConnection}
              disabled={
                busy === "create-connection" || !connectionForm.name.trim()
              }
            >
              {busy === "create-connection" ? "Connecting…" : "Connect"}
            </Button>
          </div>
        }
      >
        <div className="space-y-4">
          {error && connectionDialogOpen ? (
            <p role="alert" className="text-danger text-[13px]">
              {error}
            </p>
          ) : null}
          <FormField
            label="Name"
            htmlFor={`${fieldPrefix}-name`}
            description="Any name that helps you recognise it."
          >
            <Input
              id={`${fieldPrefix}-name`}
              value={connectionForm.name}
              onChange={(event) =>
                setConnectionForm((form) => ({
                  ...form,
                  name: event.target.value,
                }))
              }
              placeholder="Sales database"
              autoFocus
            />
          </FormField>
          <FormField label="Kind of database" htmlFor={`${fieldPrefix}-type`}>
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
            {catalogue.get(connectorType) &&
            !catalogue.get(connectorType)!.verified ? (
              <p className="text-muted mt-1.5 flex flex-wrap items-center gap-1.5 text-[13px]">
                <TierBadge spec={catalogue.get(connectorType)} />
                {catalogue.get(connectorType)!.tier_explanation}
              </p>
            ) : null}
          </FormField>

          {isSqlite ? (
            <FormField
              label="Database file"
              htmlFor={`${fieldPrefix}-file`}
              description="Where the file is on the server Pipewright runs on."
            >
              <Input
                id={`${fieldPrefix}-file`}
                value={connectionForm.filePath}
                onChange={(event) =>
                  setConnectionForm((form) => ({
                    ...form,
                    filePath: event.target.value,
                  }))
                }
                placeholder="/data/warehouse.db"
              />
            </FormField>
          ) : (
            <>
              <div className="grid grid-cols-[1fr_110px] gap-3">
                <FormField
                  label="Server address"
                  htmlFor={`${fieldPrefix}-host`}
                >
                  <Input
                    id={`${fieldPrefix}-host`}
                    value={connectionForm.host}
                    onChange={(event) =>
                      setConnectionForm((form) => ({
                        ...form,
                        host: event.target.value,
                      }))
                    }
                    placeholder="db.example.com"
                  />
                </FormField>
                <FormField label="Port" htmlFor={`${fieldPrefix}-port`}>
                  <Input
                    id={`${fieldPrefix}-port`}
                    value={connectionForm.port}
                    onChange={(event) =>
                      setConnectionForm((form) => ({
                        ...form,
                        port: event.target.value,
                      }))
                    }
                  />
                </FormField>
              </div>
              <FormField label="Database name" htmlFor={`${fieldPrefix}-db`}>
                <Input
                  id={`${fieldPrefix}-db`}
                  value={connectionForm.database}
                  onChange={(event) =>
                    setConnectionForm((form) => ({
                      ...form,
                      database: event.target.value,
                    }))
                  }
                />
              </FormField>
              <div className="grid gap-3 sm:grid-cols-2">
                <FormField label="Username" htmlFor={`${fieldPrefix}-user`}>
                  <Input
                    id={`${fieldPrefix}-user`}
                    value={connectionForm.username}
                    autoComplete="off"
                    onChange={(event) =>
                      setConnectionForm((form) => ({
                        ...form,
                        username: event.target.value,
                      }))
                    }
                  />
                </FormField>
                <FormField label="Password" htmlFor={`${fieldPrefix}-pass`}>
                  <Input
                    id={`${fieldPrefix}-pass`}
                    type="password"
                    autoComplete="new-password"
                    value={connectionForm.password}
                    onChange={(event) =>
                      setConnectionForm((form) => ({
                        ...form,
                        password: event.target.value,
                      }))
                    }
                  />
                </FormField>
              </div>
            </>
          )}
        </div>
      </Modal>

      <Modal
        open={jobDialogOpen}
        title="New import"
        description="Copy a table into a dataset. You can run it by hand or on a schedule."
        onClose={() => setJobDialogOpen(false)}
        widthClassName="max-w-lg"
        footer={
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setJobDialogOpen(false)}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={createJob}
              disabled={
                busy === "create-job" ||
                !selectedConnectionId ||
                !jobForm.name.trim() ||
                !jobForm.table.trim()
              }
            >
              {busy === "create-job" ? "Creating…" : "Create import"}
            </Button>
          </div>
        }
      >
        <div className="space-y-4">
          {error && jobDialogOpen ? (
            <p role="alert" className="text-danger text-[13px]">
              {error}
            </p>
          ) : null}
          <FormField label="Database" htmlFor={`${fieldPrefix}-job-connection`}>
            <Select
              id={`${fieldPrefix}-job-connection`}
              value={selectedConnectionId}
              onChange={(event) => setSelectedConnectionId(event.target.value)}
            >
              {connections.map((connection) => (
                <option key={connection.id} value={connection.id}>
                  {connection.name}
                </option>
              ))}
            </Select>
          </FormField>
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField label="Table" htmlFor={`${fieldPrefix}-job-table`}>
              <Input
                id={`${fieldPrefix}-job-table`}
                value={jobForm.table}
                onChange={(event) =>
                  setJobForm((form) => ({ ...form, table: event.target.value }))
                }
                placeholder="orders"
              />
            </FormField>
            <FormField
              label="Name the dataset"
              htmlFor={`${fieldPrefix}-job-name`}
            >
              <Input
                id={`${fieldPrefix}-job-name`}
                value={jobForm.name}
                onChange={(event) =>
                  setJobForm((form) => ({ ...form, name: event.target.value }))
                }
                placeholder="Orders"
              />
            </FormField>
          </div>
          <FormField
            label="What each run brings in"
            htmlFor={`${fieldPrefix}-job-mode`}
            description={LOAD_MODE_HELP[jobForm.loadMode]}
          >
            <Select
              id={`${fieldPrefix}-job-mode`}
              value={jobForm.loadMode}
              onChange={(event) =>
                setJobForm((form) => ({
                  ...form,
                  loadMode: event.target.value as LoadMode,
                }))
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
              label="Column that marks new rows"
              htmlFor={`${fieldPrefix}-job-cursor`}
              description="Usually a date or a number that only goes up, such as updated_at."
            >
              <Input
                id={`${fieldPrefix}-job-cursor`}
                value={jobForm.cursorColumn}
                onChange={(event) =>
                  setJobForm((form) => ({
                    ...form,
                    cursorColumn: event.target.value,
                  }))
                }
                placeholder="updated_at"
              />
            </FormField>
          ) : null}
          {jobForm.loadMode === "incremental_merge" ? (
            <FormField
              label="Key column"
              htmlFor={`${fieldPrefix}-job-keys`}
              description="What identifies a row, such as id. Separate several with commas."
            >
              <Input
                id={`${fieldPrefix}-job-keys`}
                value={jobForm.primaryKeyColumns}
                onChange={(event) =>
                  setJobForm((form) => ({
                    ...form,
                    primaryKeyColumns: event.target.value,
                  }))
                }
                placeholder="id"
              />
            </FormField>
          ) : null}
          <details className="border-line rounded-xl border px-3 py-2">
            <summary className="text-ink-2 cursor-pointer text-[13px]">
              Advanced: clean the data while importing
            </summary>
            <div className="mt-3">
              <FormField
                label="Recipe steps"
                htmlFor={`${fieldPrefix}-job-shape`}
                description="Paste steps exported from the SQL page. Steps the database can do run there; the rest run in Pipewright."
              >
                <textarea
                  id={`${fieldPrefix}-job-shape`}
                  value={jobForm.shapeYaml}
                  onChange={(event) =>
                    setJobForm((form) => ({
                      ...form,
                      shapeYaml: event.target.value,
                    }))
                  }
                  rows={5}
                  spellCheck={false}
                  placeholder={
                    "steps:\n  - step: filter_rows\n    with:\n      conditions:\n        - {column: amount, operator: greater_than, value: 0}"
                  }
                  className="border-line bg-sunken text-ink w-full rounded-xl border px-3 py-2 font-mono text-[12px] transition outline-none focus:border-[color:var(--accent)]"
                />
              </FormField>
            </div>
          </details>
        </div>
      </Modal>
    </>
  );
}
