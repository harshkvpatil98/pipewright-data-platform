"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { Button, Icon, Overlay } from "@platform/shared-ui";

import {
  STEP_BY_TYPE,
  STEP_CATALOG,
  STEP_GROUPS,
  suggestedFor,
  type StepDefinition,
} from "@/features/studio/step-catalog";
import { cx } from "@/lib/utils";

import { ToolFields } from "./tools/tool-form";
import { ToolPreview } from "./tools/tool-preview";
import {
  defaultValues,
  exampleLine,
  groupByCategory,
  queryWords,
  rankTools,
  toConfig,
  toolsForColumn,
  toolsNamedForColumn,
  type Tool,
} from "./tools/tool-catalogue";

const RECENT_KEY = "pipewright.studio.recent-steps";
const RECENT_LIMIT = 5;

type Props = {
  tools: Tool[];
  columns: { name: string; type?: string }[];
  /** The column the palette was opened from, if any. */
  column?: string | null;
  /** Open with this tool already chosen. */
  preselect?: string | null;
  /** Rows already on screen, used to preview a tool's effect. */
  sampleRows?: Record<string, unknown>[];
  onAddBuiltIn: (definition: StepDefinition, column: string | null) => void;
  onAddTool: (config: Record<string, unknown>) => void;
  onClose: () => void;
};

type Entry = { kind: "step"; step: StepDefinition } | { kind: "tool"; tool: Tool };

const entryId = (entry: Entry) => (entry.kind === "step" ? `step:${entry.step.type}` : `tool:${entry.tool.name}`);

