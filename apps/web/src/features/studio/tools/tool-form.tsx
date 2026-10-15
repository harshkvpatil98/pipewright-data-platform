"use client";

import { Input, Select } from "@platform/shared-ui";

import type { Tool, ToolParam } from "./tool-catalogue";
import { useOtherDatasets } from "./other-datasets";
import { typeLabel } from "@/lib/labels";

export function Field({
  label,
  help,
  children,
}: {
  label: string;
  help?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>
      {children}
      {help ? <span className="text-xs text-muted">{help}</span> : null}
    </label>
  );
}

export function ParamInput({
  param,
  columns,
  value,
  onChange,
  chosenDataset = "",
}: {
  param: ToolParam;
  columns: { name: string }[];
  value: unknown;
  onChange: (next: unknown) => void;
  /** The other dataset this tool reads, for its column settings. */
  chosenDataset?: string;
}) {
  const others = useOtherDatasets();
  if (param.kind === "dataset") {
    return (
      <Select value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}>
        <option value="">Choose a dataset…</option>
        {others.map((dataset) => (
          <option key={dataset.id} value={dataset.id}>
            {dataset.name}
          </option>
        ))}
      </Select>
    );
  }
  if (param.kind === "dataset_column" || param.kind === "dataset_columns") {
    const theirs = others.find((dataset) => dataset.id === chosenDataset)?.columns ?? [];
    if (!chosenDataset) return <p className="text-xs text-muted">Choose the other dataset first.</p>;
    if (param.kind === "dataset_column") {
      return (
        <Select value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}>
          <option value="">Choose one of its columns…</option>
          {theirs.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </Select>
      );
    }
    return (
      <ColumnChips
        label={param.label}
        names={theirs}
        value={value}
        onChange={onChange}
        empty="Its columns are not known yet."
      />
    );
  }
  if (param.kind === "columns") {
    return (
      <ColumnChips
        label={param.label}
        names={columns.map((entry) => entry.name)}
        value={value}
        onChange={onChange}
        empty="This dataset has no columns yet."
      />
    );
  }
  if (param.kind === "select") {
    return (
      <Select value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}>
        {param.options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </Select>
    );
  }
  if (param.kind === "boolean") {
    return (
      <span className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
          className="h-4 w-4 rounded border-line accent-[color:var(--accent)]"
        />
        <span className="text-sm text-ink">Yes</span>
      </span>
    );
  }
  if (param.kind === "column") {
    return (
      <Select value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}>
        <option value="">Choose a column…</option>
        {columns.map((entry) => (
          <option key={entry.name} value={entry.name}>
            {entry.name}
          </option>
        ))}
      </Select>
    );
  }
  if (param.kind === "list") {
    const text = Array.isArray(value) ? value.join("\n") : String(value ?? "");
    return (
      <textarea
        value={text}
        onChange={(event) =>
          onChange(event.target.value.split("\n").map((line) => line.trim()).filter(Boolean))
        }
        rows={3}
        placeholder={param.placeholder || "One per line"}
        className="w-full rounded-xl border border-line bg-sunken px-3 py-2 text-sm text-ink outline-none transition focus:border-[color:var(--accent)] focus:ring-2 focus:ring-[color:var(--accent-soft)]"
      />
    );
  }
  const numeric = param.kind === "number" || param.kind === "integer";
  return (
    <Input
      type={numeric ? "number" : "text"}
      step={param.kind === "integer" ? 1 : "any"}
      min={param.minimum ?? undefined}
      max={param.maximum ?? undefined}
      value={String(value ?? "")}
      placeholder={param.placeholder}
      onChange={(event) =>
        onChange(
          numeric
            ? event.target.value === ""
              ? ""
              : Number(event.target.value)
            : event.target.value,
        )
      }
    />
  );
}

/** Columns to pick, in the order picked, which is the order a tool uses them. */
function ColumnChips({
  label,
  names,
  value,
  onChange,
  empty,
}: {
  label: string;
  names: string[];
  value: unknown;
  onChange: (next: unknown) => void;
  empty: string;
}) {
  const picked = Array.isArray(value) ? value.map(String) : [];
  return (
    <span className="flex flex-wrap gap-1.5" role="group" aria-label={label}>
      {names.map((name) => {
        const position = picked.indexOf(name);
        const on = position >= 0;
        return (
          <button
            key={name}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(on ? picked.filter((item) => item !== name) : [...picked, name])}
            className={
              on
                ? "rounded-full border border-[color:var(--accent)] bg-[color:var(--accent-soft)] px-2.5 py-1 text-xs text-ink"
                : "rounded-full border border-line px-2.5 py-1 text-xs text-ink-3 transition hover:bg-sunken"
            }
          >
            {on && picked.length > 1 ? `${position + 1}. ` : ""}
            {name}
          </button>
        );
      })}
      {names.length === 0 ? <span className="text-xs text-muted">{empty}</span> : null}
    </span>
  );
}

/**
 * The settings for one tool: which column, where to write, and its parameters.
 *
 * Shared by the tool browser and the step inspector so a tool cannot offer one
 * set of choices when it is added and a different set when it is edited.
 */
export function ToolFields({
  tool,
  columns,
  column,
  into,
  values,
  onColumn,
  onInto,
  onValue,
}: {
  tool: Tool;
  columns: { name: string; type?: string }[];
  column: string | null;
  into: string;
  values: Record<string, unknown>;
  onColumn: (next: string | null) => void;
  onInto: (next: string) => void;
  onValue: (key: string, next: unknown) => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      {tool.column_scoped ? (
        <>
          <Field label="Column">
            <Select
              value={column ?? ""}
              onChange={(event) => onColumn(event.target.value || null)}
            >
              <option value="">Choose a column…</option>
              {columns.map((entry) => (
                <option key={entry.name} value={entry.name}>
                  {entry.name}
                  {entry.type ? ` · ${typeLabel(entry.type)}` : ""}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Write into"
            help="Leave empty to replace the column, or name a new one to keep the original."
          >
            <Input
              value={into}
              onChange={(event) => onInto(event.target.value)}
              placeholder={column ? `${column} (replaced)` : ""}
            />
          </Field>
        </>
      ) : null}

      {tool.params.map((param) => (
        <Field key={param.key} label={param.label} help={param.help}>
          <ParamInput
            param={param}
            columns={columns}
            value={values[param.key]}
            onChange={(next) => onValue(param.key, next)}
            chosenDataset={typeof values.right_dataset_id === "string" ? values.right_dataset_id : ""}
          />
        </Field>
      ))}
    </div>
  );
}
