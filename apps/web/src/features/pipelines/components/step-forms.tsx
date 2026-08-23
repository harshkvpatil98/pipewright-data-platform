"use client";

import { Button, FormField, Input, Select, Textarea } from "@platform/shared-ui";

import {
  CAST_TARGET_OPTIONS,
  DROP_NULL_HOW_OPTIONS,
  DUPLICATE_KEEP_OPTIONS,
  EditorStep,
  FILL_STRATEGY_OPTIONS,
  FILTER_OPERATOR_OPTIONS,
  PARSE_DATE_ERRORS_OPTIONS,
  StepFieldErrors,
  formatCommaSeparatedList,
  getConditionRows,
  getMappingRows,
} from "@/features/pipelines/pipeline-editor-state";

type StepFormProps = {
  step: EditorStep;
  onChange: (step: EditorStep) => void;
  fieldErrors?: StepFieldErrors;
};

export function StepFormRouter({ step, onChange, fieldErrors }: StepFormProps) {
  const err = fieldErrors ?? {};
  switch (step.step_type) {
    case "rename_columns":
      return (
        <MappingRowsForm
          step={step}
          onChange={onChange}
          fieldErrors={err}
          valueLabel="To"
          defaultValue=""
        />
      );
    case "cast_column_types":
      return (
        <MappingRowsForm
          step={step}
          onChange={onChange}
          fieldErrors={err}
          valueLabel="Target type"
          defaultValue="string"
          valueOptions={CAST_TARGET_OPTIONS}
        />
      );
    case "trim_strings":
      return (
        <CommaSeparatedColumnsForm
          step={step}
          onChange={onChange}
          fieldErrors={err}
          label="Columns"
          description="Comma-separated list of columns to trim."
          configKey="columns"
        />
      );
    case "drop_columns":
      return (
        <CommaSeparatedColumnsForm
          step={step}
          onChange={onChange}
          fieldErrors={err}
          label="Columns"
          description="Comma-separated list of columns to remove from the dataset."
          configKey="columns"
        />
      );
    case "select_columns":
      return (
        <CommaSeparatedColumnsForm
          step={step}
          onChange={onChange}
          fieldErrors={err}
          label="Columns"
          description="Keep only these columns, in this order."
          configKey="columns"
        />
      );
    case "fill_nulls":
      return <FillNullsForm step={step} onChange={onChange} fieldErrors={err} />;
    case "drop_null_rows":
      return <DropNullRowsForm step={step} onChange={onChange} fieldErrors={err} />;
    case "remove_duplicates":
      return <RemoveDuplicatesForm step={step} onChange={onChange} fieldErrors={err} />;
    case "filter_rows":
      return <FilterRowsForm step={step} onChange={onChange} fieldErrors={err} />;
    case "parse_dates":
      return <ParseDatesForm step={step} onChange={onChange} fieldErrors={err} />;
    default:
      return null;
  }
}

function MappingRowsForm({
  step,
  onChange,
  fieldErrors,
  valueLabel,
  defaultValue,
  valueOptions,
}: StepFormProps & {
  valueLabel: string;
  defaultValue: string;
  valueOptions?: readonly string[];
}) {
  const rows = getMappingRows(step.config, Boolean(valueOptions));

  const updateRows = (nextRows: Array<{ from: string; to: string }>) => {
    onChange({
      ...step,
      config: {
        ...step.config,
        rows: nextRows,
      },
    });
  };

  return (
    <div className="space-y-4">
      {rows.map((row, index) => (
        <div key={`${index}-${row.from}-${row.to}`} className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
          <FormField
            label="From"
            htmlFor={`${step.id}-from-${index}`}
            error={fieldErrors?.[`mapping_${index}_from`] ?? null}
          >
            <Input
              id={`${step.id}-from-${index}`}
              value={row.from}
              onChange={(event) =>
                updateRows(rows.map((item, itemIndex) => (itemIndex === index ? { ...item, from: event.target.value } : item)))
              }
              placeholder="old_name"
            />
          </FormField>
          <FormField
            label={valueLabel}
            htmlFor={`${step.id}-to-${index}`}
            error={fieldErrors?.[`mapping_${index}_to`] ?? null}
          >
            {valueOptions ? (
              <Select
                id={`${step.id}-to-${index}`}
                value={row.to || defaultValue}
                onChange={(event) =>
                  updateRows(rows.map((item, itemIndex) => (itemIndex === index ? { ...item, to: event.target.value } : item)))
                }
              >
                {valueOptions.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </Select>
            ) : (
              <Input
                id={`${step.id}-to-${index}`}
                value={row.to}
                onChange={(event) =>
                  updateRows(rows.map((item, itemIndex) => (itemIndex === index ? { ...item, to: event.target.value } : item)))
                }
                placeholder="new_name"
              />
            )}
          </FormField>
          <div className="flex items-end">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => updateRows(rows.filter((_, itemIndex) => itemIndex !== index))}
              disabled={rows.length === 1}
            >
              Remove
            </Button>
          </div>
        </div>
      ))}
      <Button
        variant="secondary"
        size="sm"
        onClick={() => updateRows([...rows, { from: "", to: defaultValue }])}
      >
        Add row
      </Button>
    </div>
  );
}