function readRecent(): string[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

function rememberRecent(id: string) {
  try {
    const next = [id, ...readRecent().filter((item) => item !== id)].slice(0, RECENT_LIMIT);
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable: nothing to remember */
  }
}

/** Built-in steps ranked against a query by the same rule as the tools. */
function rankSteps(query: string): StepDefinition[] {
  if (queryWords(query).length === 0) return STEP_CATALOG;
  const asTools: Tool[] = STEP_CATALOG.map((step) => ({
    name: step.type,
    title: step.label,
    category: step.group,
    summary: step.summary,
    synonyms: (step.keywords ?? "").split(" "),
    accepts: "any",
    column_scoped: false,
    params: [],
    example: { rows: [], params: {}, column: null, output: null, expect: [], note: "" },
  }));
  return rankTools(asTools, query).map((tool) => STEP_BY_TYPE.get(tool.name)!);
}

/**
 * The one way to add a step: the common steps and the whole tool library in a
 * single searchable list. A common step is added at once and its settings
 * open in the steps list; a tool is set up here, with a preview, first.
 */
export function StepPalette({
  tools,
  columns,
  column = null,
  preselect = null,
  sampleRows = [],
  onAddBuiltIn,
  onAddTool,
  onClose,
}: Props) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Tool | null>(null);
  const [toolColumn, setToolColumn] = useState<string | null>(column);
  const [into, setInto] = useState("");
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [recent, setRecent] = useState<string[]>([]);
  const searchRef = useRef<HTMLInputElement>(null);

  const columnType = columns.find((entry) => entry.name === column)?.type;

  useEffect(() => {
    setRecent(readRecent());
    searchRef.current?.focus();
  }, []);

  const chooseTool = (tool: Tool) => {
    setSelected(tool);
    setValues(defaultValues(tool));
    setInto("");
    if (tool.column_scoped && !toolColumn && columns.length) setToolColumn(columns[0].name);
  };

  useEffect(() => {
    if (!preselect) return;
    const found = tools.find((tool) => tool.name === preselect);
    if (found) chooseTool(found);
    // Keyed on `preselect` alone, so a later change of `tools` does not snap
    // the palette back to the first pick.
  }, [preselect]);

  const steps = useMemo(() => rankSteps(query), [query]);
  // Tools named for what the column holds ("Standardise an email" for email)
  // are the likeliest wanted, so they lead, both suggested and in a search.
  const namedForColumn = useMemo(
    () => (column ? toolsNamedForColumn(tools, column, columnType) : []),
    [tools, column, columnType],
  );
  const toolMatches = useMemo(() => {
    const pool = column ? toolsForColumn(tools, columnType) : tools;
    const ranked = rankTools(pool, query);
    const named = new Set(namedForColumn.map((tool) => tool.name));
    return [...ranked.filter((tool) => named.has(tool.name)), ...ranked.filter((tool) => !named.has(tool.name))];
  }, [tools, column, columnType, query, namedForColumn]);

  const searching = queryWords(query).length > 0;
  const suggestions = !searching && column ? suggestedFor(columnType) : [];
  const recentEntries: Entry[] = searching
    ? []
    : recent
        .map((id): Entry | null => {
          if (id.startsWith("step:")) {
            const step = STEP_BY_TYPE.get(id.slice(5));
            return step ? { kind: "step", step } : null;
          }
          const tool = tools.find((candidate) => candidate.name === id.slice(5));
          return tool ? { kind: "tool", tool } : null;
        })
        .filter((entry): entry is Entry => entry !== null);

  const pick = (entry: Entry) => {
    rememberRecent(entryId(entry));
    if (entry.kind === "step") onAddBuiltIn(entry.step, column);
    else chooseTool(entry.tool);
  };

  // Enter picks the top result: a tool named for the column when one matches,
  // otherwise the best common step, otherwise the best tool.
  const namedMatch = toolMatches.find((tool) => namedForColumn.some((named) => named.name === tool.name));
  const first: Entry | null =
    searching && namedMatch
      ? { kind: "tool", tool: namedMatch }
      : steps[0]
        ? { kind: "step", step: steps[0] }
        : toolMatches[0]
          ? { kind: "tool", tool: toolMatches[0] }
          : null;

  const ready = selected !== null && (!selected.column_scoped || Boolean(toolColumn));

  return (
    <Overlay
      open
      onClose={onClose}
      label="Add a step"
      placement="free"
      className="flex items-start justify-center p-4 pt-[6vh]"
    >
      <div className="relative flex max-h-[86vh] w-full max-w-5xl overflow-hidden rounded-2xl border border-line bg-surface shadow-[var(--shadow-lg)]">
        <div className={cx("w-full flex-col border-line md:flex md:w-1/2 md:border-r", selected ? "hidden" : "flex")}>
          <div className="border-b border-line p-4">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-[16px] font-semibold text-ink">Add a step</h2>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close"
                className="rounded-lg p-1.5 text-muted transition hover:bg-surface-2 hover:text-ink"
              >
                <Icon name="close" size={16} />
              </button>
            </div>
            <label className="sr-only" htmlFor="step-search">
              Search steps and tools
            </label>
            <div className="mt-3 flex h-10 items-center gap-2 rounded-lg border border-line bg-sunken px-3 focus-within:border-[color:var(--accent)]">
              <Icon name="search" size={15} className="text-muted" />
              <input
                id="step-search"
                ref={searchRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && first) {
                    event.preventDefault();
                    pick(first);
                  }
                }}
                placeholder="What do you want to do? For example “remove empty rows”"
                // The box around it shows focus; the global focus ring (which
                // outranks utility classes) would draw a second one inside it.
                style={{ outline: "none" }}
                className="min-w-0 flex-1 bg-transparent text-[14px] text-ink placeholder:text-faint"
              />
            </div>
            {column ? (
              <p className="mt-2 text-[13px] text-ink-3">
                For the column <span className="font-medium text-ink">{column}</span>
              </p>
            ) : null}
          </div>

          <div className="flex-1 overflow-y-auto p-2">
            {suggestions.length > 0 ? (
              <Section title={`Suggested for ${column}`}>
                {namedForColumn.length > 0 ? (
                  <ul className="mb-1">
                    {namedForColumn.slice(0, 3).map((tool) => (
                      <EntryRow
                        key={tool.name}
                        entry={{ kind: "tool", tool }}
                        active={selected?.name === tool.name}
                        onPick={() => pick({ kind: "tool", tool })}
                      />
                    ))}
                  </ul>
                ) : null}
                <StepGrid steps={suggestions} onPick={(step) => pick({ kind: "step", step })} />
              </Section>
            ) : null}

            {recentEntries.length > 0 ? (
              <Section title="Recently used">
                <ul>
                  {recentEntries.map((entry) => (
                    <EntryRow
                      key={entryId(entry)}
                      entry={entry}
                      active={entry.kind === "tool" && selected?.name === entry.tool.name}
                      onPick={() => pick(entry)}
                    />
                  ))}
                </ul>
              </Section>
            ) : null}

            {searching ? (
              steps.length > 0 ? (
                <Section title="Common steps">
                  <ul>
                    {steps.map((step) => (
                      <EntryRow key={step.type} entry={{ kind: "step", step }} onPick={() => pick({ kind: "step", step })} />
                    ))}
                  </ul>
                </Section>
              ) : null
            ) : (
              STEP_GROUPS.map((group) => (
                <Section key={group} title={group}>
                  <StepGrid
                    steps={STEP_CATALOG.filter((step) => step.group === group)}
                    onPick={(step) => pick({ kind: "step", step })}
                  />
                </Section>
              ))
            )}

            {toolMatches.length > 0 ? (
              <Section
                title={
                  searching
                    ? "More tools"
                    : `More tools (${toolMatches.length}${column ? ` for ${column}` : ""})`
                }
              >
                {groupByCategory(toolMatches).map((group) => (
                  <div key={group.category} className="mb-2">
                    {searching ? null : (
                      <h4 className="px-3 pb-1 pt-2 text-[12px] font-medium text-ink-3">{group.category}</h4>
                    )}
                    <ul>
                      {group.tools.map((tool) => (
                        <EntryRow
                          key={tool.name}
                          entry={{ kind: "tool", tool }}
                          active={selected?.name === tool.name}
                          onPick={() => pick({ kind: "tool", tool })}
                        />
                      ))}
                    </ul>
                  </div>
                ))}
              </Section>
            ) : null}

            {searching && steps.length === 0 && toolMatches.length === 0 ? (
              <p className="px-3 py-6 text-[14px] text-muted">
                Nothing matches “{query}”. Every word has to match, so try fewer of them.
              </p>
            ) : null}
          </div>
        </div>

        <div className={cx("w-full flex-col md:flex md:w-1/2", selected ? "flex" : "hidden")}>
          {selected === null ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center">
              <Icon name="sparkles" size={22} className="text-muted" />
              <p className="max-w-xs text-[14px] leading-6 text-ink-3">
                A common step is added straight away and you set it up in the steps list. A tool
                is set up here first, with a preview of what it does.
              </p>
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col">
              <div className="min-h-0 flex-1 overflow-y-auto p-5">
                <header className="mb-4">
                  <h3 className="text-[16px] font-semibold text-ink">{selected.title}</h3>
                  <p className="mt-1 text-[14px] text-ink-3">{selected.summary}</p>
                  {exampleLine(selected) ? (
                    <p className="mt-2 rounded-lg border border-line bg-sunken px-3 py-2 font-mono text-[12px] text-ink">
                      {exampleLine(selected)}
                    </p>
                  ) : selected.example.note ? (
                    <p className="mt-2 text-[13px] text-muted">{selected.example.note}</p>
                  ) : null}
                </header>

                <ToolFields
                  tool={selected}
                  columns={columns}
                  column={toolColumn}
                  into={into}
                  values={values}
                  onColumn={setToolColumn}
                  onInto={setInto}
                  onValue={(key, next) => setValues((current) => ({ ...current, [key]: next }))}
                />

                <ToolPreview tool={selected} column={toolColumn} into={into} values={values} rows={sampleRows} />
              </div>
              {/* Kept in view however long the settings are. */}
              <footer className="flex shrink-0 justify-end gap-2 border-t border-line px-5 py-3">
                <Button variant="ghost" onClick={() => setSelected(null)}>
                  Back
                </Button>
                <Button disabled={!ready} onClick={() => onAddTool(toConfig(selected, toolColumn, into, values))}>
                  Add step
                </Button>
              </footer>
            </div>
          )}
        </div>
      </div>
    </Overlay>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-3">
      <h3 className="px-3 pb-1 pt-2 text-[12px] font-semibold text-muted">{title}</h3>
      {children}
    </section>
  );
}

