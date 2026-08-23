"use client";

import { useMemo } from "react";

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
}: {
  config: Record<string, unknown>;
  tools: Tool[];
  columns: { name: string; type?: string }[];
  onChange: (config: Record<string, unknown>) => void;
}) {
  const name = typeof config.tool === "string" ? config.tool : "";
  const tool = useMemo(() => tools.find((entry) => entry.name === name), [tools, name]);

  if (!tool) {
    return (
      <p className="text-sm text-muted">
        This step uses a tool called <code className="text-ink">{name || "(none)"}</code>, which
        this version of the platform does not have. The pipeline still stores it; running it will
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
        <h3 className="text-sm font-medium text-ink">{tool.title}</h3>
        <p className="mt-1 text-xs text-muted">{tool.summary}</p>
        {exampleLine(tool) ? (
          <p className="mt-2 rounded-lg border border-line bg-sunken px-3 py-2 font-mono text-xs text-ink">
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
): { label: string; detail: string } {
  const name = typeof config.tool === "string" ? config.tool : "";
  const tool = tools.find((entry) => entry.name === name);
  const column = typeof config.column === "string" ? config.column : "";
  const into = typeof config.into === "string" ? config.into : "";
  return {
    label: tool?.title ?? name ?? "tool",
    detail: into && into !== column ? `${column} → ${into}` : column,
  };
}
