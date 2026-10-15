"use client";

import { DataGrid } from "@/features/studio/grid/data-grid";
import { countOf, formatCount } from "@/lib/format";

import { formatDuration } from "./editor-state";
import type { AcrossResponse, Connection } from "./types";

/** What "Across sources" in the connection list is called internally. */
export const ACROSS = "__across__";

/** The connections a query across sources can read: databases. */
const DATABASES = new Set(["postgresql", "mysql", "sqlite"]);

export function databases(connections: Connection[]): Connection[] {
  return connections.filter((connection) => DATABASES.has(connection.connector_type));
}

/** A connection's name as it can be typed without quotes: lower case, spaces as underscores. */
export function plainName(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

/** An example query that names this project's own connections. */
export function acrossExample(connections: Connection[]): string {
  const first = databases(connections)[0];
  const table = first ? `${plainName(first.name) || "connection"}.public.orders` : 'datasets."Orders"';
  return [
    "SELECT c.region, SUM(o.amount) AS sales",
    `FROM ${table} AS o`,
    'JOIN datasets."Customers" AS c ON o.customer_id = c.id',
    "WHERE o.amount > 50",
    "GROUP BY c.region",
  ].join("\n");
}

/** In place of the table tree: how to name tables from several sources. */
export function AcrossHelp({ connections, onInsert }: { connections: Connection[]; onInsert: (text: string) => void }) {
  const readable = databases(connections);
  return (
    <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3 text-xs">
      <p className="leading-5 text-ink-2">
        One SELECT over tables in this project&apos;s connections and its datasets. Each source runs what it can;
        joins between them run here.
      </p>
      <div>
        <p className="mb-1 font-medium text-ink">Name a table</p>
        <ul className="space-y-1 font-mono text-[12px] text-ink-2">
          <li>connection.schema.table</li>
          <li>datasets.&quot;Name&quot;</li>
        </ul>
      </div>
      {readable.length > 0 ? (
        <div>
          <p className="mb-1 font-medium text-ink">This project&apos;s databases</p>
          <ul className="space-y-1">
            {readable.map((connection) => (
              <li key={connection.id}>
                <button
                  type="button"
                  onClick={() => onInsert(plainName(connection.name))}
                  className="w-full rounded-lg px-2 py-1 text-left transition hover:bg-sunken"
                  title="Insert at the cursor"
                >
                  <span className="block font-mono text-[12px] text-ink">{plainName(connection.name)}</span>
                  <span className="block text-[12px] text-muted">{connection.name}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <button
        type="button"
        onClick={() => onInsert(acrossExample(connections))}
        className="rounded-lg border border-line px-2 py-1 text-[12px] text-ink transition hover:bg-sunken"
      >
        Insert an example
      </button>
    </div>
  );
}

/** The answer, and what each source ran to give it. */
export function AcrossResult({ result }: { result: AcrossResponse }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-[160px] flex-[3]">
        <DataGrid
          columns={result.columns.map((name) => ({ name }))}
          rows={result.rows}
          className="h-full"
          emptyMessage="This query returned no rows."
        />
      </div>
      {result.truncated ? (
        <p className="border-t border-line px-3 py-1 text-[12px] text-muted">
          Showing the first {countOf(result.rows.length, "row")} of {formatCount(result.row_count)}.
        </p>
      ) : null}
      <section aria-label="How it ran" className="min-h-0 flex-[2] overflow-y-auto border-t border-line p-3 text-xs">
        <p className="mb-2 text-ink">
          {countOf(result.row_count, "row")} in {formatDuration(result.duration_ms)}, from{" "}
          {countOf(result.sources.length, "source")}.
        </p>
        {result.notes.map((note) => (
          <p key={note} className="mb-2 rounded-lg border border-line bg-sunken px-3 py-2 text-ink">
            {note}
          </p>
        ))}
        <ul className="space-y-3">
          {result.sources.map((source, index) => (
            <li key={`${source.source}-${index}`}>
              <p className="text-ink">
                <span className="font-medium">{source.source}</span>
                <span className="text-ink-3">
                  {" "}
                  sent {countOf(source.rows, "row")}
                  {source.estimated !== null ? ` (expected about ${formatCount(source.estimated)})` : ""},{" "}
                  {source.method}.
                </span>
              </p>
              {source.estimate_how ? <p className="text-[12px] text-ink-3">Estimated from {source.estimate_how}.</p> : null}
              <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded-lg bg-sunken p-2 font-mono text-[12px] leading-5 text-ink-2">
                {source.ran}
              </pre>
            </li>
          ))}
        </ul>
        {result.joins.length > 0 ? (
          <div className="mt-3">
            <p className="mb-1 font-medium text-ink">Joined here</p>
            <ul className="space-y-1 text-ink-2">
              {result.joins.map((join, index) => (
                <li key={`${join.joined}-${index}`}>
                  {join.joined}: {countOf(join.rows, "row")}
                  {join.estimated !== null ? ` (expected about ${formatCount(join.estimated)})` : ""}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {result.rewrites.length > 0 ? (
          <div className="mt-3">
            <p className="mb-1 font-medium text-ink">Rewritten first, without changing the answer</p>
            <ul className="space-y-0.5 text-[12px] text-ink-3">
              {result.rewrites.map((rewrite) => (
                <li key={rewrite}>{rewrite}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>
    </div>
  );
}
