"use client";

import type {
  TransformationPreviewResponse,
  TransformationStep,
  TransformationStepType,
} from "@platform/shared-types";

export type EditorStep = TransformationStep & {
  id: string;
};

type StepDirection = "up" | "down";

type MappingRow = {
  from: string;
  to: string;
};

type ConditionRow = {
  column: string;
  operator: string;
  value: string;
};

export const STEP_TYPE_OPTIONS: Array<{ value: TransformationStepType; label: string }> = [
  { value: "rename_columns", label: "Rename Columns" },
  { value: "cast_column_types", label: "Cast Column Types" },
  { value: "trim_strings", label: "Trim Strings" },
  { value: "drop_columns", label: "Drop Columns" },
  { value: "select_columns", label: "Select Columns" },
  { value: "fill_nulls", label: "Fill Nulls" },
  { value: "drop_null_rows", label: "Drop Null Rows" },
  { value: "remove_duplicates", label: "Remove Duplicates" },
  { value: "filter_rows", label: "Filter Rows" },
  { value: "parse_dates", label: "Parse Dates" },
];

export const FILTER_OPERATOR_OPTIONS = [
  "equals",
  "not_equals",
  "greater_than",
  "greater_or_equal",
  "less_than",
  "less_or_equal",
  "contains",
  "in",
] as const;

export const CAST_TARGET_OPTIONS = ["string", "int", "float", "datetime", "boolean"] as const;
export const FILL_STRATEGY_OPTIONS = ["constant", "mean", "median", "mode"] as const;
export const DROP_NULL_HOW_OPTIONS = ["any", "all"] as const;
export const DUPLICATE_KEEP_OPTIONS = ["first", "last", "none"] as const;
export const PARSE_DATE_ERRORS_OPTIONS = ["coerce", "raise", "ignore"] as const;

export const SUPPORTED_STEP_TYPES: ReadonlySet<TransformationStepType> = new Set(
  STEP_TYPE_OPTIONS.map((option) => option.value),
);

export type StepFieldErrors = Partial<Record<string, string>>;

export type StepValidation = {
  valid: boolean;
  summary: string | null;
  fields: StepFieldErrors;
};

export function validatePipelineName(name: string): string | null {
  const trimmed = name.trim();
  if (!trimmed) {
    return "Pipeline name is required.";
  }
  if (trimmed.length < 2) {
    return "Pipeline name must be at least 2 characters.";
  }
  return null;
}

/** Stable JSON for comparing editor state to last loaded/saved baseline (dirty detection). */
export function serializePipelineEditorBaseline(state: {
  name: string;
  description: string;
  status: "draft" | "active";
  baseDatasetId: string | null;
  steps: EditorStep[];
}): string {
  return JSON.stringify({
    name: state.name,
    description: state.description,
    status: state.status,
    baseDatasetId: state.baseDatasetId,
    steps_json: toApiSteps(state.steps),
  });
}

