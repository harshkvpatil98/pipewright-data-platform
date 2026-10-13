"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import type {
  DestinationListResponse,
  DestinationRecord,
  DiscoveredTablesResponse,
  ExtractionConnection,
  ExtractionConnectionListResponse,
} from "@platform/shared-types";
import { SQL_CONNECTOR_TYPES } from "@platform/shared-types";
import { Button, FormField, Modal, Select, buttonClassName } from "@platform/shared-ui";

import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";

type ColumnPlan = {
  name: string;
  source_type: string;
  target_type: string;
  nullable: boolean;
  primary_key: boolean;
  lossy: boolean;
  note: string | null;
};
type TablePlan = {
  source: string;
  target: string;
  columns: ColumnPlan[];
  primary_key: string[];
  not_carried: string[];
  problem: string | null;
};
type CopyPlan = { source_label: string; destination_label: string; tables: TablePlan[]; never_copied: string[] };
type TableReport = {
  source: string;
  target: string;
  status: "succeeded" | "skipped" | "failed";
  rows_copied: number;
  carried: string[];
  not_carried: string[];
  message: string | null;
};
type CopyReport = { run_id: string; status: "succeeded" | "failed"; tables: TableReport[]; rows_copied: number; never_copied: string[] };

type CopyDatabaseDialogProps = {
  open: boolean;
  onClose: () => void;
  projectId: string;
  /** Start from this connection, when opened from one. */
  connectionId?: string;
};

type Step = "choose" | "tables" | "review" | "report";

/**
 * Copy tables from a connected database into a PostgreSQL or MySQL
 * destination: data and basic shape (columns and types, primary key, which
 * columns may be empty), with every conversion that loses detail flagged
 * before anything is written, and a report of what came across and what did not.
 */
