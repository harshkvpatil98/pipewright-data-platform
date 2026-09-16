"use client";

import { useMemo, useState } from "react";

import { Input } from "@platform/shared-ui";

import { Icon } from "@/components/ui/icon";
import { cx } from "@/lib/utils";

import type { SchemaResponse, TableInfo } from "./types";

/**
 * The schema browser.
 *
 * Columns load when a table is expanded, not when the tree is drawn: a
 * warehouse with two thousand tables would otherwise reflect all of them to
 * render a list nobody has scrolled to yet.
 */
export function SchemaTree({
  schema,
  loading,
  onExpand,
  onInsert,
  onRefresh,
}: {
  schema: SchemaResponse | null;
  loading: boolean;
  onExpand: (table: TableInfo) => void;
  onInsert: (text: string) => void;
  onRefresh: () => void;
}) {
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());

  const tables = useMemo(() => {
    if (!schema) return [];
    const needle = filter.trim().toLowerCase();
    if (!needle) return schema.tables;
    return schema.tables.filter(
      (table) =>
        table.qualified.toLowerCase().includes(needle) ||
        table.columns.some((column) => column.name.toLowerCase().includes(needle)),
    );
  }, [schema, filter]);

  const toggle = (table: TableInfo) => {
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(table.qualified)) next.delete(table.qualified);
      else {
        next.add(table.qualified);
        if (!table.loaded) onExpand(table);
      }
      return next;
    });
  };

  return (
    <div className="flex h-full min-h-0 flex-col border-r border-line">
      <div className="flex items-center gap-2 border-b border-line p-2">
        <Input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter tables"
          className="h-8 text-xs"
          aria-label="Filter tables"
        />
        <button
          type="button"
          onClick={onRefresh}
          aria-label="Reload the schema"
          title="Reload the schema"
          className="shrink-0 rounded-lg border border-line p-1.5 text-muted transition hover:text-ink"
        >
          <Icon name="refresh" className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-1">
        {loading && !schema ? (
          <p className="px-2 py-3 text-xs text-muted">Reading the schema…</p>
        ) : null}
        {schema && tables.length === 0 ? (
          <p className="px-2 py-3 text-xs text-muted">
            {filter ? `Nothing matches “${filter}”.` : "This connection has no tables."}
          </p>
        ) : null}

        <ul>
          {tables.map((table) => {
            const expanded = open.has(table.qualified);
            return (
              <li key={table.qualified}>
                <button
                  type="button"
                  onClick={() => toggle(table)}
                  onDoubleClick={() => onInsert(table.qualified)}
                  aria-expanded={expanded}
                  className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-xs text-ink transition hover:bg-sunken"
                >
                  <Icon
                    name={expanded ? "chevronDown" : "chevronRight"}
                    className="h-3 w-3 shrink-0 text-muted"
                  />
                  <Icon
                    name={table.kind === "view" ? "search" : "table"}
                    className="h-3 w-3 shrink-0 text-muted"
                  />
                  <span className="truncate">{table.name}</span>
                  {table.table_schema && table.table_schema !== schema?.default_schema ? (
                    <span className="shrink-0 text-[10px] text-muted">{table.table_schema}</span>
                  ) : null}
                </button>

                {expanded ? (
                  <ul className="ml-6 border-l border-line">
                    {table.loaded && table.columns.length === 0 ? (
                      <li className="px-2 py-1 text-[11px] text-muted">No columns.</li>
                    ) : null}
                    {!table.loaded ? (
                      <li className="px-2 py-1 text-[11px] text-muted">Reading columns…</li>
                    ) : null}
                    {table.columns.map((column) => (
                      <li key={column.name}>
                        <button
                          type="button"
                          onClick={() => onInsert(column.name)}
                          title={`${column.type}${column.nullable ? "" : " · required"}`}
                          className={cx(
                            "flex w-full items-baseline gap-2 rounded px-2 py-0.5 text-left text-[11px] transition hover:bg-sunken",
                          )}
                        >
                          <span className="truncate text-ink-2">{column.name}</span>
                          {column.primary_key ? (
                            <span className="shrink-0 text-[9px] uppercase tracking-wide text-[color:var(--accent)]">
                              key
                            </span>
                          ) : null}
                          <span className="ml-auto shrink-0 truncate text-[10px] text-muted">
                            {column.type}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            );
          })}
        </ul>

        {schema?.truncated ? (
          <p className="px-2 py-2 text-[11px] text-muted">
            Only the first tables are shown; use the filter to find others.
          </p>
        ) : null}
      </div>
    </div>
  );
}