function StepGrid({ steps, onPick }: { steps: StepDefinition[]; onPick: (step: StepDefinition) => void }) {
  return (
    <div className="grid grid-cols-1 gap-1 px-1 sm:grid-cols-2">
      {steps.map((step) => (
        <button
          key={step.type}
          type="button"
          onClick={() => onPick(step)}
          title={step.summary}
          className="flex min-h-9 items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[14px] text-ink transition hover:bg-[color:var(--accent-faint)]"
        >
          <Icon name={step.icon} size={15} className="shrink-0 text-[color:var(--accent-muted)]" />
          <span className="truncate">{step.label}</span>
        </button>
      ))}
    </div>
  );
}

function EntryRow({ entry, active = false, onPick }: { entry: Entry; active?: boolean; onPick: () => void }) {
  const title = entry.kind === "step" ? entry.step.label : entry.tool.title;
  const summary = entry.kind === "step" ? entry.step.summary : entry.tool.summary;
  return (
    <li>
      <button
        type="button"
        onClick={onPick}
        className={cx(
          "flex w-full items-start gap-2.5 rounded-lg px-3 py-2 text-left transition",
          active ? "bg-[color:var(--accent-faint)]" : "hover:bg-sunken",
        )}
      >
        <Icon
          name={entry.kind === "step" ? entry.step.icon : "sparkles"}
          size={15}
          className="mt-0.5 shrink-0 text-[color:var(--accent-muted)]"
        />
        <span className="min-w-0">
          <span className="block text-[14px] text-ink">{title}</span>
          <span className="block text-[13px] text-muted">{summary}</span>
        </span>
      </button>
    </li>
  );
}