export function validateEditorStep(step: EditorStep): StepValidation {
  const fields: StepFieldErrors = {};

  if (!SUPPORTED_STEP_TYPES.has(step.step_type)) {
    return {
      valid: false,
      summary: "This step type is not supported in the editor.",
      fields: { step_type: "Unsupported step type." },
    };
  }

  const config = step.config ?? {};

  switch (step.step_type) {
    case "rename_columns":
    case "cast_column_types": {
      const allowTypes = step.step_type === "cast_column_types";
      const rows = getMappingRows(config, allowTypes);
      let anyInvalid = false;
      rows.forEach((row, index) => {
        const fromOk = row.from.trim().length > 0;
        const toOk = row.to.trim().length > 0;
        if (!fromOk) {
          fields[`mapping_${index}_from`] = "Required.";
          anyInvalid = true;
        }
        if (!toOk) {
          fields[`mapping_${index}_to`] = "Required.";
          anyInvalid = true;
        }
      });
      return {
        valid: !anyInvalid,
        summary: anyInvalid ? "Complete all mapping rows." : null,
        fields,
      };
    }
    case "trim_strings":
    case "drop_columns":
    case "select_columns":
    case "parse_dates": {
      if (parseCommaSeparatedList(config.columns).length === 0) {
        fields.columns = "Add at least one column.";
        return {
          valid: false,
          summary: "Add at least one column.",
          fields,
        };
      }
      if (step.step_type === "parse_dates") {
        const err = String(config.errors ?? "coerce");
        if (!PARSE_DATE_ERRORS_OPTIONS.includes(err as (typeof PARSE_DATE_ERRORS_OPTIONS)[number])) {
          fields.errors = "Choose how to handle parse errors.";
          return { valid: false, summary: "Choose how to handle parse errors.", fields };
        }
      }
      return { valid: true, summary: null, fields };
    }
    case "fill_nulls": {
      const strategy = String(config.strategy ?? "constant");
      if (!FILL_STRATEGY_OPTIONS.includes(strategy as (typeof FILL_STRATEGY_OPTIONS)[number])) {
        fields.strategy = "Choose a fill strategy.";
        return { valid: false, summary: "Choose a fill strategy.", fields };
      }
      if (parseCommaSeparatedList(config.columns).length === 0) {
        fields.columns = "Add at least one column.";
        return { valid: false, summary: "Add at least one column.", fields };
      }
      if (strategy === "constant" && String(config.constant_value ?? "").trim() === "") {
        fields.constant_value = "Provide a constant value.";
        return { valid: false, summary: "Provide a constant value.", fields };
      }
      return { valid: true, summary: null, fields };
    }
    case "drop_null_rows": {
      const how = String(config.how ?? "");
      if (!DROP_NULL_HOW_OPTIONS.includes(how as (typeof DROP_NULL_HOW_OPTIONS)[number])) {
        fields.how = "Choose how null rows should be dropped.";
        return { valid: false, summary: "Choose how null rows should be dropped.", fields };
      }
      return { valid: true, summary: null, fields };
    }
    case "remove_duplicates": {
      const keep = String(config.keep ?? "");
      if (!DUPLICATE_KEEP_OPTIONS.includes(keep as (typeof DUPLICATE_KEEP_OPTIONS)[number])) {
        fields.keep = "Choose which duplicate row to keep.";
        return { valid: false, summary: "Choose which duplicate row to keep.", fields };
      }
      return { valid: true, summary: null, fields };
    }
    case "filter_rows": {
      const rows = getConditionRows(config);
      if (rows.length === 0) {
        fields.conditions = "Add at least one filter condition.";
        return { valid: false, summary: "Add at least one filter condition.", fields };
      }
      let anyInvalid = false;
      rows.forEach((row, index) => {
        const colOk = row.column.trim().length > 0;
        const opOk = row.operator.trim().length > 0;
        const valOk = row.value.trim().length > 0;
        if (!colOk) {
          fields[`condition_${index}_column`] = "Required.";
          anyInvalid = true;
        }
        if (!opOk) {
          fields[`condition_${index}_operator`] = "Required.";
          anyInvalid = true;
        }
        if (!valOk) {
          fields[`condition_${index}_value`] = "Required.";
          anyInvalid = true;
        }
      });
      return {
        valid: !anyInvalid,
        summary: anyInvalid ? "Complete all filter conditions." : null,
        fields,
      };
    }
    default:
      return { valid: true, summary: null, fields };
  }
}

export function isPipelineDraftValid(args: { name: string; steps: EditorStep[] }): boolean {
  if (validatePipelineName(args.name)) {
    return false;
  }
  return args.steps.every((step) => validateEditorStep(step).valid);
}

export function toEditorSteps(steps: TransformationStep[]): EditorStep[] {
  return steps.map((step) => ({
    id: makeEditorStepId(),
    step_type: step.step_type,
    config: structuredClone(step.config),
  }));
}

export function toApiSteps(steps: EditorStep[]): TransformationStep[] {
  return steps.map((step) => ({
    step_type: step.step_type,
    config: normalizeStepConfig(step),
  }));
}

export function createDefaultStep(stepType: TransformationStepType): EditorStep {
  return {
    id: makeEditorStepId(),
    step_type: stepType,
    config: defaultConfigForStep(stepType),
  };
}

export function addEditorStep(steps: EditorStep[], stepType: TransformationStepType): EditorStep[] {
  return [...steps, createDefaultStep(stepType)];
}

