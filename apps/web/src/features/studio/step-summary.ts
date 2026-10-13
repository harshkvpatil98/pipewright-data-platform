import {
  CAST_TYPE_LABELS,
  OPERATOR_LABELS,
} from "@/features/studio/step-catalog";

/**
 * What a step acts on, in a few words, for its line in the steps list:
 * "email", "amount is more than 0", "signup_date, newest first".
 *
 * An empty string means the step is not set up yet; the list says so in its
 * own words rather than this function guessing.
 */
export function describeStep(
  stepType: string,
  config: Record<string, unknown>,
  datasetNames: Map<string, string> = new Map(),
): string {
  const columns = (key: string) => names(asList(config[key]));
  const text = (key: string) => (typeof config[key] === "string" ? (config[key] as string) : "");

  switch (stepType) {
    case "select_columns":
    case "drop_columns":
    case "trim_strings":
    case "fill_nulls":
    case "parse_dates":
      return columns("columns");
    case "drop_null_rows": {
      const checked = columns("columns");
      if (checked) return `empty in ${checked}`;
      return config.how === "all" ? "rows with every cell empty" : "rows with any empty cell";
    }
    case "remove_duplicates": {
      const subset = columns("subset");
      return subset ? `matching on ${subset}` : "whole rows";
    }
    case "rename_columns":
    case "cast_column_types": {
      const entries = Object.entries(asRecord(config.mappings)).filter(([from]) => from);
      if (entries.length === 0) return "";
      const [from, to] = entries[0];
      const target =
        stepType === "cast_column_types"
          ? (CAST_TYPE_LABELS[to as keyof typeof CAST_TYPE_LABELS] ?? to).toLowerCase()
          : to;
      return `${from} → ${target}${more(entries.length - 1)}`;
    }
    case "derive_column":
      return text("target_column");
    case "split_column":
    case "replace_values":
      return text("column");
    case "filter_rows": {
      const conditions = asList(config.conditions) as { column?: string; operator?: string; value?: unknown }[];
      const first = conditions.find((condition) => condition?.column);
      if (!first) return "";
      const operator = OPERATOR_LABELS[first.operator as keyof typeof OPERATOR_LABELS] ?? first.operator ?? "";
      const value = Array.isArray(first.value) ? first.value.join(", ") : String(first.value ?? "");
      return `${first.column} ${operator} ${value}`.trim() + more(conditions.length - 1);
    }
    case "sort_rows": {
      const by = columns("columns");
      if (!by) return "";
      return `${by}, ${config.ascending === false ? "Z to A" : "A to Z"}`;
    }
    case "limit_rows":
      return typeof config.count === "number" ? `first ${config.count.toLocaleString()}` : "";
    case "join_datasets":
      return datasetNames.get(text("right_dataset_id")) ?? "";
    case "union_datasets":
      return datasetNames.get(text("other_dataset_id")) ?? "";
    case "aggregate": {
      const by = columns("group_by");
      return by ? `by ${by}` : "";
    }
    case "pivot":
      return text("columns");
    case "unpivot":
      return columns("id_columns");
    default:
      return "";
  }
}

function asList(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asRecord(value: unknown): Record<string, string> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, string>) : {};
}

function more(count: number): string {
  return count > 0 ? ` and ${count} more` : "";
}

function names(values: unknown[]): string {
  const list = values.filter((value): value is string => typeof value === "string" && value !== "");
  if (list.length <= 2) return list.join(", ");
  return `${list[0]}, ${list[1]}${more(list.length - 2)}`;
}