export function CopyDatabaseDialog({ open, onClose, projectId, connectionId }: CopyDatabaseDialogProps) {
  const [step, setStep] = useState<Step>("choose");
  const [connections, setConnections] = useState<ExtractionConnection[] | null>(null);
  const [destinations, setDestinations] = useState<DestinationRecord[] | null>(null);
  const [sourceId, setSourceId] = useState(connectionId ?? "");
  const [targetId, setTargetId] = useState("");
  const [tables, setTables] = useState<string[]>([]);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [plan, setPlan] = useState<CopyPlan | null>(null);
  const [replace, setReplace] = useState(false);
  const [report, setReport] = useState<CopyReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setStep("choose");
    setPlan(null);
    setReport(null);
    setError(null);
    Promise.all([
      apiFetch<ExtractionConnectionListResponse>(`/projects/${projectId}/extraction/connections`),
      apiFetch<DestinationListResponse>(`/projects/${projectId}/destinations`),
    ])
      .then(([sources, targets]) => {
        const databases = sources.items.filter((item) => (SQL_CONNECTOR_TYPES as readonly string[]).includes(item.connector_type));
        const tablesTargets = targets.items.filter(
          (item) => (item.destination_type === "postgres" || item.destination_type === "mysql") && item.status === "active",
        );
        setConnections(databases);
        setDestinations(tablesTargets);
        setSourceId((current) => current || connectionId || databases[0]?.id || "");
        setTargetId((current) => current || tablesTargets[0]?.id || "");
      })
      .catch((caught) => setError(extractErrorMessage(caught)));
  }, [open, projectId, connectionId]);

  const act = async (work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const loadTables = () =>
    act(async () => {
      const listed = await apiFetch<DiscoveredTablesResponse>(
        `/projects/${projectId}/extraction/connections/${sourceId}/tables`,
      );
      const names = listed.items.filter((item) => item.kind === "table").map((item) => item.qualified_name);
      setTables(names);
      setChosen(new Set(names));
      setStep("tables");
    });

  const body = () => JSON.stringify({ connection_id: sourceId, destination_id: targetId, tables: Array.from(chosen), replace_existing: replace });

  const review = () =>
    act(async () => {
      setPlan(await apiFetch<CopyPlan>(`/projects/${projectId}/database-copies/plan`, { method: "POST", body: body() }));
      setStep("review");
    });

  const copy = () =>
    act(async () => {
      setReport(await apiFetch<CopyReport>(`/projects/${projectId}/database-copies`, { method: "POST", body: body() }));
      setStep("report");
    });

  const lossy = plan ? plan.tables.reduce((sum, table) => sum + table.columns.filter((column) => column.lossy).length, 0) : 0;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Copy a database"
      description="Copy tables, with their data, columns, primary keys and required columns, into a PostgreSQL or MySQL destination."
      widthClassName="max-w-3xl"
      footer={
        step === "choose" ? (
          <div className="flex justify-end">
            <Button size="sm" onClick={() => void loadTables()} disabled={busy || !sourceId || !targetId}>
              {busy ? "Reading…" : "Choose tables"}
            </Button>
          </div>
        ) : step === "tables" ? (
          <div className="flex justify-between gap-2">
            <Button variant="ghost" size="sm" onClick={() => setStep("choose")}>
              Back
            </Button>
            <Button size="sm" onClick={() => void review()} disabled={busy || chosen.size === 0}>
              {busy ? "Checking…" : "Check what will be copied"}
            </Button>
          </div>
        ) : step === "review" ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <label className="flex items-center gap-2 text-[13px] text-ink-2">
              <input type="checkbox" checked={replace} onChange={(event) => setReplace(event.target.checked)} className="h-4 w-4" />
              Replace tables already in the destination
            </label>
            <div className="flex gap-2">
              <Button variant="ghost" size="sm" onClick={() => setStep("tables")}>
                Back
              </Button>
              <Button size="sm" onClick={() => void copy()} disabled={busy || !plan}>
                <Icon name="database" size={14} />
                {busy ? "Copying…" : `Copy ${plan?.tables.length ?? 0} table${plan?.tables.length === 1 ? "" : "s"}`}
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex justify-end gap-2">
            {report ? (
              <Link href={`/projects/${projectId}/runs/${report.run_id}/audit`} className={buttonClassName("ghost", "sm")}>
                See the run
              </Link>
            ) : null}
            <Button size="sm" onClick={onClose}>
              Done
            </Button>
          </div>
        )
      }
    >
      {error ? (
        <p role="alert" className="mb-3 rounded-xl border border-danger-line bg-danger-soft px-3 py-2 text-[13px] text-danger">
          {error}
        </p>
      ) : null}

      {step === "choose" ? (
        connections === null || destinations === null ? (
          <p className="py-4 text-[14px] text-muted">Loading…</p>
        ) : connections.length === 0 || destinations.length === 0 ? (
          <div className="space-y-3 text-[14px] text-ink-3">
            {connections.length === 0 ? (
              <p>
                Connect the database to copy from first, on{" "}
                <Link href={`/projects/${projectId}/sources`} className="font-medium text-[color:var(--accent-muted)] underline">
                  Sources
                </Link>
                .
              </p>
            ) : null}
            {destinations.length === 0 ? (
              <p>
                Add the PostgreSQL or MySQL database to copy into, on{" "}
                <Link href={`/projects/${projectId}/destinations`} className="font-medium text-[color:var(--accent-muted)] underline">
                  Destinations
                </Link>
                .
              </p>
            ) : null}
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-[1fr_auto_1fr] sm:items-end">
            <FormField label="Copy from" htmlFor="copy-source">
              <Select id="copy-source" value={sourceId} onChange={(event) => setSourceId(event.target.value)}>
                {connections.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </Select>
            </FormField>
            <Icon name="arrowRight" size={18} className="mb-3 hidden text-muted sm:block" />
            <FormField label="Copy into" htmlFor="copy-target">
              <Select id="copy-target" value={targetId} onChange={(event) => setTargetId(event.target.value)}>
                {destinations.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </Select>
            </FormField>
            <p className="text-[13px] leading-5 text-ink-3 sm:col-span-3">
              Copied: the rows, each column with the closest type, the primary key and which columns may not be empty.
              Not copied: views, foreign keys, other indexes, defaults, triggers and procedures. You see exactly
              what before anything is written.
            </p>
          </div>
        )
      ) : null}

      {step === "tables" ? (
        <div>
          <div className="mb-2 flex items-center justify-between text-[13px] text-ink-3">
            <span>
              {chosen.size} of {tables.length} tables chosen
            </span>
            <button
              type="button"
              className="font-medium text-[color:var(--accent-muted)]"
              onClick={() => setChosen(chosen.size === tables.length ? new Set() : new Set(tables))}
            >
              {chosen.size === tables.length ? "Choose none" : "Choose all"}
            </button>
          </div>
          <ul className="grid max-h-[46vh] gap-1 overflow-y-auto sm:grid-cols-2">
            {tables.map((name) => (
              <li key={name}>
                <label className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-[14px] text-ink">
                  <input
                    type="checkbox"
                    checked={chosen.has(name)}
                    onChange={() =>
                      setChosen((current) => {
                        const next = new Set(current);
                        if (next.has(name)) next.delete(name);
                        else next.add(name);
                        return next;
                      })
                    }
                    className="h-4 w-4"
                  />
                  <span className="truncate">{name}</span>
                </label>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {step === "review" && plan ? (
        <div className="space-y-4">
          <p className="text-[14px] text-ink-2">
            {plan.tables.length} table{plan.tables.length === 1 ? "" : "s"} from {plan.source_label} into{" "}
            {plan.destination_label}.{" "}
            {lossy > 0 ? (
              <span className="text-warning">
                {lossy} column{lossy === 1 ? "" : "s"} will not come across exactly; each is marked below.
              </span>
            ) : (
              "Every column comes across exactly."
            )}
          </p>
          {plan.tables.map((table) => (
            <details key={table.source} className="rounded-xl border border-line bg-surface px-3 py-2" open={plan.tables.length <= 3}>
              <summary className="cursor-pointer text-[14px] text-ink">
                <span className="font-medium">{table.source}</span> → {table.target}
                <span className="ml-2 text-[13px] text-ink-3">
                  {table.columns.length} columns
                  {table.primary_key.length ? ` · key ${table.primary_key.join(", ")}` : " · no primary key"}
                </span>
                {table.problem ? <span className="ml-2 text-[13px] text-danger">{table.problem}</span> : null}
              </summary>
              <table className="mt-2 w-full text-left text-[13px]">
                <thead className="text-ink-3">
                  <tr>
                    <th className="py-1 pr-3 font-medium">Column</th>
                    <th className="py-1 pr-3 font-medium">{plan.source_label}</th>
                    <th className="py-1 pr-3 font-medium">{plan.destination_label}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {table.columns.map((column) => (
                    <tr key={column.name} className={cx(column.lossy && "bg-warning-soft")}>
                      <td className="py-1 pr-3 text-ink">
                        {column.name}
                        {column.primary_key ? <span className="ml-1 text-[12px] text-[color:var(--accent-muted)]">key</span> : null}
                        {!column.nullable && !column.primary_key ? <span className="ml-1 text-[12px] text-ink-3">required</span> : null}
                      </td>
                      <td className="py-1 pr-3 font-mono text-[12px] text-ink-3">{column.source_type}</td>
                      <td className="py-1 pr-3 font-mono text-[12px] text-ink-2">
                        {column.target_type}
                        {column.note ? <span className="block font-sans text-[12px] text-warning">{column.note}</span> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {table.not_carried.length ? (
                <p className="mt-2 text-[13px] text-ink-3">Not copied: {table.not_carried.join("; ")}.</p>
              ) : null}
            </details>
          ))}
          <ul className="space-y-0.5 text-[13px] text-ink-3">
            {plan.never_copied.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {step === "report" && report ? (
        <div className="space-y-3">
          <p
            role="status"
            className={cx(
              "rounded-xl border px-3 py-2 text-[14px]",
              report.status === "succeeded" ? "border-success-line bg-success-soft text-success" : "border-danger-line bg-danger-soft text-danger",
            )}
          >
            {report.status === "succeeded" ? "Copied" : "Some tables did not copy"}: {report.rows_copied.toLocaleString()} rows
            in {report.tables.filter((table) => table.status === "succeeded").length} of {report.tables.length} tables.
          </p>
          <ul className="space-y-2">
            {report.tables.map((table) => (
              <li key={table.source} className="rounded-xl border border-line bg-surface px-3 py-2 text-[13px]">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-ink">{table.target}</span>
                  <span
                    className={cx(
                      "rounded-full px-2 text-[12px]",
                      table.status === "succeeded"
                        ? "bg-success-soft text-success"
                        : table.status === "skipped"
                          ? "bg-surface-2 text-ink-3"
                          : "bg-danger-soft text-danger",
                    )}
                  >
                    {table.status === "succeeded" ? `${table.rows_copied.toLocaleString()} rows` : table.status}
                  </span>
                </div>
                {table.message ? <p className="mt-1 text-ink-3">{table.message}</p> : null}
                {table.carried.length ? <p className="mt-1 text-ink-2">Carried: {table.carried.join("; ")}.</p> : null}
                {table.not_carried.length ? <p className="mt-0.5 text-ink-3">Not carried: {table.not_carried.join("; ")}.</p> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Modal>
  );
}