export function removeEditorStep(steps: EditorStep[], stepId: string): EditorStep[] {
  return steps.filter((step) => step.id !== stepId);
}

export function moveEditorStep(
  steps: EditorStep[],
  stepId: string,
  direction: StepDirection,
): EditorStep[] {
  const index = steps.findIndex((step) => step.id === stepId);
  if (index === -1) {
    return steps;
  }

  const targetIndex = direction === "up" ? index - 1 : index + 1;
  if (targetIndex < 0 || targetIndex >= steps.length) {
    return steps;
  }

  const next = [...steps];
  const [step] = next.splice(index, 1);
  next.splice(targetIndex, 0, step);
  return next;
}

export function updateEditorStep(
  steps: EditorStep[],
  stepId: string,
  updater: (step: EditorStep) => EditorStep,
): EditorStep[] {
  return steps.map((step) => (step.id === stepId ? updater(step) : step));
}

export function summarizeStep(step: EditorStep): string {
  const config = normalizeStepConfig(step);

  switch (step.step_type) {
    case "rename_columns":
      return summarizeCountRecord(config.mappings as Record<string, string> | undefined, "mapping");
    case "cast_column_types":
      return summarizeCountRecord(config.mappings as Record<string, string> | undefined, "cast");
    case "trim_strings":
    case "drop_columns":
    case "select_columns":
    case "parse_dates":
      return summarizeCountList(config.columns as string[] | undefined, "column");
    case "fill_nulls":
      return `${String(config.strategy ?? "constant")} · ${summarizeCountList(
        config.columns as string[] | undefined,
        "column",
      )}`;
    case "drop_null_rows":
      return `${String(config.how ?? "any")} · ${summarizeCountList(
        (config.columns as string[] | undefined) ?? [],
        "column",
        "all columns",
      )}`;
    case "remove_duplicates":
      return `${String(config.keep ?? "first")} · ${summarizeCountList(
        (config.subset as string[] | undefined) ?? [],
        "subset",
        "all columns",
      )}`;
    case "filter_rows":
      return summarizeCountList(
        (config.conditions as Array<Record<string, unknown>> | undefined) ?? [],
        "condition",
      );
    default:
      return "Configured step";
  }
}

export function getEditorStepError(step: EditorStep): string | null {
  return validateEditorStep(step).summary;
}

export function buildPipelineDraftPayload(args: {
  name: string;
  description: string;
  status: "draft" | "active";
  steps: EditorStep[];
}) {
  return {
    name: args.name.trim(),
    description: args.description.trim() || null,
    status: args.status,
    steps_json: toApiSteps(args.steps),
  };
}

export function getPreviewTotals(preview: TransformationPreviewResponse | null) {
  if (!preview) {
    return null;
  }

  return {
    rows: `${preview.row_count_before} -> ${preview.row_count_after}`,
    columns: `${preview.column_count_before} -> ${preview.column_count_after}`,
  };
}

export function parseCommaSeparatedList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((item) => String(item).trim())
      .filter(Boolean);
  }
  if (typeof value !== "string") {
    return [];
  }

  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function formatCommaSeparatedList(value: unknown): string {
  return parseCommaSeparatedList(value).join(", ");
}

export function getMappingRows(config: Record<string, unknown>, allowTypes = false): MappingRow[] {
  if (Array.isArray(config.rows)) {
    const rows = config.rows
      .map((item) => item as Record<string, unknown>)
      .map((row) => ({
        from: String(row.from ?? ""),
        to: String(row.to ?? ""),
      }));
    return rows.length > 0 ? rows : [{ from: "", to: allowTypes ? "string" : "" }];
  }

  const raw = config.mappings;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return [{ from: "", to: allowTypes ? "string" : "" }];
  }

  const entries = Object.entries(raw as Record<string, unknown>).map(([from, to]) => ({
    from,
    to: String(to ?? ""),
  }));
  return entries.length > 0 ? entries : [{ from: "", to: allowTypes ? "string" : "" }];
}

export function mappingRowsToConfig(rows: MappingRow[]): Record<string, string> {
  const mappings: Record<string, string> = {};
  for (const row of rows) {
    const from = row.from.trim();
    const to = row.to.trim();
    if (!from || !to) {
      continue;
    }
    mappings[from] = to;
  }
  return mappings;
}

