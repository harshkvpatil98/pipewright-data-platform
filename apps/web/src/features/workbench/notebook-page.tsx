"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { AuthUser } from "@platform/shared-types";
import { EmptyState, Input, Select } from "@platform/shared-ui";

import { AppFrame } from "@/components/shell/app-frame";
import type { RibbonGroup } from "@/components/shell/ribbon";
import { useToast } from "@/components/providers/toast-provider";
import { Icon } from "@/components/ui/icon";
import { DataGrid } from "@/features/studio/grid/data-grid";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";

import {
  type Cell,
  type CellKind,
  type CellResult,
  describeCell,
  emptyCell,
  insertAfter,
  moveCell,
  namesAvailableTo,
  removeCell,
  toPayload,
  updateCell,
  validate,
} from "./notebook-state";
import type { Connection } from "./types";

type Notebook = {
  id: string;
  name: string;
  description: string | null;
  connection_id: string | null;
  cells: { id: string; kind: CellKind; source: string; output_name: string | null; config: Record<string, unknown> }[];
};

type SandboxStatus = {
  usable: boolean;
  reason: string;
  allowed_imports: string[];
  capabilities: { name: string; available: boolean; detail: string }[];
  limits: Record<string, number>;
};

const KIND_LABEL: Record<CellKind, string> = {
  sql: "SQL",
  python: "Python",
  recipe: "Recipe",
  markdown: "Notes",
};

