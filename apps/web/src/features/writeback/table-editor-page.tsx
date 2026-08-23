"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { AuthUser } from "@platform/shared-types";
import { Button, EmptyState, Input, Select } from "@platform/shared-ui";

import { AppFrame } from "@/components/shell/app-frame";
import type { RibbonGroup } from "@/components/shell/ribbon";
import { useToast } from "@/components/providers/toast-provider";
import { Icon } from "@/components/ui/icon";
import { DataGrid, type GridColumn } from "@/features/studio/grid/data-grid";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";

import {
  addInsert,
  coerceValue,
  describe as describeTray,
  discardRow,
  emptyTray,
  isEmpty,
  isInsertId,
  keyOf,
  overlayRows,
  stageCell,
  stageColumn,
  stageDelete,
  stageInsertCell,
  toPayload,
  trayCount,
  type CellValue,
  type Tray,
} from "./change-tray";

type Connection = { id: string; name: string; connector_type: string; status: string };
type DiscoveredTable = { schema_name: string | null; name: string; qualified_name: string };

type RowIdentity = {
  kind: string;
  columns: string[];
  reason: string;
  caveat: string;
  usable: boolean;
  durable: boolean;
};

type TableShape = {
  table: string;
  table_schema: string | null;
  columns: string[];
  nullable: string[];
  types: Record<string, string>;
  identity: RowIdentity;
  editable: boolean;
};

type RowPage = {
  columns: string[];
  rows: Record<string, unknown>[];
  total: number;
  offset: number;
  key_columns: string[];
};

type Statement = {
  sql: string;
  describes: string;
  kind: string;
  expected_rows: number | null;
  actual_rows: number | null;
  irreversible: boolean;
};

type Plan = {
  identity: RowIdentity;
  statements: Statement[];
  rows_affected: number;
  table_rows: number;
  blast_radius: string;
  needs_confirmation: boolean;
  has_irreversible: boolean;
  conflicts: string[];
  warnings: string[];
  ddl_is_not_transactional: boolean;
};

const PAGE_SIZE = 100;

/** Types offered when adding a column. Deliberately short and portable. */
const COLUMN_TYPES = ["text", "integer", "bigint", "numeric", "boolean", "date", "timestamp"];

type Props = {
  currentUser: AuthUser;
  projectId: string;
  projectName: string;
  projectEnvironment: string;
  connections: Connection[];
};

