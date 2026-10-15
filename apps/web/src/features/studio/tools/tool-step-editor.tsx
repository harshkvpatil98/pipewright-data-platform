"use client";

import { useMemo } from "react";

import { cx } from "@/lib/utils";

import { exampleLine, toConfig, type Tool } from "./tool-catalogue";
import { ToolFields } from "./tool-form";

/**
 * Settings for an already-added tool step.
 *
 * Reads the current config back into the form rather than holding its own copy:
 * a step is edited, reordered and re-selected, and a second source of truth is
 * how an editor ends up showing settings the pipeline does not have.
 */
export function ToolStepEditor({
  config,
  tools,
  columns,
  onChange,
  compact = false,
}: {
  config: Record<string, unknown>;
  tools: Tool[];
  columns: { name: string; type?: string }[];
  onChange: (config: Record<string, unknown>) => void;
  /** Inside the steps list, where the step's name is already on its line. */
  compact?: boolean;
}) {
  const name = typeof config.tool === "string" ? config.tool : "";
  const tool = useMemo(() => tools.find((entry) => entry.name === name), [tools, name]);

  if (!tool) {
    return (
      <p className="text-[13px] text-muted">
        This step uses a tool called <code className="text-ink">{name || "(none)"}</code>, which
        this version of the platform does not have. The recipe still stores it; running it will
        report the same thing.
      </p>
    );
  }

  const column = typeof config.column === "string" ? config.column : null;
  const into = typeof config.into === "string" ? config.into : "";
  const values: Record<string, unknown> = {};
  for (const param of tool.params) {
    values[param.key] = config[param.key] ?? param.default ?? (param.kind === "boolean" ? false : "");
  }

  const update = (
    nextColumn: string | null,
    nextInto: string,
    nextValues: Record<string, unknown>,
  ) => onChange(toConfig(tool, nextColumn, nextInto, nextValues));

  return (
    <div className="flex flex-col gap-4">
      <header>
        {compact ? null : <h3 className="text-sm font-medium text-ink">{tool.title}</h3>}
        <p className={cx("text-[13px] text-ink-3", !compact && "mt-1")}>{tool.summary}</p>
        {exampleLine(tool) ? (
          <p className="mt-2 rounded-lg border border-line bg-sunken px-3 py-2 font-mono text-[12px] text-ink">
            {exampleLine(tool)}
          </p>
        ) : null}
      </header>

      <ToolFields
        tool={tool}
        columns={columns}
        column={column}
        into={into}
        values={values}
        onColumn={(next) => update(next, into, values)}
        onInto={(next) => update(column, next, values)}
        onValue={(key, next) => update(column, into, { ...values, [key]: next })}
      />
    </div>
  );
}

/** How a tool step reads in the step list. */
export function describeToolStep(
  config: Record<string, unknown>,
  tools: Tool[],
  datasetNames: ReadonlyMap<string, string> = new Map(),
): { label: string; detail: string; incomplete: boolean } {
  const name = typeof config.tool === "string" ? config.tool : "";
  const tool = tools.find((entry) => entry.name === name);
  const column = typeof config.column === "string" ? config.column : "";
  const into = typeof config.into === "string" ? config.into : "";
  const label = tool?.title ?? (name || "tool");
  const empty = (value: unknown) =>
    value === undefined || value === null || value === "" || (Array.isArray(value) && value.length === 0);
  // Not set up: no column for a tool that works on one, or a required setting with nothing in it.
  const incomplete = tool
    ? (tool.column_scoped && !column) ||
      tool.params.some((param) => param.required && empty(config[param.key]) && empty(param.default))
    : false;
  if (column) return { label, detail: into && into !== column ? `${column} → ${into}` : column, incomplete };
  // A tool that does not work on one column says what it was given: its columns, the
  // other dataset, its values.
  const parts: string[] = [];
  for (const param of tool?.params ?? []) {
    const value = config[param.key];
    if (empty(value) || param.kind === "boolean") continue;
    if (param.kind === "dataset") parts.push(datasetNames.get(String(value)) ?? "another dataset");
    else if (Array.isArray(value)) parts.push(value.map(String).join(", "));
    else if (param.kind === "number" || param.kind === "integer") parts.push(`${param.label.toLowerCase()} ${String(value)}`);
    else parts.push(String(value));
  }
  const detail = parts.slice(0, 3).join(" · ");
  return { label, detail: detail.length > 80 ? `${detail.slice(0, 79)}…` : detail, incomplete };
}
