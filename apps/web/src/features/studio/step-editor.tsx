"use client";

import { useId, useRef } from "react";

import { Icon } from "@/components/ui/icon";
import {
  AGGREGATION_FUNCTIONS,
  CAST_TYPES,
  FILTER_OPERATORS,
  type StepDefinition,
  type StepField,
} from "@/features/studio/step-catalog";
import { cx } from "@/lib/utils";

type StepEditorProps = {
  definition: StepDefinition;
  config: Record<string, unknown>;
  columns: string[];
  datasets: { id: string; name: string }[];
  onChange: (config: Record<string, unknown>) => void;
};

const inputClass =
  "h-9 w-full rounded-lg border border-line bg-sunken px-2.5 text-[13px] text-ink outline-none transition placeholder:text-faint focus:border-[color:var(--accent)] focus:ring-2 focus:ring-[color:var(--accent-soft)]";

/** Renders the correct control for each field kind in the step catalogue. */
export function StepEditor({ definition, config, columns, datasets, onChange }: StepEditorProps) {
  const set = (key: string, value: unknown) => onChange({ ...config, [key]: value });

  return (
    <div className="space-y-3">
      <p className="text-[12px] leading-5 text-ink-3">{definition.summary}</p>
      {definition.fields.map((field) => (
        <Field
          key={field.key}
          field={field}
          value={config[field.key]}
          columns={columns}
          datasets={datasets}
          onChange={(value) => set(field.key, value)}
        />
      ))}
    </div>
  );
}

type FieldProps = {
  field: StepField;
  value: unknown;
  columns: string[];
  datasets: { id: string; name: string }[];
  onChange: (value: unknown) => void;
};

function Field({ field, value, columns, datasets, onChange }: FieldProps) {
  const id = useId();

  return (
    <div>
      <label htmlFor={id} className="mb-1.5 flex items-center gap-2 text-[12px] font-medium text-ink">
        {field.label}
        {field.optional ? <span className="text-[10px] text-muted">optional</span> : null}
      </label>
      <Control id={id} field={field} value={value} columns={columns} datasets={datasets} onChange={onChange} />
      {field.help ? <p className="mt-1.5 text-[11px] leading-4 text-muted">{field.help}</p> : null}
    </div>
  );
}