export function TableEditorPage({
  currentUser,
  projectId,
  projectName,
  projectEnvironment,
  connections,
}: Props) {
  const toast = useToast();
  const base = `/projects/${projectId}/writeback`;

  const [connectionId, setConnectionId] = useState(connections[0]?.id ?? "");
  const [tables, setTables] = useState<DiscoveredTable[]>([]);
  const [tableName, setTableName] = useState("");
  const [shape, setShape] = useState<TableShape | null>(null);
  const [page, setPage] = useState<RowPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [tray, setTray] = useState<Tray>(emptyTray());
  const [plan, setPlan] = useState<Plan | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [focusedRow, setFocusedRow] = useState(0);
  const [focusedColumnIndex, setFocusedColumnIndex] = useState(0);
  const [columnFormOpen, setColumnFormOpen] = useState(false);
  const [newColumn, setNewColumn] = useState({ name: "", type: "text" });

  const selectedTable = useMemo(
    () => tables.find((item) => item.qualified_name === tableName) ?? null,
    [tables, tableName],
  );

  // ------------------------------------------------------------------ loading

  useEffect(() => {
    if (!connectionId) return;
    let cancelled = false;
    setTables([]);
    setTableName("");
    setShape(null);
    setPage(null);
    apiFetch<{ items: DiscoveredTable[] }>(
      `/projects/${projectId}/extraction/connections/${connectionId}/tables`,
    )
      .then((response) => {
        if (!cancelled) setTables(response.items);
      })
      .catch((caught) => {
        if (!cancelled) setError(extractErrorMessage(caught));
      });
    return () => {
      cancelled = true;
    };
  }, [connectionId, projectId]);

  const loadTable = useCallback(
    async (nextOffset: number) => {
      if (!connectionId || !selectedTable) return;
      setLoading(true);
      setError(null);
      const query = new URLSearchParams({ table: selectedTable.name });
      if (selectedTable.schema_name) query.set("table_schema", selectedTable.schema_name);
      try {
        const nextShape = await apiFetch<TableShape>(
          `${base}/tables/${connectionId}?${query.toString()}`,
        );
        setShape(nextShape);
        if (!nextShape.editable) {
          setPage(null);
          return;
        }
        const rowQuery = new URLSearchParams(query);
        rowQuery.set("limit", String(PAGE_SIZE));
        rowQuery.set("offset", String(nextOffset));
        setPage(await apiFetch<RowPage>(`${base}/rows/${connectionId}?${rowQuery.toString()}`));
        setOffset(nextOffset);
      } catch (caught) {
        setError(extractErrorMessage(caught));
        setPage(null);
      } finally {
        setLoading(false);
      }
    },
    [base, connectionId, selectedTable],
  );

  useEffect(() => {
    if (!selectedTable) return;
    // Switching tables abandons staged work rather than carrying edits that
    // name columns the new table does not have.
    setTray(emptyTray());
    setPlan(null);
    void loadTable(0);
  }, [loadTable, selectedTable]);

  // ------------------------------------------------------------------ editing

  const keyColumns = page?.key_columns ?? [];
  const painted = useMemo(
    () => (page ? overlayRows(page.rows, keyColumns, tray) : []),
    [page, keyColumns, tray],
  );

  const rowStates = useMemo(() => {
    const states: Record<number, "edited" | "deleted" | "new"> = {};
    painted.forEach((entry, index) => {
      if (entry.state !== "clean") states[index] = entry.state;
    });
    return states;
  }, [painted]);

  const gridColumns: GridColumn[] = useMemo(() => {
    if (!shape) return [];
    const added = tray.columns
      .filter((change) => change.kind === "add_column")
      .map((change) => ({ name: change.column, type: change.columnType }));
    const dropped = new Set(
      tray.columns.filter((change) => change.kind === "drop_column").map((c) => c.column),
    );
    return [
      ...shape.columns
        .filter((name) => !dropped.has(name))
        .map((name) => ({ name, type: shape.types[name] })),
      ...added,
    ];
  }, [shape, tray.columns]);

  const handleEditCell = useCallback(
    (address: { row: number; column: number }, raw: string) => {
      const target = painted[address.row];
      const column = gridColumns[address.column];
      if (!target || !column) return;
      if (target.state === "deleted") {
        toast.error("That row is staged for deletion", "Undo the deletion before editing it.");
        return;
      }
      if (keyColumns.includes(column.name) && !isInsertId(target.rowId)) {
        toast.error(
          `${column.name} identifies the row`,
          "Delete the row and insert a replacement instead of changing its key.",
        );
        return;
      }
      const value = coerceValue(raw, column.type);
      if (isInsertId(target.rowId)) {
        setTray((current) => stageInsertCell(current, target.rowId, column.name, value));
        return;
      }
      const stored = page?.rows[address.row];
      setTray((current) =>
        stageCell(current, {
          key: keyOf(target.row, keyColumns),
          column: column.name,
          value,
          original: (stored ? stored[column.name] : null) as CellValue,
          hasOriginal: stored !== undefined && column.name in stored,
        }),
      );
    },
    [gridColumns, keyColumns, page, painted, toast],
  );

  const focused = painted[focusedRow] ?? null;
  const focusedColumn = gridColumns[focusedColumnIndex]?.name ?? null;

  const toggleRow = useCallback(() => {
    if (!focused) return;
    // One control, because "delete" and "undo delete" apply to the same row and
    // two buttons would leave one of them wrong at all times.
    if (isInsertId(focused.rowId) || focused.state === "deleted") {
      setTray((current) => discardRow(current, focused.rowId));
      return;
    }
    setTray((current) => stageDelete(current, keyOf(focused.row, keyColumns)));
  }, [focused, keyColumns]);

  const dropFocusedColumn = useCallback(
    (column: string) => {
      setTray((current) => stageColumn(current, { kind: "drop_column", column }));
    },
    [],
  );

  // ---------------------------------------------------------------- reviewing

  const review = useCallback(async () => {
    if (!shape || !connectionId || isEmpty(tray)) return;
    setBusy(true);
    setPlan(null);
    let created: { id: string } | null = null;
    try {
      created = await apiFetch<{ id: string }>(`${base}/change-sets`, {
        method: "POST",
        body: JSON.stringify({
          connection_id: connectionId,
          table_name: shape.table,
          table_schema: shape.table_schema,
          name: `Edit ${shape.table}`,
        }),
      });
      await apiFetch(`${base}/change-sets/${created.id}/edits`, {
        method: "POST",
        body: JSON.stringify({ edits: toPayload(tray) }),
      });
      const planned = await apiFetch<Plan>(`${base}/change-sets/${created.id}/plan`, {
        method: "POST",
      });
      setPlan(planned);
      setChangeSetId(created.id);
      setConfirmation("");
      setReviewing(true);
    } catch (caught) {
      // The draft exists on the server by the time staging or planning can
      // fail. Leaving it behind would fill the change list with abandoned
      // attempts that nobody can explain later.
      if (created) {
        await apiFetch(`${base}/change-sets/${created.id}/discard`, { method: "POST" }).catch(
          () => undefined,
        );
      }
      toast.error("Could not prepare the change", extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }, [base, connectionId, shape, toast, tray]);

  const [changeSetId, setChangeSetId] = useState<string | null>(null);

  const commit = useCallback(async () => {
    if (!changeSetId) return;
    setBusy(true);
    try {
      const result = await apiFetch<{ rows_affected: number; statements_run: number }>(
        `${base}/change-sets/${changeSetId}/commit`,
        {
          method: "POST",
          body: JSON.stringify({
            confirm_table_name: plan?.needs_confirmation ? confirmation : null,
          }),
        },
      );
      toast.success(
        "Applied",
        `${result.rows_affected} row(s) changed by ${result.statements_run} statement(s).`,
      );
      setTray(emptyTray());
      setReviewing(false);
      setPlan(null);
      setChangeSetId(null);
      await loadTable(offset);
    } catch (caught) {
      toast.error("Nothing was written", extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }, [base, changeSetId, confirmation, loadTable, offset, plan, toast]);

  const discardChangeSet = useCallback(async () => {
    if (changeSetId) {
      // The draft was already created server-side; leaving it there would
      // clutter the change list with abandoned edits.
      await apiFetch(`${base}/change-sets/${changeSetId}/discard`, { method: "POST" }).catch(
        () => undefined,
      );
    }
    setReviewing(false);
    setPlan(null);
    setChangeSetId(null);
  }, [base, changeSetId]);

  const downloadMigration = useCallback(async () => {
    if (!changeSetId) return;
    try {
      const file = await apiFetch<{ filename: string; sql: string }>(
        `${base}/change-sets/${changeSetId}/migration`,
      );
      const url = URL.createObjectURL(new Blob([file.sql], { type: "text/plain" }));
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = file.filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (caught) {
      toast.error("Could not export the migration", extractErrorMessage(caught));
    }
  }, [base, changeSetId, toast]);

  // ------------------------------------------------------------------ chrome

  const pending = trayCount(tray);
  const isProduction = projectEnvironment.toLowerCase() === "production";

  const ribbon: RibbonGroup[] = [
    {
      id: "rows",
      label: "Rows",
      actions: [
        {
          id: "add-row",
          label: "New row",
          icon: "plus",
          onClick: () => setTray((current) => addInsert(current)),
          disabled: !shape?.editable,
        },
        {
          id: "delete-row",
          label:
            focused && (isInsertId(focused.rowId) || focused.state === "deleted")
              ? "Undo this row"
              : "Delete row",
          icon: "trash",
          hint: "Acts on the row the cursor is in",
          onClick: toggleRow,
          disabled: !focused,
        },
        {
          id: "refresh",
          label: "Reload",
          icon: "refresh",
          onClick: () => void loadTable(offset),
          disabled: !shape?.editable || loading,
        },
      ],
    },
    {
      id: "columns",
      label: "Columns",
      actions: [
        {
          id: "add-column",
          label: "Add column",
          icon: "plus",
          onClick: () => setColumnFormOpen(true),
          disabled: !shape?.editable,
        },
        {
          id: "drop-column",
          label: "Drop column",
          icon: "trash",
          hint: focusedColumn ? `Drops ${focusedColumn}` : "Put the cursor in a column first",
          onClick: () => focusedColumn && dropFocusedColumn(focusedColumn),
          disabled: !focusedColumn || keyColumns.includes(focusedColumn ?? ""),
        },
      ],
    },
    {
      id: "apply",
      label: "Apply",
      actions: [
        {
          id: "review",
          label: pending ? `Review ${pending} change${pending === 1 ? "" : "s"}` : "Review",
          icon: "check",
          onClick: () => void review(),
          disabled: pending === 0 || busy,
        },
        {
          id: "discard-all",
          label: "Discard all",
          icon: "trash",
          onClick: () => setTray(emptyTray()),
          disabled: pending === 0,
        },
      ],
    },
  ];

  return (
    <AppFrame
      currentUser={currentUser}
      crumbs={[
        { label: "Projects", href: "/projects" },
        { label: projectName, href: `/projects/${projectId}` },
        { label: "Table editor" },
      ]}
      ribbon={ribbon}
      statusItems={[
        { id: "table", label: "Table", value: shape?.table ?? "none" },
        { id: "rows", label: "Rows", value: page ? page.total.toLocaleString() : "—" },
        { id: "pending", label: "Staged", value: String(pending) },
        { id: "env", label: "Environment", value: projectEnvironment },
      ]}
      inspector={{
        title: "Staged changes",
        content: <TrayPanel tray={tray} onDiscardAll={() => setTray(emptyTray())} />,
      }}
    >
      <div className="flex h-full flex-col gap-4">
        {isProduction ? (
          <div className="flex items-center gap-3 rounded-xl border border-[color:var(--danger-line)] bg-[color:var(--danger-soft)] px-4 py-3 text-sm text-ink">
            <Icon name="warning" className="h-4 w-4 shrink-0" />
            <span>
              This project is marked <strong>production</strong>. Changes here are applied to the
              live database as soon as you commit them.
            </span>
          </div>
        ) : null}

        {connections.length === 0 ? (
          <EmptyState
            title="No database connections in this project"
            description={
              "The table editor writes to a live database, so it needs a database " +
              "connection to write to. Files and uploaded datasets are edited in the " +
              "Studio instead, where every change becomes a replayable step rather " +
              "than a rewrite of the original file."
            }
            action={
              <a
                href={`/projects/${projectId}/extraction`}
                className="inline-flex items-center rounded-full border border-[color:var(--accent-soft)] bg-[color:var(--accent-faint)] px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-ink hover:brightness-110"
              >
                Add a connection
              </a>
            }
          />
        ) : null}

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.14em] text-muted">
            Connection
            <Select value={connectionId} onChange={(event) => setConnectionId(event.target.value)}>
              {connections.length === 0 ? <option value="">No connections</option> : null}
              {connections.map((connection) => (
                <option key={connection.id} value={connection.id}>
                  {connection.name} ({connection.connector_type})
                </option>
              ))}
            </Select>
          </label>
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.14em] text-muted">
            Table
            <Select value={tableName} onChange={(event) => setTableName(event.target.value)}>
              <option value="">Choose a table…</option>
              {tables.map((table) => (
                <option key={table.qualified_name} value={table.qualified_name}>
                  {table.qualified_name}
                </option>
              ))}
            </Select>
          </label>
        </div>

        {error ? (
          <p className="rounded-xl border border-[color:var(--danger-line)] bg-[color:var(--danger-soft)] px-4 py-3 text-sm text-ink">
            {error}
          </p>
        ) : null}

        {shape ? <IdentityBanner identity={shape.identity} /> : null}

        {columnFormOpen ? (
          <form
            className="flex flex-wrap items-end gap-3 rounded-xl border border-line bg-surface px-4 py-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (!newColumn.name.trim()) return;
              setTray((current) =>
                stageColumn(current, {
                  kind: "add_column",
                  column: newColumn.name.trim(),
                  columnType: newColumn.type,
                }),
              );
              setNewColumn({ name: "", type: "text" });
              setColumnFormOpen(false);
            }}
          >
            <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.14em] text-muted">
              Column name
              <Input
                value={newColumn.name}
                onChange={(event) => setNewColumn({ ...newColumn, name: event.target.value })}
                autoFocus
              />
            </label>
            <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.14em] text-muted">
              Type
              <Select
                value={newColumn.type}
                onChange={(event) => setNewColumn({ ...newColumn, type: event.target.value })}
              >
                {COLUMN_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </Select>
            </label>
            <Button type="submit">Stage column</Button>
            <Button type="button" variant="ghost" onClick={() => setColumnFormOpen(false)}>
              Cancel
            </Button>
          </form>
        ) : null}

        {shape && !shape.editable ? (
          <p className="rounded-xl border border-line bg-surface px-4 py-6 text-sm text-muted">
            {shape.identity.reason}
          </p>
        ) : null}

        {page ? (
          <>
            <DataGrid
              columns={gridColumns}
              rows={painted.map((entry) => entry.row)}
              onEditCell={handleEditCell}
              onFocusChange={(address) => {
                setFocusedRow(address.row);
                setFocusedColumnIndex(address.column);
              }}
              rowStates={rowStates}
              className="min-h-[24rem] flex-1"
              emptyMessage="This table has no rows yet. Use “New row” to add one."
            />
            <div className="flex items-center justify-between text-xs text-muted">
              <span>
                Rows {page.total === 0 ? 0 : offset + 1}–
                {Math.min(offset + page.rows.length, page.total)} of {page.total.toLocaleString()}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={offset === 0 || loading}
                  onClick={() => void loadTable(Math.max(0, offset - PAGE_SIZE))}
                >
                  Previous
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={offset + PAGE_SIZE >= page.total || loading}
                  onClick={() => void loadTable(offset + PAGE_SIZE)}
                >
                  Next
                </Button>
              </div>
            </div>

          </>
        ) : null}

        {reviewing && plan ? (
          <ReviewDialog
            plan={plan}
            tableName={shape?.table ?? ""}
            confirmation={confirmation}
            onConfirmationChange={setConfirmation}
            busy={busy}
            onCommit={() => void commit()}
            onCancel={() => void discardChangeSet()}
            onDownload={() => void downloadMigration()}
          />
        ) : null}
      </div>
    </AppFrame>
  );
}

