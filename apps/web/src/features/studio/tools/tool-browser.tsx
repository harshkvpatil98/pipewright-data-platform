"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { Button, Input, Select } from "@platform/shared-ui";

import { Icon } from "@/components/ui/icon";
import { cx } from "@/lib/utils";

import { ToolFields } from "./tool-form";
import { ToolPreview } from "./tool-preview";
import {
  defaultValues,
  exampleLine,
  groupByCategory,
  rankTools,
  toConfig,
  toolsForColumn,
  type Tool,
} from "./tool-catalogue";

type Props = {
  tools: Tool[];
  categories: string[];
  columns: { name: string; type?: string }[];
  /** Pre-selected when the browser opens from a column's context menu. */
  initialColumn?: string | null;
  /** Show only the tools that suit `initialColumn`'s type. */
  restrictToColumnType?: boolean;
  /** Open with this tool already chosen, from a context-menu pick. */
  preselect?: string | null;
  /** Rows already on screen, used to preview the tool's effect. */
  sampleRows?: Record<string, unknown>[];
  onAdd: (config: Record<string, unknown>) => void;
  onClose: () => void;
};

export function ToolBrowser({
  tools,
  categories,
  columns,
  initialColumn = null,
  restrictToColumnType = false,
  preselect = null,
  sampleRows = [],
  onAdd,
  onClose,
}: Props) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>("");
  const [selected, setSelected] = useState<Tool | null>(null);
  const [column, setColumn] = useState<string | null>(initialColumn);
  const [into, setInto] = useState("");
  const [values, setValues] = useState<Record<string, unknown>>({});
  const searchRef = useRef<HTMLInputElement>(null);

  const choose = (tool: Tool) => {
    setSelected(tool);
    setValues(defaultValues(tool));
    setInto("");
    if (tool.column_scoped && !column && columns.length) setColumn(columns[0].name);
  };

  useEffect(() => {
    searchRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!preselect) return;
    const found = tools.find((tool) => tool.name === preselect);
    if (found) choose(found);
    // Deliberately keyed on `preselect` alone: re-running when `tools` changes
    // would snap the panel back to the context-menu pick after somebody had
    // moved on to another tool.
  }, [preselect]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const columnType = useMemo(
    () => columns.find((entry) => entry.name === column)?.type,
    [columns, column],
  );

  const visible = useMemo(() => {
    let pool = tools;
    if (restrictToColumnType && column) pool = toolsForColumn(pool, columnType);
    if (category) pool = pool.filter((tool) => tool.category === category);
    return rankTools(pool, query);
  }, [tools, restrictToColumnType, column, columnType, category, query]);

  const grouped = useMemo(() => groupByCategory(visible), [visible]);

  const ready = selected !== null && (!selected.column_scoped || Boolean(column));

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-[color:var(--scrim)] p-4 pt-[8vh]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="relative flex max-h-[80vh] w-full max-w-5xl overflow-hidden rounded-2xl border border-line bg-surface"
        role="dialog"
        aria-modal="true"
        aria-label="Add a transformation tool"
      >
        {/* ------------------------------------------------------- catalogue */}
        <div className="flex w-1/2 flex-col border-r border-line">
          <div className="flex flex-col gap-2 border-b border-line p-4">
            <label className="sr-only" htmlFor="tool-search">
              Search tools
            </label>
            <Input
              id="tool-search"
              ref={searchRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={`Search ${tools.length} tools — try “title case” or “zip”`}
            />
            <div className="flex items-center gap-2">
              <Select
                value={category}
                onChange={(event) => setCategory(event.target.value)}
                className="h-9 text-xs"
                aria-label="Category"
              >
                <option value="">All categories</option>
                {categories.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </Select>
              <span className="shrink-0 text-xs tabular-nums text-muted">
                {visible.length} shown
              </span>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-2">
            {visible.length === 0 ? (
              <p className="px-3 py-6 text-sm text-muted">
                Nothing matches “{query}”. Every word has to match, so try fewer of them.
              </p>
            ) : null}
            {grouped.map((group) => (
              <section key={group.category} className="mb-3">
                <h3 className="px-3 py-1 text-xs uppercase tracking-[0.14em] text-muted">
                  {group.category}
                </h3>
                <ul>
                  {group.tools.map((tool) => (
                    <li key={tool.name}>
                      <button
                        type="button"
                        onClick={() => choose(tool)}
                        className={cx(
                          "w-full rounded-lg px-3 py-2 text-left transition",
                          selected?.name === tool.name
                            ? "bg-[color:var(--accent-faint)] text-ink"
                            : "text-ink hover:bg-sunken",
                        )}
                      >
                        <span className="block text-sm">{tool.title}</span>
                        <span className="block text-xs text-muted">{tool.summary}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </div>

        {/* --------------------------------------------------------- settings */}
        <div className="flex w-1/2 flex-col">
          {selected === null ? (
            <div className="flex flex-1 items-center justify-center p-8 text-center text-sm text-muted">
              Pick a tool to see what it does and set it up.
            </div>
          ) : (
            <div className="flex flex-1 flex-col overflow-y-auto p-5">
              <header className="mb-4">
                <h2 className="text-base font-medium text-ink">{selected.title}</h2>
                <p className="mt-1 text-sm text-muted">{selected.summary}</p>
                {exampleLine(selected) ? (
                  <p className="mt-2 rounded-lg border border-line bg-sunken px-3 py-2 font-mono text-xs text-ink">
                    {exampleLine(selected)}
                  </p>
                ) : selected.example.note ? (
                  <p className="mt-2 text-xs text-muted">{selected.example.note}</p>
                ) : null}
              </header>

              <ToolFields
                tool={selected}
                columns={columns}
                column={column}
                into={into}
                values={values}
                onColumn={setColumn}
                onInto={setInto}
                onValue={(key, next) => setValues((current) => ({ ...current, [key]: next }))}
              />

              <ToolPreview
                tool={selected}
                column={column}
                into={into}
                values={values}
                rows={sampleRows}
              />

              <footer className="mt-6 flex justify-end gap-2">
                <Button variant="ghost" onClick={onClose}>
                  Cancel
                </Button>
                <Button
                  disabled={!ready}
                  onClick={() => onAdd(toConfig(selected, column, into, values))}
                >
                  Add step
                </Button>
              </footer>
            </div>
          )}
        </div>

        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute right-3 top-3 rounded-full border border-line bg-surface p-2 text-muted transition hover:text-ink"
        >
          <Icon name="close" className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