function CommaSeparatedColumnsForm({
  step,
  onChange,
  fieldErrors,
  label,
  description,
  configKey,
}: StepFormProps & {
  label: string;
  description: string;
  configKey: "columns" | "subset";
}) {
  return (
    <FormField
      label={label}
      htmlFor={`${step.id}-${configKey}`}
      description={description}
      error={fieldErrors?.[configKey] ?? null}
    >
      <Textarea
        id={`${step.id}-${configKey}`}
        value={formatCommaSeparatedList(step.config[configKey])}
        onChange={(event) =>
          onChange({
            ...step,
            config: {
              ...step.config,
              [configKey]: event.target.value,
            },
          })
        }
        className="min-h-[112px]"
        placeholder="customer_id, order_date, amount"
      />
    </FormField>
  );
}

function FillNullsForm({ step, onChange, fieldErrors }: StepFormProps) {
  const strategy = String(step.config.strategy ?? "constant");

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <FormField label="Strategy" htmlFor={`${step.id}-strategy`} error={fieldErrors?.strategy ?? null}>
          <Select
            id={`${step.id}-strategy`}
            value={strategy}
            onChange={(event) =>
              onChange({
                ...step,
                config: {
                  ...step.config,
                  strategy: event.target.value,
                },
              })
            }
          >
            {FILL_STRATEGY_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </Select>
        </FormField>
      </div>

      <CommaSeparatedColumnsForm
        step={step}
        onChange={onChange}
        fieldErrors={fieldErrors}
        label="Columns"
        description="Columns where null values should be filled."
        configKey="columns"
      />

      {strategy === "constant" ? (
        <FormField
          label="Constant value"
          htmlFor={`${step.id}-constant`}
          description="Sent as a string payload to the backend; the backend remains the source of truth."
          error={fieldErrors?.constant_value ?? null}
        >
          <Input
            id={`${step.id}-constant`}
            value={String(step.config.constant_value ?? "")}
            onChange={(event) =>
              onChange({
                ...step,
                config: {
                  ...step.config,
                  constant_value: event.target.value,
                },
              })
            }
            placeholder="0"
          />
        </FormField>
      ) : null}
    </div>
  );
}

function DropNullRowsForm({ step, onChange, fieldErrors }: StepFormProps) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <FormField label="How" htmlFor={`${step.id}-how`} error={fieldErrors?.how ?? null}>
          <Select
            id={`${step.id}-how`}
            value={String(step.config.how ?? "any")}
            onChange={(event) =>
              onChange({
                ...step,
                config: {
                  ...step.config,
                  how: event.target.value,
                },
              })
            }
          >
            {DROP_NULL_HOW_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </Select>
        </FormField>
      </div>

      <CommaSeparatedColumnsForm
        step={step}
        onChange={onChange}
        fieldErrors={fieldErrors}
        label="Columns"
        description="Optional subset of columns to inspect for null values."
        configKey="columns"
      />
    </div>
  );
}

function RemoveDuplicatesForm({ step, onChange, fieldErrors }: StepFormProps) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <FormField label="Keep" htmlFor={`${step.id}-keep`} error={fieldErrors?.keep ?? null}>
          <Select
            id={`${step.id}-keep`}
            value={String(step.config.keep ?? "first")}
            onChange={(event) =>
              onChange({
                ...step,
                config: {
                  ...step.config,
                  keep: event.target.value,
                },
              })
            }
          >
            {DUPLICATE_KEEP_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </Select>
        </FormField>
      </div>

      <CommaSeparatedColumnsForm
        step={step}
        onChange={onChange}
        fieldErrors={fieldErrors}
        label="Subset columns"
        description="Optional subset used to determine duplicate rows."
        configKey="subset"
      />
    </div>
  );
}