function IdentityBanner({ identity }: { identity: RowIdentity }) {
  if (!identity.usable) return null;
  const tone = identity.durable ? "border-line bg-surface" : "border-[color:var(--warning-line)] bg-[color:var(--warning-soft)]";
  return (
    <div className={cx("rounded-xl border px-4 py-3 text-sm text-ink", tone)}>
      <span className="text-muted">Rows addressed by </span>
      <strong>{identity.columns.join(", ")}</strong>
      <span className="text-muted"> — {identity.reason}</span>
      {identity.caveat ? <p className="mt-1 text-xs text-muted">{identity.caveat}</p> : null}
    </div>
  );
}

function TrayPanel({ tray, onDiscardAll }: { tray: Tray; onDiscardAll: () => void }) {
  const lines = describeTray(tray);
  if (lines.length === 0) {
    return (
      <p className="text-sm text-muted">
        Nothing staged. Edits are collected here and nothing is written until you review and
        commit them.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-col gap-2 text-xs">
        {lines.map((line) => (
          <li key={`${line.kind}:${line.id}`} className="rounded-lg border border-line bg-sunken px-3 py-2 text-ink">
            {line.text}
          </li>
        ))}
      </ul>
      <Button variant="ghost" size="sm" onClick={onDiscardAll}>
        Discard all
      </Button>
    </div>
  );
}

function ReviewDialog({
  plan,
  tableName,
  confirmation,
  onConfirmationChange,
  busy,
  onCommit,
  onCancel,
  onDownload,
}: {
  plan: Plan;
  tableName: string;
  confirmation: string;
  onConfirmationChange: (value: string) => void;
  busy: boolean;
  onCommit: () => void;
  onCancel: () => void;
  onDownload: () => void;
}) {
  const blocked = plan.needs_confirmation && confirmation !== tableName;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[color:var(--scrim)] p-4">
      <div className="flex max-h-[85vh] w-full max-w-3xl flex-col gap-4 overflow-y-auto rounded-2xl border border-line bg-surface p-6">
        <header>
          <h2 className="text-lg font-medium text-ink">Review before applying</h2>
          <p className="mt-1 text-sm text-muted">
            Rehearsed against {tableName} inside a transaction that was rolled back.{" "}
            {plan.blast_radius}
          </p>
        </header>

        {plan.conflicts.length > 0 ? (
          <div className="rounded-xl border border-[color:var(--danger-line)] bg-[color:var(--danger-soft)] px-4 py-3 text-sm text-ink">
            <p className="font-medium">The data has moved since it was read.</p>
            <ul className="mt-2 list-disc pl-5 text-xs">
              {plan.conflicts.map((conflict) => (
                <li key={conflict}>{conflict}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {plan.warnings.map((warning) => (
          <p
            key={warning}
            className="rounded-xl border border-[color:var(--warning-line)] bg-[color:var(--warning-soft)] px-4 py-3 text-xs text-ink"
          >
            {warning}
          </p>
        ))}

        <ol className="flex flex-col gap-2">
          {plan.statements.map((statement, index) => (
            <li key={`${statement.sql}:${index}`} className="rounded-xl border border-line bg-sunken p-3">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-sm text-ink">{statement.describes}</span>
                <span className="shrink-0 text-xs tabular-nums text-muted">
                  {statement.actual_rows === null
                    ? "not rehearsed"
                    : `${statement.actual_rows} row(s)`}
                </span>
              </div>
              <pre className="mt-2 overflow-x-auto text-xs text-muted">{statement.sql}</pre>
              {statement.irreversible ? (
                <p className="mt-1 text-xs text-[color:var(--danger)]">
                  This cannot be undone once it runs.
                </p>
              ) : null}
            </li>
          ))}
        </ol>

        {plan.needs_confirmation ? (
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.14em] text-muted">
            Type {tableName} to confirm
            <Input
              value={confirmation}
              onChange={(event) => onConfirmationChange(event.target.value)}
              placeholder={tableName}
            />
          </label>
        ) : null}

        <footer className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={onDownload}>
            Download as migration
          </Button>
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button variant={plan.has_irreversible ? "danger" : "primary"} onClick={onCommit} disabled={busy || blocked}>
            {busy ? "Applying…" : `Apply ${plan.rows_affected} row change(s)`}
          </Button>
        </footer>
      </div>
    </div>
  );
}