export function getConditionRows(config: Record<string, unknown>): ConditionRow[] {
  const raw = Array.isArray(config.condition_rows)
    ? config.condition_rows
    : Array.isArray(config.conditions)
      ? config.conditions
      : [];
  const rows = raw.map((item) => {
    const condition = item as Record<string, unknown>;
    return {
      column: String(condition.column ?? ""),
      operator: String(condition.operator ?? "equals"),
      value: Array.isArray(condition.value)
        ? condition.value.map((value) => String(value)).join(", ")
        : String(condition.value ?? ""),
    };
  });

  return rows.length > 0 ? rows : [{ column: "", operator: "equals", value: "" }];
}

export function conditionRowsToConfig(rows: ConditionRow[]) {
  return rows
    .filter((row) => row.column.trim() || row.operator.trim() || row.value.trim())
    .map((row) => ({
      column: row.column.trim(),
      operator: row.operator.trim(),
      value:
        row.operator === "in"
          ? row.value
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean)
          : row.value.trim(),
    }));
}

function normalizeStepConfig(step: EditorStep): Record<string, unknown> {
  const config = step.config ?? {};

  switch (step.step_type) {
    case "rename_columns":
      return { mappings: mappingRowsToConfig(getMappingRows(config)) };
    case "cast_column_types":
      return { mappings: mappingRowsToConfig(getMappingRows(config, true)) };
    case "trim_strings":
    case "drop_columns":
    case "select_columns":
    case "parse_dates":
      return {
        ...config,
        columns: parseCommaSeparatedList(config.columns),
      };
    case "fill_nulls":
      return {
        strategy: String(config.strategy ?? "constant"),
        columns: parseCommaSeparatedList(config.columns),
        ...(String(config.strategy ?? "constant") === "constant"
          ? { constant_value: String(config.constant_value ?? "") }
          : {}),
      };
    case "drop_null_rows":
      return {
        how: String(config.how ?? "any"),
        ...(parseCommaSeparatedList(config.columns).length > 0
          ? { columns: parseCommaSeparatedList(config.columns) }
          : {}),
      };
    case "remove_duplicates":
      return {
        keep: String(config.keep ?? "first"),
        ...(parseCommaSeparatedList(config.subset).length > 0
          ? { subset: parseCommaSeparatedList(config.subset) }
          : {}),
      };
    case "filter_rows":
      return {
        conditions: conditionRowsToConfig(getConditionRows(config)),
      };
    default:
      return structuredClone(config);
  }
}

function defaultConfigForStep(stepType: TransformationStepType): Record<string, unknown> {
  switch (stepType) {
    case "rename_columns":
      return { rows: [{ from: "old_name", to: "new_name" }] };
    case "cast_column_types":
      return { rows: [{ from: "column_name", to: "string" }] };
    case "trim_strings":
    case "drop_columns":
    case "select_columns":
      return { columns: "" };
    case "fill_nulls":
      return { strategy: "constant", columns: "", constant_value: "" };
    case "drop_null_rows":
      return { columns: "", how: "any" };
    case "remove_duplicates":
      return { subset: "", keep: "first" };
    case "filter_rows":
      return {
        condition_rows: [
          {
            column: "",
            operator: "equals",
            value: "",
          },
        ],
      };
    case "parse_dates":
      return { columns: "", format: "", errors: "coerce" };
    default:
      return {};
  }
}

function summarizeCountList(
  items: ArrayLike<unknown> | undefined,
  label: string,
  emptyLabel = "Not configured",
): string {
  const count = items?.length ?? 0;
  if (!count) {
    return emptyLabel;
  }
  return `${count} ${label}${count === 1 ? "" : "s"}`;
}

function summarizeCountRecord(
  record: Record<string, unknown> | undefined,
  label: string,
): string {
  const count = record ? Object.keys(record).length : 0;
  if (!count) {
    return "Not configured";
  }
  return `${count} ${label}${count === 1 ? "" : "s"}`;
}

function makeEditorStepId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `step_${Math.random().toString(36).slice(2, 10)}`;
}
