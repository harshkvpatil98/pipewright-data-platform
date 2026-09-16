"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { AuthUser } from "@platform/shared-types";
import { Button, EmptyState, Input, Select } from "@platform/shared-ui";

import { AppFrame } from "@/components/shell/app-frame";
import type { RibbonGroup } from "@/components/shell/ribbon";
import { useToast } from "@/components/providers/toast-provider";
import { Icon } from "@/components/ui/icon";
import { DataGrid } from "@/features/studio/grid/data-grid";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";

import { describeRun, formatDuration, sqlToRun } from "./editor-state";
import { exportName, toCsv } from "./result-export";
import { SchemaTree } from "./schema-tree";
import { SqlEditor } from "./sql-editor";
import type {
  Completion,
  Connection,
  ExplainResponse,
  PlanResponse,
  QueryRun,
  RunResponse,
  SavedQuery,
  SchemaResponse,
  StatementResult,
  TableInfo,
} from "./types";

type Props = {
  currentUser: AuthUser;
  projectId: string;
  projectName: string;
  projectEnvironment: string;
  connections: Connection[];
};

type Side = "schema" | "saved" | "history";

export function WorkbenchPage({
  currentUser,
  projectId,
  projectName,
  projectEnvironment,
  connections,
}: Props) {
  const toast = useToast();
  const base = `/projects/${projectId}/workbench`;

  const [connectionId, setConnectionId] = useState(connections[0]?.id ?? "");
  const [sql, setSql] = useState("");
  const [selection, setSelection] = useState({ start: 0, end: 0 });
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [result, setResult] = useState<RunResponse | null>(null);
  const [explain, setExplain] = useState<ExplainResponse | null>(null);
  const [activeTab, setActiveTab] = useState(0);
  const [running, setRunning] = useState(false);
  const [writeMode, setWriteMode] = useState(false);
  const [ddlMode, setDdlMode] = useState(false);
  const [parameters, setParameters] = useState<Record<string, string>>({});
  const [confirmation, setConfirmation] = useState<{ sql: string; statement: boolean } | null>(null);

  const [side, setSide] = useState<Side>("schema");
  const [schema, setSchema] = useState<SchemaResponse | null>(null);
  const [schemaLoading, setSchemaLoading] = useState(false);
  const [saved, setSaved] = useState<SavedQuery[]>([]);
  const [history, setHistory] = useState<QueryRun[]>([]);
  const [saveName, setSaveName] = useState("");

  const isProduction = projectEnvironment.toLowerCase() === "production";

  // ------------------------------------------------------------------ schema

  const loadSchema = useCallback(
    async (refresh = false) => {
      if (!connectionId) return;
      setSchemaLoading(true);
      try {
        setSchema(
          await apiFetch<SchemaResponse>(
            `${base}/schema/${connectionId}?refresh=${refresh ? "true" : "false"}`,
          ),
        );
      } catch (error) {
        toast.error("Could not read the schema", extractErrorMessage(error));
      } finally {
        setSchemaLoading(false);
      }
    },
    [base, connectionId, toast],
  );

  useEffect(() => {
    setSchema(null);
    void loadSchema();
  }, [loadSchema]);

  const expandTable = useCallback(
    async (table: TableInfo) => {
      if (!connectionId) return;
      try {
        const query = new URLSearchParams({ table: table.qualified });
        setSchema(await apiFetch<SchemaResponse>(`${base}/schema/${connectionId}?${query}`));
      } catch (error) {
        toast.error("Could not read the columns", extractErrorMessage(error));
      }
    },
    [base, connectionId, toast],
  );

  const loadSaved = useCallback(async () => {
    try {
      setSaved((await apiFetch<{ items: SavedQuery[] }>(`${base}/queries`)).items);
    } catch {
      setSaved([]);
    }
  }, [base]);

  const loadHistory = useCallback(async () => {
    try {
      setHistory((await apiFetch<{ items: QueryRun[] }>(`${base}/history?limit=50`)).items);
    } catch {
      setHistory([]);
    }
  }, [base]);

  useEffect(() => {
    void loadSaved();
    void loadHistory();
  }, [loadSaved, loadHistory]);

  // -------------------------------------------------------------- analysing

  useEffect(() => {
    if (!sql.trim()) {
      setPlan(null);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      apiFetch<PlanResponse>(`${base}/preview`, {
        method: "POST",
        body: JSON.stringify({ sql, allow_writes: writeMode, allow_ddl: ddlMode }),
      })
        .then((response) => {
          if (!cancelled) setPlan(response);
        })
        .catch(() => {
          // A half-typed script is the normal state while somebody is writing.
          if (!cancelled) setPlan(null);
        });
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [base, sql, writeMode, ddlMode]);

  const completionsFor = useCallback(
    async (text: string, offset: number): Promise<Completion[]> => {
      if (!connectionId) return [];
      const response = await apiFetch<{ items: Completion[] }>(
        `${base}/completions/${connectionId}`,
        { method: "POST", body: JSON.stringify({ sql: text, offset, limit: 40 }) },
      );
      return response.items;
    },
    [base, connectionId],
  );

  // ----------------------------------------------------------------- running

  const send = useCallback(
    async (text: string) => {
      setRunning(true);
      setExplain(null);
      try {
        const response = await apiFetch<RunResponse>(`${base}/run`, {
          method: "POST",
          body: JSON.stringify({
            connection_id: connectionId,
            sql: text,
            parameters,
            allow_writes: writeMode,
            allow_ddl: ddlMode,
          }),
        });
        setResult(response);
        setActiveTab(0);
        if (response.statements.some((statement) => statement.kind === "ddl")) {
          void loadSchema(true);
        }
        void loadHistory();
      } catch (error) {
        toast.error("Nothing ran", extractErrorMessage(error));
      } finally {
        setRunning(false);
        setConfirmation(null);
      }
    },
    [base, connectionId, parameters, writeMode, ddlMode, toast, loadSchema, loadHistory],
  );

  const run = useCallback(
    (statementOnly: boolean) => {
      if (!connectionId) {
        toast.error("No connection", "Choose a database connection first.");
        return;
      }
      const text = sqlToRun(sql, selection, plan?.statements ?? [], statementOnly ? "statement" : "script");
      if (!text.trim()) return;
      // A write gets a confirmation step, always. The plan already knows
      // whether one is needed, so the prompt is never in the way of a SELECT.
      if (plan?.verdict.needs_confirmation && writeMode) {
        setConfirmation({ sql: text, statement: statementOnly });
        return;
      }
      void send(text);
    },
    [connectionId, sql, selection, plan, writeMode, send, toast],
  );

  const askExplain = useCallback(async () => {
    if (!connectionId) return;
    const text = sqlToRun(sql, selection, plan?.statements ?? [], "statement");
    try {
      setExplain(await apiFetch<ExplainResponse>(`${base}/explain`, {
        method: "POST",
        body: JSON.stringify({ connection_id: connectionId, sql: text, parameters }),
      }));
      setActiveTab(-1);
    } catch (error) {
      toast.error("No plan available", extractErrorMessage(error));
    }
  }, [base, connectionId, sql, selection, plan, parameters, toast]);

  const downloadCsv = useCallback(() => {
    if (!shownRef.current) return;
    const statement = shownRef.current;
    const url = URL.createObjectURL(
      new Blob([toCsv(statement.columns, statement.rows)], { type: "text/csv" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = exportName(statement.summary, "csv");
    anchor.click();
    URL.revokeObjectURL(url);
  }, []);

  const sendToNotebook = useCallback(async () => {
    const text = sqlToRun(sql, selection, plan?.statements ?? [], "statement");
    if (!text.trim()) return;
    try {
      const created = await apiFetch<{ id: string; name: string }>(`${base}/notebooks`, {
        method: "POST",
        body: JSON.stringify({
          name: `From the workbench — ${new Date().toLocaleString()}`,
          connection_id: connectionId || null,
          cells: [{ kind: "sql", source: text, output_name: "result" }],
        }),
      });
      toast.success(
        "Opened as a notebook",
        `“${created.name}” has this query as its first cell, ready to build on.`,
      );
      window.location.href = `/projects/${projectId}/notebooks`;
    } catch (error) {
      toast.error("Could not create the notebook", extractErrorMessage(error));
    }
  }, [base, sql, selection, plan, connectionId, projectId, toast]);

  const save = useCallback(async () => {
    const name = saveName.trim();
    if (!name || !sql.trim()) return;
    try {
      await apiFetch(`${base}/queries`, {
        method: "POST",
        body: JSON.stringify({ name, sql, connection_id: connectionId || null }),
      });
      toast.success("Saved", `“${name}” is in this project's saved queries.`);
      setSaveName("");
      void loadSaved();
    } catch (error) {
      toast.error("Could not save", extractErrorMessage(error));
    }
  }, [base, saveName, sql, connectionId, toast, loadSaved]);

  // ------------------------------------------------------------------ chrome

  const statements = result?.statements.filter((statement) => !statement.skipped) ?? [];
  const shown: StatementResult | undefined = statements[activeTab];
  // Held in a ref so the export callback reads what is on screen now rather
  // than whatever was showing when the callback was created.
  const shownRef = useRef<StatementResult | undefined>(undefined);
  shownRef.current = shown;

  const insertAtCaret = useCallback(
    (text: string) => {
      setSql((current) => current.slice(0, selection.start) + text + current.slice(selection.end));
    },
    [selection],
  );

  const ribbon: RibbonGroup[] = [
    {
      id: "run",
      label: "Run",
      actions: [
        {
          id: "run-all",
          label: running ? "Running…" : "Run",
          icon: "play",
          prominent: true,
          hint: "⌘↵ — or the selection, if there is one",
          disabled: running || !connectionId || !sql.trim(),
          onClick: () => run(false),
        },
        {
          id: "run-statement",
          label: "Run statement",
          icon: "play",
          hint: "⌘⇧↵ — just the one under the cursor",
          disabled: running || !connectionId || !sql.trim(),
          onClick: () => run(true),
        },
        {
          id: "explain",
          label: "Explain",
          icon: "sigma",
          hint: "How the database would run it. Nothing is executed.",
          disabled: running || !connectionId || !sql.trim(),
          onClick: () => void askExplain(),
        },
      ],
    },
    {
      id: "result",
      label: "Result",
      actions: [
        {
          id: "csv",
          label: "Download CSV",
          icon: "download",
          hint: "The rows on screen, as a file",
          disabled: !shown || shown.columns.length === 0,
          onClick: downloadCsv,
        },
        {
          id: "notebook",
          label: "Open as notebook",
          icon: "book",
          hint: "Carry this query on into Python and recipe cells",
          disabled: !sql.trim(),
          onClick: () => void sendToNotebook(),
        },
      ],
    },
    {
      id: "mode",
      label: "Mode",
      actions: [
        {
          id: "writes",
          label: writeMode ? "Write mode on" : "Read-only",
          icon: writeMode ? "warning" : "shield",
          hint:
            currentUser.role === "admin"
              ? "Writing to a source database bypasses every review the platform applies."
              : "Write mode needs the admin role.",
          disabled: currentUser.role !== "admin",
          onClick: () => {
            setWriteMode((current) => !current);
            setDdlMode(false);
          },
        },
        {
          id: "ddl",
          label: ddlMode ? "Structure changes on" : "Structure changes off",
          icon: "warning",
          disabled: !writeMode || currentUser.role !== "admin",
          onClick: () => setDdlMode((current) => !current),
        },
      ],
    },
  ];

  if (connections.length === 0) {
    return (
      <AppFrame
        currentUser={currentUser}
        crumbs={[
          { label: "Projects", href: "/projects" },
          { label: projectName, href: `/projects/${projectId}` },
          { label: "SQL workbench" },
        ]}
      >
        <EmptyState
          title="No database connections in this project"
          description="The workbench runs SQL against a live database, so it needs one to run against."
          action={
            <a
              href={`/projects/${projectId}/extraction`}
              className="inline-flex items-center rounded-full border border-[color:var(--accent-soft)] bg-[color:var(--accent-faint)] px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-ink hover:brightness-110"
            >
              Add a connection
            </a>
          }
        />
      </AppFrame>
    );
  }

  return (
    <AppFrame
      currentUser={currentUser}
      crumbs={[
        { label: "Projects", href: "/projects" },
        { label: projectName, href: `/projects/${projectId}` },
        { label: "SQL workbench" },
      ]}
      ribbon={ribbon}
      statusItems={[
        { id: "mode", label: "Mode", value: plan?.policy.description ?? "read-only" },
        { id: "statements", label: "Statements", value: String(plan?.statements.length ?? 0) },
        {
          id: "last",
          label: "Last run",
          value: result ? formatDuration(result.duration_ms) : "—",
        },
        { id: "env", label: "Environment", value: projectEnvironment },
      ]}
    >
      <div className="flex h-full min-h-0">
        {/* ------------------------------------------------------ side panel */}
        <aside className="flex w-64 shrink-0 flex-col">
          <div className="flex border-b border-line" role="tablist" aria-label="Workbench panels">
            {(["schema", "saved", "history"] as Side[]).map((panel) => (
              <button
                key={panel}
                type="button"
                role="tab"
                aria-selected={side === panel}
                onClick={() => setSide(panel)}
                className={cx(
                  "flex-1 px-2 py-2 text-[11px] uppercase tracking-[0.12em] transition",
                  side === panel
                    ? "border-b-2 border-[color:var(--accent)] text-ink"
                    : "text-muted hover:text-ink",
                )}
              >
                {panel}
              </button>
            ))}
          </div>

          {side === "schema" ? (
            <SchemaTree
              schema={schema}
              loading={schemaLoading}
              onExpand={(table) => void expandTable(table)}
              onInsert={insertAtCaret}
              onRefresh={() => void loadSchema(true)}
            />
          ) : null}

          {side === "saved" ? (
            <div className="min-h-0 flex-1 overflow-y-auto p-2">
              {saved.length === 0 ? (
                <p className="px-1 py-2 text-xs text-muted">Nothing saved yet.</p>
              ) : null}
              <ul className="flex flex-col gap-1">
                {saved.map((entry) => (
                  <li key={entry.id}>
                    <button
                      type="button"
                      onClick={() => setSql(entry.sql)}
                      className="w-full rounded-lg px-2 py-1.5 text-left text-xs text-ink transition hover:bg-sunken"
                    >
                      <span className="block truncate">{entry.name}</span>
                      <span className="block text-[10px] text-muted">
                        run {entry.run_count} time{entry.run_count === 1 ? "" : "s"}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              <div className="mt-3 flex flex-col gap-2 border-t border-line pt-3">
                <Input
                  value={saveName}
                  onChange={(event) => setSaveName(event.target.value)}
                  placeholder="Save this as…"
                  className="h-8 text-xs"
                  aria-label="Name for the saved query"
                />
                <Button size="sm" disabled={!saveName.trim() || !sql.trim()} onClick={() => void save()}>
                  Save query
                </Button>
              </div>
            </div>
          ) : null}

          {side === "history" ? (
            <div className="min-h-0 flex-1 overflow-y-auto p-2">
              {history.length === 0 ? (
                <p className="px-1 py-2 text-xs text-muted">Nothing run yet.</p>
              ) : null}
              <ul className="flex flex-col gap-1">
                {history.map((entry) => (
                  <li key={entry.id}>
                    <button
                      type="button"
                      onClick={() => setSql(entry.sql)}
                      className="w-full rounded-lg px-2 py-1.5 text-left transition hover:bg-sunken"
                    >
                      <span className="block truncate font-mono text-[11px] text-ink-2">
                        {entry.sql.replace(/\s+/g, " ").slice(0, 60)}
                      </span>
                      <span
                        className={cx(
                          "block text-[10px]",
                          entry.succeeded ? "text-muted" : "text-[color:var(--danger)]",
                        )}
                      >
                        {entry.succeeded
                          ? `${entry.rows_returned} rows · ${formatDuration(entry.duration_ms)}`
                          : "failed"}
                        {entry.wrote ? " · write" : ""}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </aside>

        {/* --------------------------------------------------------- editor */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center gap-2 border-b border-line px-3 py-2">
            <Select
              value={connectionId}
              onChange={(event) => setConnectionId(event.target.value)}
              className="h-8 w-64 text-xs"
              aria-label="Connection"
            >
              {connections.map((connection) => (
                <option key={connection.id} value={connection.id}>
                  {connection.name} ({connection.connector_type})
                </option>
              ))}
            </Select>
            {isProduction ? (
              <span className="flex items-center gap-1.5 rounded-full border border-[color:var(--danger-line)] bg-[color:var(--danger-soft)] px-2.5 py-1 text-[11px] text-ink">
                <Icon name="warning" className="h-3 w-3" />
                production
              </span>
            ) : null}
            {writeMode ? (
              <span className="flex items-center gap-1.5 rounded-full border border-[color:var(--warning-line)] bg-[color:var(--warning-soft)] px-2.5 py-1 text-[11px] text-ink">
                <Icon name="warning" className="h-3 w-3" />
                {ddlMode ? "writes and structure changes" : "writes"}
              </span>
            ) : null}
          </div>

          <div className="min-h-0 flex-[3]">
            <SqlEditor
              value={sql}
              onChange={(next, range) => {
                setSql(next);
                setSelection(range);
              }}
              onRun={() => run(false)}
              onRunStatement={() => run(true)}
              completionsFor={completionsFor}
              disabled={!connectionId}
            />
          </div>

          {plan && plan.parameters.length > 0 ? (
            <div className="flex flex-wrap items-end gap-2 border-t border-line px-3 py-2">
              {plan.parameters.map((name) => (
                <label key={name} className="flex flex-col gap-1">
                  <span className="text-[10px] uppercase tracking-[0.12em] text-muted">{name}</span>
                  <Input
                    value={parameters[name] ?? ""}
                    onChange={(event) =>
                      setParameters((current) => ({ ...current, [name]: event.target.value }))
                    }
                    className="h-8 w-40 text-xs"
                  />
                </label>
              ))}
            </div>
          ) : null}

          {plan && !plan.verdict.allowed ? (
            <p className="border-t border-line bg-[color:var(--danger-soft)] px-3 py-2 text-xs text-ink">
              {plan.verdict.reason}
            </p>
          ) : null}
          {plan?.verdict.warnings.map((warning) => (
            <p
              key={warning}
              className="border-t border-line bg-[color:var(--warning-soft)] px-3 py-2 text-xs text-ink"
            >
              {warning}
            </p>
          ))}

          {/* -------------------------------------------------------- results */}
          <div className="flex min-h-0 flex-[4] flex-col border-t border-line">
            {explain ? (
              <div className="min-h-0 flex-1 overflow-auto p-3">
                <div className="mb-2 flex items-baseline gap-3">
                  <h2 className="text-xs uppercase tracking-[0.14em] text-muted">
                    Query plan · {explain.dialect}
                  </h2>
                  {explain.estimated_rows !== null ? (
                    <span className="text-xs text-muted">
                      about {explain.estimated_rows.toLocaleString()} rows
                    </span>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => setExplain(null)}
                    className="ml-auto text-xs text-muted hover:text-ink"
                  >
                    Close
                  </button>
                </div>
                {explain.notes.map((note) => (
                  <p key={note} className="mb-2 rounded-lg border border-line bg-sunken px-3 py-2 text-xs text-ink">
                    {note}
                  </p>
                ))}
                <pre className="overflow-x-auto font-mono text-[11px] leading-5 text-ink-2">
                  {explain.text}
                </pre>
              </div>
            ) : result ? (
              <>
                <div className="flex items-center gap-1 overflow-x-auto border-b border-line px-2" role="tablist">
                  {statements.map((statement, index) => (
                    <button
                      key={statement.index}
                      type="button"
                      role="tab"
                      aria-selected={index === activeTab}
                      onClick={() => setActiveTab(index)}
                      className={cx(
                        "shrink-0 px-3 py-1.5 text-[11px] transition",
                        index === activeTab
                          ? "border-b-2 border-[color:var(--accent)] text-ink"
                          : "text-muted hover:text-ink",
                        statement.error ? "text-[color:var(--danger)]" : "",
                      )}
                      title={statement.summary}
                    >
                      {statement.index}. {statement.error ? "failed" : statement.columns.length ? `${statement.row_count} rows` : `${statement.rows_affected ?? 0} changed`}
                    </button>
                  ))}
                  <span className="ml-auto shrink-0 px-3 text-[11px] tabular-nums text-muted">
                    {describeRun(result)}
                  </span>
                </div>

                <div className="min-h-0 flex-1">
                  {shown?.error ? (
                    <p className="m-3 rounded-lg border border-[color:var(--danger-line)] bg-[color:var(--danger-soft)] px-3 py-2 font-mono text-xs text-ink">
                      {shown.error}
                    </p>
                  ) : shown && shown.columns.length > 0 ? (
                    <>
                      <DataGrid
                        columns={shown.columns.map((name) => ({ name }))}
                        rows={shown.rows}
                        className="h-full"
                        emptyMessage="This query returned no rows."
                      />
                      {shown.truncated ? (
                        <p className="border-t border-line px-3 py-1 text-[11px] text-muted">
                          Showing the first {shown.rows.length.toLocaleString()} rows. Add a LIMIT
                          to see a specific part.
                        </p>
                      ) : null}
                    </>
                  ) : (
                    <p className="p-3 text-xs text-muted">
                      {shown
                        ? `${shown.rows_affected ?? 0} row(s) changed in ${formatDuration(shown.duration_ms)}.`
                        : "No results."}
                    </p>
                  )}
                </div>
              </>
            ) : (
              <p className="p-4 text-xs text-muted">
                Results appear here. ⌘↵ runs the script, ⌘⇧↵ runs the statement under the cursor.
              </p>
            )}
          </div>
        </div>
      </div>

      {confirmation ? (
        <ConfirmWrite
          environment={projectEnvironment}
          warnings={plan?.verdict.warnings ?? []}
          onCancel={() => setConfirmation(null)}
          onConfirm={() => void send(confirmation.sql)}
        />
      ) : null}
    </AppFrame>
  );
}

function ConfirmWrite({
  environment,
  warnings,
  onCancel,
  onConfirm,
}: {
  environment: string;
  warnings: string[];
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const [typed, setTyped] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const production = environment.toLowerCase() === "production";
  const required = production ? environment.toLowerCase() : "";

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[color:var(--scrim)] p-4">
      <div className="w-full max-w-lg rounded-2xl border border-line bg-surface p-6" role="dialog" aria-modal="true">
        <h2 className="text-base font-medium text-ink">This changes data</h2>
        <p className="mt-2 text-sm text-muted">
          The workbench writes directly to the source database. Nothing here goes through the
          review, lineage or audit that a pipeline does.
        </p>
        {warnings.map((warning) => (
          <p key={warning} className="mt-3 rounded-lg border border-[color:var(--warning-line)] bg-[color:var(--warning-soft)] px-3 py-2 text-xs text-ink">
            {warning}
          </p>
        ))}
        {production ? (
          <label className="mt-4 flex flex-col gap-1">
            <span className="text-xs uppercase tracking-[0.14em] text-muted">
              Type “production” to confirm
            </span>
            <Input ref={inputRef} value={typed} onChange={(event) => setTyped(event.target.value)} />
          </label>
        ) : null}
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant="danger"
            disabled={production && typed.trim().toLowerCase() !== required}
            onClick={onConfirm}
          >
            Run it
          </Button>
        </div>
      </div>
    </div>
  );
}