export function NotebookPage({
  currentUser,
  projectId,
  projectName,
  connections,
}: {
  currentUser: AuthUser;
  projectId: string;
  projectName: string;
  connections: Connection[];
}) {
  const toast = useToast();
  const base = `/projects/${projectId}/workbench`;

  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [connectionId, setConnectionId] = useState<string | null>(connections[0]?.id ?? null);
  const [cells, setCells] = useState<Cell[]>([emptyCell("sql")]);
  const [results, setResults] = useState<Record<number, CellResult>>({});
  const [running, setRunning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [sandboxStatus, setSandboxStatus] = useState<SandboxStatus | null>(null);

  const problems = useMemo(() => validate(cells), [cells]);

  const load = useCallback(async () => {
    try {
      setNotebooks((await apiFetch<{ items: Notebook[] }>(`${base}/notebooks`)).items);
    } catch {
      setNotebooks([]);
    }
  }, [base]);

  useEffect(() => {
    void load();
    apiFetch<SandboxStatus>("/workbench/sandbox")
      .then(setSandboxStatus)
      .catch(() => setSandboxStatus(null));
  }, [load]);

  const open = useCallback((notebook: Notebook) => {
    setOpenId(notebook.id);
    setName(notebook.name);
    setConnectionId(notebook.connection_id);
    setCells(
      notebook.cells.length
        ? notebook.cells.map((cell) => ({
            id: cell.id,
            kind: cell.kind,
            source: cell.source,
            output_name: cell.output_name,
            config: cell.config ?? {},
          }))
        : [emptyCell("sql")],
    );
    setResults({});
  }, []);

  const save = useCallback(async () => {
    if (!name.trim()) {
      toast.error("Name it first", "A notebook needs a name to be saved.");
      return;
    }
    setSaving(true);
    try {
      const body = JSON.stringify({
        name: name.trim(),
        connection_id: connectionId,
        cells: toPayload(cells),
      });
      const notebook = openId
        ? await apiFetch<Notebook>(`${base}/notebooks/${openId}`, { method: "PATCH", body })
        : await apiFetch<Notebook>(`${base}/notebooks`, { method: "POST", body });
      setOpenId(notebook.id);
      toast.success("Saved", `“${notebook.name}” is up to date.`);
      void load();
    } catch (error) {
      toast.error("Could not save", extractErrorMessage(error));
    } finally {
      setSaving(false);
    }
  }, [base, name, connectionId, cells, openId, toast, load]);

  const run = useCallback(
    async (onlyTo?: number) => {
      if (!openId) {
        toast.error("Save first", "A notebook runs from what is saved, so save it before running.");
        return;
      }
      setRunning(true);
      try {
        const response = await apiFetch<{ cells: CellResult[] }>(
          `${base}/notebooks/${openId}/run`,
          { method: "POST", body: JSON.stringify({ only_to: onlyTo ?? null }) },
        );
        const next: Record<number, CellResult> = {};
        for (const cell of response.cells) next[cell.position] = cell;
        setResults(next);
      } catch (error) {
        toast.error("Could not run", extractErrorMessage(error));
      } finally {
        setRunning(false);
      }
    },
    [base, openId, toast],
  );

  const ribbon: RibbonGroup[] = [
    {
      id: "notebook",
      label: "Notebook",
      actions: [
        {
          id: "run-all",
          label: running ? "Running…" : "Run all",
          icon: "play",
          prominent: true,
          disabled: running || !openId || problems.length > 0,
          hint: problems.length ? "Fix the problems below first" : "Runs every cell in order",
          onClick: () => void run(),
        },
        {
          id: "save",
          label: saving ? "Saving…" : "Save",
          icon: "check",
          disabled: saving,
          onClick: () => void save(),
        },
        {
          id: "new",
          label: "New notebook",
          icon: "plus",
          onClick: () => {
            setOpenId(null);
            setName("");
            setCells([emptyCell("sql")]);
            setResults({});
          },
        },
      ],
    },
  ];

  if (connections.length === 0 && notebooks.length === 0) {
    return (
      <AppFrame
        currentUser={currentUser}
        crumbs={[
          { label: "Projects", href: "/projects" },
          { label: projectName, href: `/projects/${projectId}` },
          { label: "Notebooks" },
        ]}
      >
        <EmptyState
          title="No database connections in this project"
          description="A notebook can hold Python and recipe cells without one, but SQL cells need a database to read from."
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
        { label: "Notebooks" },
      ]}
      ribbon={ribbon}
      statusItems={[
        { id: "cells", label: "Cells", value: String(cells.length) },
        { id: "problems", label: "Problems", value: String(problems.length) },
        {
          id: "python",
          label: "Python cells",
          value: sandboxStatus ? (sandboxStatus.usable ? "enabled" : "disabled") : "…",
        },
      ]}
      inspector={{
        title: "Notebooks",
        content: (
          <ul className="flex flex-col gap-1">
            {notebooks.length === 0 ? (
              <li className="text-sm text-muted">Nothing saved yet.</li>
            ) : null}
            {notebooks.map((notebook) => (
              <li key={notebook.id}>
                <button
                  type="button"
                  onClick={() => open(notebook)}
                  className={cx(
                    "w-full rounded-lg px-3 py-2 text-left text-sm transition",
                    notebook.id === openId
                      ? "bg-[color:var(--accent-faint)] text-ink"
                      : "text-ink-2 hover:bg-sunken",
                  )}
                >
                  <span className="block truncate">{notebook.name}</span>
                  <span className="block text-xs text-muted">
                    {notebook.cells.length} cell{notebook.cells.length === 1 ? "" : "s"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ),
      }}
    >
      <div className="mx-auto flex h-full w-full max-w-4xl flex-col gap-4 overflow-y-auto p-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-1 flex-col gap-1">
            <span className="text-xs uppercase tracking-[0.14em] text-muted">Notebook name</span>
            <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Monthly revenue" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs uppercase tracking-[0.14em] text-muted">Connection</span>
            <Select
              value={connectionId ?? ""}
              onChange={(event) => setConnectionId(event.target.value || null)}
              className="w-56"
            >
              <option value="">None — Python and recipes only</option>
              {connections.map((connection) => (
                <option key={connection.id} value={connection.id}>
                  {connection.name}
                </option>
              ))}
            </Select>
          </label>
        </div>

        {sandboxStatus && !sandboxStatus.usable ? (
          <p className="rounded-xl border border-[color:var(--warning-line)] bg-[color:var(--warning-soft)] px-4 py-3 text-sm text-ink">
            {sandboxStatus.reason} Everything else in a notebook still works.
          </p>
        ) : null}

        {problems.map((problem) => (
          <p
            key={`${problem.cell}:${problem.message}`}
            className="rounded-xl border border-[color:var(--danger-line)] bg-[color:var(--danger-soft)] px-4 py-2 text-xs text-ink"
          >
            Cell {problem.cell + 1}: {problem.message}
          </p>
        ))}

        {cells.map((cell, index) => (
          <CellCard
            key={cell.id}
            cell={cell}
            index={index}
            total={cells.length}
            available={namesAvailableTo(cells, index)}
            result={results[index]}
            pythonDisabled={sandboxStatus ? !sandboxStatus.usable : false}
            onChange={(changes) => setCells((current) => updateCell(current, cell.id, changes))}
            onMove={(delta) => setCells((current) => moveCell(current, index, delta))}
            onRemove={() => setCells((current) => (current.length > 1 ? removeCell(current, cell.id) : current))}
            onInsert={(kind) => setCells((current) => insertAfter(current, index, emptyCell(kind)))}
            onRunTo={() => void run(index)}
            canRun={Boolean(openId) && !running}
          />
        ))}
      </div>
    </AppFrame>
  );
}

function CellCard({
  cell,
  index,
  total,
  available,
  result,
  pythonDisabled,
  onChange,
  onMove,
  onRemove,
  onInsert,
  onRunTo,
  canRun,
}: {
  cell: Cell;
  index: number;
  total: number;
  available: string[];
  result?: CellResult;
  pythonDisabled: boolean;
  onChange: (changes: Partial<Cell>) => void;
  onMove: (delta: number) => void;
  onRemove: () => void;
  onInsert: (kind: CellKind) => void;
  onRunTo: () => void;
  canRun: boolean;
}) {
  const disabled = cell.kind === "python" && pythonDisabled;

  return (
    <section className="rounded-xl border border-line bg-surface" aria-label={`Cell ${index + 1}`}>
      <header className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
        <span className="text-xs tabular-nums text-muted">{index + 1}</span>
        <Select
          value={cell.kind}
          onChange={(event) => onChange({ kind: event.target.value as CellKind })}
          className="h-8 w-32 text-xs"
          aria-label="Cell type"
        >
          {(Object.keys(KIND_LABEL) as CellKind[]).map((kind) => (
            <option key={kind} value={kind}>
              {KIND_LABEL[kind]}
            </option>
          ))}
        </Select>

        {cell.kind === "recipe" ? (
          <Select
            value={typeof cell.config.input === "string" ? cell.config.input : ""}
            onChange={(event) => onChange({ config: { ...cell.config, input: event.target.value } })}
            className="h-8 w-40 text-xs"
            aria-label="Input"
          >
            <option value="">Transform which result…</option>
            {available.map((entry) => (
              <option key={entry} value={entry}>
                {entry}
              </option>
            ))}
          </Select>
        ) : null}

        {cell.kind !== "markdown" ? (
          <Input
            value={cell.output_name ?? ""}
            onChange={(event) => onChange({ output_name: event.target.value || null })}
            placeholder="name this result"
            className="h-8 w-40 text-xs"
            aria-label="Name this result"
          />
        ) : null}

        <div className="ml-auto flex items-center gap-1">
          {result ? (
            <span
              className={cx(
                "mr-2 text-xs tabular-nums",
                result.error ? "text-[color:var(--danger)]" : "text-muted",
              )}
            >
              {describeCell(result)}
            </span>
          ) : null}
          <IconButton label="Run to here" icon="play" onClick={onRunTo} disabled={!canRun} />
          <IconButton label="Move up" icon="chevronRight" onClick={() => onMove(-1)} disabled={index === 0} rotate />
          <IconButton label="Move down" icon="chevronDown" onClick={() => onMove(1)} disabled={index === total - 1} />
          <IconButton label="Add a cell below" icon="plus" onClick={() => onInsert(cell.kind)} />
          <IconButton label="Remove this cell" icon="trash" onClick={onRemove} disabled={total === 1} />
        </div>
      </header>

      <textarea
        value={cell.source}
        onChange={(event) => onChange({ source: event.target.value })}
        disabled={disabled}
        spellCheck={cell.kind === "markdown"}
        rows={cell.kind === "markdown" ? 3 : 6}
        aria-label={`${KIND_LABEL[cell.kind]} source`}
        placeholder={
          disabled
            ? "Python cells are disabled on this deployment."
            : cell.kind === "sql"
              ? "SELECT * FROM …"
              : cell.kind === "python"
                ? "# Frames from earlier cells are available by name.\nout = orders.head()"
                : cell.kind === "recipe"
                  ? "version: 1\nsteps:\n  - step: tool\n    tool: text.trim\n    with:\n      column: name"
                  : "Notes for whoever reads this next."
        }
        className={cx(
          "w-full resize-y bg-canvas p-3 font-mono text-[13px] leading-6 text-ink outline-none",
          "placeholder:text-muted disabled:opacity-50 disabled:saturate-0",
          cell.kind === "markdown" && "font-sans",
        )}
      />

      {result ? <CellOutput result={result} /> : null}
    </section>
  );
}

function CellOutput({ result }: { result: CellResult }) {
  return (
    <div className="border-t border-line">
      {result.error ? (
        <p className="m-3 rounded-lg border border-[color:var(--danger-line)] bg-[color:var(--danger-soft)] px-3 py-2 font-mono text-xs text-ink">
          {result.error}
        </p>
      ) : null}
      {result.stdout ? (
        <pre className="m-3 overflow-x-auto rounded-lg bg-sunken px-3 py-2 font-mono text-[11px] leading-5 text-ink-2">
          {result.stdout}
        </pre>
      ) : null}
      {result.columns.length > 0 ? (
        <div className="h-64">
          <DataGrid
            columns={result.columns.map((name) => ({ name }))}
            rows={result.rows}
            className="h-full"
            emptyMessage="No rows."
          />
        </div>
      ) : null}
      {result.truncated ? (
        <p className="px-3 py-1 text-[11px] text-muted">
          Showing the first {result.rows.length.toLocaleString()} of{" "}
          {result.row_count.toLocaleString()} rows.
        </p>
      ) : null}
    </div>
  );
}

function IconButton({
  label,
  icon,
  onClick,
  disabled = false,
  rotate = false,
}: {
  label: string;
  icon: "play" | "chevronRight" | "chevronDown" | "plus" | "trash";
  onClick: () => void;
  disabled?: boolean;
  rotate?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="rounded-lg p-1.5 text-muted transition hover:text-ink disabled:opacity-40 disabled:saturate-0"
    >
      <Icon name={icon} className={cx("h-3.5 w-3.5", rotate && "-rotate-90")} />
    </button>
  );
}
