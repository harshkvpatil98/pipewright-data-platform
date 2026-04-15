import type {
  TransformationPipelineCreatePayload,
  TransformationPipelineUpdatePayload,
  TransformationStep,
  TransformationStepType,
} from "@platform/shared-types";

export const transformationStepOptions: Array<{ value: TransformationStepType; label: string }> = [
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

export function parseCommaSeparatedList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function serializeCommaSeparatedList(values: string[] | undefined): string {
  return values?.join(", ") ?? "";
}

export function linesToMapping(value: string): Record<string, string> {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .reduce<Record<string, string>>((acc, line) => {
      const [rawKey, ...rawValue] = line.split(":");
      const key = rawKey?.trim();
      const mappedValue = rawValue.join(":").trim();
      if (key && mappedValue) {
        acc[key] = mappedValue;
      }
      return acc;
    }, {});
}

export function mappingToLines(mapping: Record<string, string> | undefined): string {
  return Object.entries(mapping ?? {})
    .map(([key, value]) => `${key}: ${value}`)
    .join("\n");
}

export function buildEmptyStep(stepType: TransformationStepType): TransformationStep {
  return {
    step_type: stepType,
    config: {},
  };
}

export function buildCreatePipelinePayload(input: {
  name: string;
  description: string;
  status: "draft" | "active";
  steps: TransformationStep[];
}): TransformationPipelineCreatePayload {
  return {
    name: input.name.trim(),
    description: input.description.trim() || null,
    status: input.status,
    steps_json: input.steps,
  };
}

export function buildUpdatePipelinePayload(input: {
  name: string;
  description: string;
  status: "draft" | "active";
  steps: TransformationStep[];
}): TransformationPipelineUpdatePayload {
  return {
    name: input.name.trim(),
    description: input.description.trim() || null,
    status: input.status,
    steps_json: input.steps,
  };
}