function Control({ id, field, value, columns, datasets, onChange }: FieldProps & { id: string }) {
  switch (field.kind) {
    case "formula":
      return <FormulaInput id={id} field={field} value={value} columns={columns} onChange={onChange} />;

    case "text":
      return (
        <input
          id={id}
          className={inputClass}
          value={typeof value === "string" ? value : ""}
          placeholder={field.placeholder}
          onChange={(event) => onChange(event.target.value)}
        />
      );

    case "number":
      return (
        <input
          id={id}
          type="number"
          className={inputClass}
          value={typeof value === "number" ? value : ""}
          placeholder={field.placeholder}
          onChange={(event) =>
            onChange(event.target.value === "" ? undefined : Number(event.target.value))
          }
        />
      );

    case "boolean":
      return (
        <button
          id={id}
          type="button"
          role="switch"
          aria-checked={Boolean(value)}
          onClick={() => onChange(!value)}
          className={cx(
            "relative h-6 w-11 rounded-full border transition duration-[var(--duration-fast)]",
            value
              ? "border-[color:var(--accent)] bg-[color:var(--accent)]"
              : "border-line-strong bg-surface-2",
          )}
        >
          <span
            className={cx(
              // A plain white thumb on the off-state track is 1.06:1 in light mode --
              // invisible. The border and shadow are what make it read on both
              // tracks in both themes.
              "absolute top-0.5 h-4.5 w-4.5 rounded-full border border-line-strong bg-surface shadow-[var(--shadow-sm)] transition-all duration-[var(--duration-fast)]",
              value ? "left-[22px]" : "left-0.5",
            )}
            style={{ height: 18, width: 18 }}
          />
        </button>
      );

    case "select":
      return (
        <select
          id={id}
          className={inputClass}
          value={typeof value === "string" ? value : ""}
          onChange={(event) => onChange(event.target.value || undefined)}
        >
          {field.optional ? <option value="">Default</option> : <option value="">Choose…</option>}
          {(field.options ?? []).map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      );

    case "dataset":
      return (
        <select
          id={id}
          className={inputClass}
          value={typeof value === "string" ? value : ""}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">Choose a dataset…</option>
          {datasets.map((dataset) => (
            <option key={dataset.id} value={dataset.id}>
              {dataset.name}
            </option>
          ))}
        </select>
      );

    case "column":
      return (
        <select
          id={id}
          className={inputClass}
          value={typeof value === "string" ? value : ""}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">Choose a column…</option>
          {columns.map((column) => (
            <option key={column} value={column}>
              {column}
            </option>
          ))}
        </select>
      );

    case "columns":
      return <ColumnPicker id={id} value={Array.isArray(value) ? (value as string[]) : []} columns={columns} onChange={onChange} />;

    case "mapping":
      return <MappingEditor value={(value ?? {}) as Record<string, string>} columns={columns} onChange={onChange} />;

    case "condition":
      return <ConditionEditor value={Array.isArray(value) ? (value as ConditionRow[]) : []} columns={columns} onChange={onChange} />;

    case "aggregations":
      return <AggregationEditor value={Array.isArray(value) ? (value as AggRow[]) : []} columns={columns} onChange={onChange} />;

    case "replacements":
      return <ReplacementEditor value={Array.isArray(value) ? (value as ReplaceRow[]) : []} onChange={onChange} />;

    default:
      return null;
  }
}

/** Multi-select over the dataset's real columns, as toggle chips. */
function ColumnPicker({
  id,
  value,
  columns,
  onChange,
}: {
  id: string;
  value: string[];
  columns: string[];
  onChange: (value: string[]) => void;
}) {
  const toggle = (column: string) =>
    onChange(value.includes(column) ? value.filter((item) => item !== column) : [...value, column]);

  if (columns.length === 0) {
    return (
      <input
        id={id}
        className={inputClass}
        value={value.join(", ")}
        placeholder="column_a, column_b"
        onChange={(event) =>
          onChange(event.target.value.split(",").map((item) => item.trim()).filter(Boolean))
        }
      />
    );
  }

  return (
    <div className="flex flex-wrap gap-1.5 rounded-lg border border-line bg-sunken p-2">
      {columns.map((column) => {
        const selected = value.includes(column);
        return (
          <button
            key={column}
            type="button"
            onClick={() => toggle(column)}
            className={cx(
              "rounded-md px-2 py-1 text-[11px] transition duration-[var(--duration-fast)]",
              selected
                ? "bg-[color:var(--accent)] text-accent-ink"
                : "bg-surface-2 text-ink-2 hover:bg-surface-2",
            )}
          >
            {column}
          </button>
        );
      })}
    </div>
  );
}

function MappingEditor({
  value,
  columns,
  onChange,
}: {
  value: Record<string, string>;
  columns: string[];
  onChange: (value: Record<string, string>) => void;
}) {
  const entries = Object.entries(value);
  const isCast = columns.length > 0 && entries.some(([, v]) => (CAST_TYPES as readonly string[]).includes(v));

  const update = (index: number, key: string, mapped: string) => {
    const next = entries.map((entry, position) => (position === index ? [key, mapped] : entry));
    onChange(Object.fromEntries(next.filter(([k]) => k)));
  };

  return (
    <div className="space-y-1.5">
      {entries.map(([key, mapped], index) => (
        <div key={index} className="flex items-center gap-1.5">
          <select
            className={cx(inputClass, "flex-1")}
            value={key}
            onChange={(event) => update(index, event.target.value, mapped)}
          >
            <option value="">Column…</option>
            {columns.map((column) => (
              <option key={column} value={column}>
                {column}
              </option>
            ))}
          </select>
          <Icon name="arrowRight" size={13} className="shrink-0 text-muted" />
          {isCast ? (
            <select
              className={cx(inputClass, "flex-1")}
              value={mapped}
              onChange={(event) => update(index, key, event.target.value)}
            >
              {CAST_TYPES.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          ) : (
            <input
              className={cx(inputClass, "flex-1")}
              value={mapped}
              placeholder="new value"
              onChange={(event) => update(index, key, event.target.value)}
            />
          )}
          <button
            type="button"
            onClick={() => onChange(Object.fromEntries(entries.filter((_, i) => i !== index)))}
            className="shrink-0 rounded-md p-1.5 text-muted transition hover:bg-surface-2 hover:text-danger"
            aria-label="Remove"
          >
            <Icon name="close" size={13} />
          </button>
        </div>
      ))}
      <AddRowButton
        label="Add mapping"
        onClick={() => onChange({ ...value, [`column_${entries.length + 1}`]: "" })}
      />
    </div>
  );
}

type ConditionRow = { column: string; operator: string; value: unknown };

function ConditionEditor({
  value,
  columns,
  onChange,
}: {
  value: ConditionRow[];
  columns: string[];
  onChange: (value: ConditionRow[]) => void;
}) {
  const update = (index: number, patch: Partial<ConditionRow>) =>
    onChange(value.map((row, position) => (position === index ? { ...row, ...patch } : row)));

  return (
    <div className="space-y-1.5">
      {value.map((row, index) => (
        <div key={index} className="space-y-1.5 rounded-lg border border-line bg-sunken p-2">
          <div className="flex items-center gap-1.5">
            <select
              className={cx(inputClass, "flex-1")}
              value={row.column}
              onChange={(event) => update(index, { column: event.target.value })}
            >
              <option value="">Column…</option>
              {columns.map((column) => (
                <option key={column} value={column}>
                  {column}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => onChange(value.filter((_, i) => i !== index))}
              className="shrink-0 rounded-md p-1.5 text-muted transition hover:bg-surface-2 hover:text-danger"
              aria-label="Remove condition"
            >
              <Icon name="close" size={13} />
            </button>
          </div>
          <div className="flex items-center gap-1.5">
            <select
              className={cx(inputClass, "flex-1")}
              value={row.operator}
              onChange={(event) => update(index, { operator: event.target.value })}
            >
              {FILTER_OPERATORS.map((operator) => (
                <option key={operator} value={operator}>
                  {operator.replace(/_/g, " ")}
                </option>
              ))}
            </select>
            <input
              className={cx(inputClass, "flex-1")}
              value={
                Array.isArray(row.value)
                  ? (row.value as unknown[]).join(", ")
                  : row.value === null || row.value === undefined
                    ? ""
                    : String(row.value)
              }
              placeholder={row.operator === "in" ? "a, b, c" : "value"}
              onChange={(event) =>
                update(index, {
                  value:
                    row.operator === "in"
                      ? event.target.value.split(",").map((item) => item.trim()).filter(Boolean)
                      : event.target.value,
                })
              }
            />
          </div>
        </div>
      ))}
      <AddRowButton
        label="Add condition"
        onClick={() => onChange([...value, { column: columns[0] ?? "", operator: "equals", value: "" }])}
      />
    </div>
  );
}

type AggRow = { column: string; function: string; alias?: string };

function AggregationEditor({
  value,
  columns,
  onChange,
}: {
  value: AggRow[];
  columns: string[];
  onChange: (value: AggRow[]) => void;
}) {
  const update = (index: number, patch: Partial<AggRow>) =>
    onChange(value.map((row, position) => (position === index ? { ...row, ...patch } : row)));

  return (
    <div className="space-y-1.5">
      {value.map((row, index) => (
        <div key={index} className="flex items-center gap-1.5">
          <select
            className={cx(inputClass, "flex-1")}
            value={row.column}
            onChange={(event) => update(index, { column: event.target.value })}
          >
            <option value="">Column…</option>
            {columns.map((column) => (
              <option key={column} value={column}>
                {column}
              </option>
            ))}
          </select>
          <select
            className={cx(inputClass, "w-[130px]")}
            value={row.function}
            onChange={(event) => update(index, { function: event.target.value })}
          >
            {AGGREGATION_FUNCTIONS.map((fn) => (
              <option key={fn} value={fn}>
                {fn}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => onChange(value.filter((_, i) => i !== index))}
            className="shrink-0 rounded-md p-1.5 text-muted transition hover:bg-surface-2 hover:text-danger"
            aria-label="Remove aggregation"
          >
            <Icon name="close" size={13} />
          </button>
        </div>
      ))}
      <AddRowButton
        label="Add aggregation"
        onClick={() => onChange([...value, { column: columns[0] ?? "", function: "sum" }])}
      />
    </div>
  );
}

type ReplaceRow = { find: string; replace_with: string };

function ReplacementEditor({
  value,
  onChange,
}: {
  value: ReplaceRow[];
  onChange: (value: ReplaceRow[]) => void;
}) {
  const update = (index: number, patch: Partial<ReplaceRow>) =>
    onChange(value.map((row, position) => (position === index ? { ...row, ...patch } : row)));

  return (
    <div className="space-y-1.5">
      {value.map((row, index) => (
        <div key={index} className="flex items-center gap-1.5">
          <input
            className={cx(inputClass, "flex-1")}
            value={row.find}
            placeholder="find"
            onChange={(event) => update(index, { find: event.target.value })}
          />
          <Icon name="arrowRight" size={13} className="shrink-0 text-muted" />
          <input
            className={cx(inputClass, "flex-1")}
            value={row.replace_with}
            placeholder="replace with"
            onChange={(event) => update(index, { replace_with: event.target.value })}
          />
          <button
            type="button"
            onClick={() => onChange(value.filter((_, i) => i !== index))}
            className="shrink-0 rounded-md p-1.5 text-muted transition hover:bg-surface-2 hover:text-danger"
            aria-label="Remove replacement"
          >
            <Icon name="close" size={13} />
          </button>
        </div>
      ))}
      <AddRowButton
        label="Add replacement"
        onClick={() => onChange([...value, { find: "", replace_with: "" }])}
      />
    </div>
  );
}

function AddRowButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-line py-1.5 text-[11px] text-ink-3 transition hover:border-line-strong hover:bg-surface hover:text-ink"
    >
      <Icon name="plus" size={12} />
      {label}
    </button>
  );
}

/**
 * A formula field, with the columns to hand.
 *
 * Monospaced because a formula is code, and column chips because the commonest
 * mistake by a distance is writing `amount` instead of `[amount]` -- clicking
 * the name inserts the brackets, so the mistake is harder to make than to avoid.
 */
function FormulaInput({
  id,
  field,
  value,
  columns,
  onChange,
}: {
  id: string;
  field: { placeholder?: string };
  value: unknown;
  columns: string[];
  onChange: (next: unknown) => void;
}) {
  const text = typeof value === "string" ? value : "";
  const inputRef = useRef<HTMLInputElement>(null);

  const insert = (snippet: string) => {
    const input = inputRef.current;
    const at = input?.selectionStart ?? text.length;
    onChange(text.slice(0, at) + snippet + text.slice(input?.selectionEnd ?? at));
    // Put the caret after what was just inserted, so typing continues naturally.
    requestAnimationFrame(() => {
      input?.focus();
      const position = at + snippet.length;
      input?.setSelectionRange(position, position);
    });
  };

  return (
    <div className="grid gap-1.5">
      <input
        id={id}
        ref={inputRef}
        className="h-9 w-full rounded-lg border border-line bg-sunken px-2.5 font-mono text-[12.5px] text-ink outline-none transition placeholder:text-faint focus:border-[color:var(--accent)] focus:ring-2 focus:ring-[color:var(--accent-soft)]"
        value={text}
        placeholder={field.placeholder}
        spellCheck={false}
        onChange={(event) => onChange(event.target.value)}
      />
      {columns.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {columns.slice(0, 12).map((column) => (
            <button
              key={column}
              type="button"
              onClick={() => insert(`[${column}]`)}
              title={`Insert [${column}]`}
              className="rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[10.5px] text-ink-3 transition hover:border-line-strong hover:text-ink"
            >
              {column}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