function FilterRowsForm({ step, onChange, fieldErrors }: StepFormProps) {
  const rows = getConditionRows(step.config);

  const updateRows = (nextRows: Array<{ column: string; operator: string; value: string }>) => {
    onChange({
      ...step,
      config: {
        ...step.config,
        condition_rows: nextRows,
      },
    });
  };

  return (
    <div className="space-y-4">
      {fieldErrors?.conditions ? (
        <div className="rounded-xl border border-danger-line bg-danger-soft px-3 py-2 text-sm text-danger">
          {fieldErrors.conditions}
        </div>
      ) : null}
      {rows.map((row, index) => (
        <div key={`${index}-${row.column}-${row.operator}`} className="grid gap-3 md:grid-cols-[1fr_1fr_1fr_auto]">
          <FormField
            label="Column"
            htmlFor={`${step.id}-column-${index}`}
            error={fieldErrors?.[`condition_${index}_column`] ?? null}
          >
            <Input
              id={`${step.id}-column-${index}`}
              value={row.column}
              onChange={(event) =>
                updateRows(rows.map((item, itemIndex) => (itemIndex === index ? { ...item, column: event.target.value } : item)))
              }
              placeholder="amount"
            />
          </FormField>
          <FormField
            label="Operator"
            htmlFor={`${step.id}-operator-${index}`}
            error={fieldErrors?.[`condition_${index}_operator`] ?? null}
          >
            <Select
              id={`${step.id}-operator-${index}`}
              value={row.operator}
              onChange={(event) =>
                updateRows(rows.map((item, itemIndex) => (itemIndex === index ? { ...item, operator: event.target.value } : item)))
              }
            >
              {FILTER_OPERATOR_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField
            label="Value"
            htmlFor={`${step.id}-value-${index}`}
            description={row.operator === "in" ? "Comma-separated values." : undefined}
            error={fieldErrors?.[`condition_${index}_value`] ?? null}
          >
            <Input
              id={`${step.id}-value-${index}`}
              value={row.value}
              onChange={(event) =>
                updateRows(rows.map((item, itemIndex) => (itemIndex === index ? { ...item, value: event.target.value } : item)))
              }
              placeholder={row.operator === "in" ? "active, pending" : "100"}
            />
          </FormField>
          <div className="flex items-end">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => updateRows(rows.filter((_, itemIndex) => itemIndex !== index))}
              disabled={rows.length === 1}
            >
              Remove
            </Button>
          </div>
        </div>
      ))}
      <Button
        variant="secondary"
        size="sm"
        onClick={() => updateRows([...rows, { column: "", operator: "equals", value: "" }])}
      >
        Add condition
      </Button>
    </div>
  );
}

function ParseDatesForm({ step, onChange, fieldErrors }: StepFormProps) {
  return (
    <div className="space-y-4">
      <CommaSeparatedColumnsForm
        step={step}
        onChange={onChange}
        fieldErrors={fieldErrors}
        label="Columns"
        description="Columns that should be parsed as datetimes."
        configKey="columns"
      />
      <div className="grid gap-4 md:grid-cols-2">
        <FormField label="Format" htmlFor={`${step.id}-format`} description="Optional datetime format string.">
          <Input
            id={`${step.id}-format`}
            value={String(step.config.format ?? "")}
            onChange={(event) =>
              onChange({
                ...step,
                config: {
                  ...step.config,
                  format: event.target.value,
                },
              })
            }
            placeholder="%Y-%m-%d"
          />
        </FormField>
        <FormField label="Errors" htmlFor={`${step.id}-errors`} error={fieldErrors?.errors ?? null}>
          <Select
            id={`${step.id}-errors`}
            value={String(step.config.errors ?? "coerce")}
            onChange={(event) =>
              onChange({
                ...step,
                config: {
                  ...step.config,
                  errors: event.target.value,
                },
              })
            }
          >
            {PARSE_DATE_ERRORS_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </Select>
        </FormField>
      </div>
    </div>
  );
}
