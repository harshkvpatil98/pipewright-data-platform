import type { IconName } from "@/components/ui/icon";

/**
 * The transformation catalogue the Studio ribbon is built from.
 *
 * Field keys and shapes here mirror the backend step validators exactly, so the
 * editor cannot produce a config the server will reject for structural reasons.
 * Adding a step here surfaces it in the ribbon and the step editor without
 * touching either component.
 */

export type FieldKind =
  | "text"
  | "formula"
  | "number"
  | "columns"
  | "column"
  | "select"
  | "boolean"
  | "mapping"
  | "condition"
  | "aggregations"
  | "replacements"
  | "dataset";

export type StepField = {
  key: string;
  label: string;
  kind: FieldKind;
  placeholder?: string;
  help?: string;
  options?: string[];
  optional?: boolean;
};

export type StepDefinition = {
  type: string;
  label: string;
  icon: IconName;
  group: StepGroup;
  summary: string;
  fields: StepField[];
  /** Values merged into the config when the step is added. */
  defaults?: Record<string, unknown>;
};

export type StepGroup = "Columns" | "Rows" | "Clean" | "Combine" | "Reshape";

export const FILTER_OPERATORS = [
  "equals",
  "not_equals",
  "greater_than",
  "greater_or_equal",
  "less_than",
  "less_or_equal",
  "contains",
  "in",
] as const;

export const AGGREGATION_FUNCTIONS = [
  "sum",
  "mean",
  "min",
  "max",
  "count",
  "count_distinct",
  "median",
  "std",
  "first",
  "last",
] as const;

export const CAST_TYPES = ["string", "int", "float", "datetime", "boolean"] as const;

export const STEP_CATALOG: StepDefinition[] = [
  // --- Columns ---
  {
    type: "select_columns",
    label: "Choose",
    icon: "columns",
    group: "Columns",
    summary: "Keep only the columns you name.",
    fields: [{ key: "columns", label: "Columns to keep", kind: "columns" }],
    defaults: { columns: [] },
  },
  {
    type: "drop_columns",
    label: "Remove",
    icon: "trash",
    group: "Columns",
    summary: "Drop columns you do not need.",
    fields: [{ key: "columns", label: "Columns to remove", kind: "columns" }],
    defaults: { columns: [] },
  },
  {
    type: "rename_columns",
    label: "Rename",
    icon: "table",
    group: "Columns",
    summary: "Give columns clearer names.",
    fields: [{ key: "mappings", label: "Current name → new name", kind: "mapping" }],
    defaults: { mappings: {} },
  },
  {
    type: "derive_column",
    label: "Add column",
    icon: "sparkles",
    group: "Columns",
    summary: "Compute a new column from a formula.",
    fields: [
      { key: "target_column", label: "New column name", kind: "text", placeholder: "total_with_tax" },
      {
        key: "formula",
        label: "Formula",
        kind: "formula",
        placeholder: "=ROUND([price] * [quantity] * 1.2, 2)",
        help: "Spreadsheet syntax. Column names go in square brackets; over 100 functions including IF, ROUND, UPPER, TRIM, CONCAT, COALESCE, DATEDIFF and REGEXEXTRACT.",
      },
      { key: "overwrite", label: "Replace if it already exists", kind: "boolean", optional: true },
    ],
    defaults: { target_column: "", formula: "" },
  },
  {
    type: "cast_column_types",
    label: "Change type",
    icon: "transform",
    group: "Columns",
    summary: "Convert columns to another data type.",
    fields: [
      {
        key: "mappings",
        label: "Column → type",
        kind: "mapping",
        help: `Allowed types: ${CAST_TYPES.join(", ")}.`,
      },
    ],
    defaults: { mappings: {} },
  },
  {
    type: "split_column",
    label: "Split",
    icon: "columns",
    group: "Columns",
    summary: "Split one column into several by a delimiter.",
    fields: [
      { key: "column", label: "Column", kind: "column" },
      { key: "delimiter", label: "Delimiter", kind: "text", placeholder: " " },
      { key: "into", label: "New column names", kind: "columns" },
      { key: "drop_original", label: "Remove the original column", kind: "boolean", optional: true },
    ],
    defaults: { column: "", delimiter: " ", into: [] },
  },

  // --- Rows ---
  {
    type: "filter_rows",
    label: "Filter",
    icon: "filter",
    group: "Rows",
    summary: "Keep only rows matching your conditions.",
    fields: [{ key: "conditions", label: "Conditions", kind: "condition" }],
    defaults: { conditions: [] },
  },
  {
    type: "sort_rows",
    label: "Sort",
    icon: "sort",
    group: "Rows",
    summary: "Order rows by one or more columns.",
    fields: [
      { key: "columns", label: "Sort by", kind: "columns" },
      { key: "ascending", label: "Ascending", kind: "boolean", optional: true },
    ],
    defaults: { columns: [], ascending: true },
  },
  {
    type: "limit_rows",
    label: "Limit",
    icon: "grid",
    group: "Rows",
    summary: "Keep a fixed number of rows.",
    fields: [
      { key: "count", label: "Row count", kind: "number", placeholder: "100" },
      { key: "offset", label: "Skip first N rows", kind: "number", optional: true },
    ],
    defaults: { count: 100 },
  },
  {
    type: "remove_duplicates",
    label: "Dedupe",
    icon: "refresh",
    group: "Rows",
    summary: "Remove repeated rows.",
    fields: [
      { key: "subset", label: "Match on columns", kind: "columns", optional: true },
      { key: "keep", label: "Keep", kind: "select", options: ["first", "last", "none"], optional: true },
    ],
    defaults: {},
  },

  // --- Clean ---
  {
    type: "fill_nulls",
    label: "Fill nulls",
    icon: "check",
    group: "Clean",
    summary: "Replace missing values.",
    fields: [
      { key: "columns", label: "Columns", kind: "columns" },
      { key: "strategy", label: "Strategy", kind: "select", options: ["constant", "mean", "median", "mode"] },
      {
        key: "constant_value",
        label: "Value",
        kind: "text",
        optional: true,
        help: "Used only with the constant strategy.",
      },
    ],
    defaults: { columns: [], strategy: "constant" },
  },
  {
    type: "drop_null_rows",
    label: "Drop nulls",
    icon: "trash",
    group: "Clean",
    summary: "Remove rows with missing values.",
    fields: [
      { key: "how", label: "Drop when", kind: "select", options: ["any", "all"] },
      { key: "columns", label: "Columns to check", kind: "columns", optional: true },
    ],
    defaults: { how: "any" },
  },
  {
    type: "trim_strings",
    label: "Trim",
    icon: "transform",
    group: "Clean",
    summary: "Strip leading and trailing whitespace.",
    fields: [{ key: "columns", label: "Columns", kind: "columns" }],
    defaults: { columns: [] },
  },
  {
    type: "replace_values",
    label: "Replace",
    icon: "refresh",
    group: "Clean",
    summary: "Find and replace values in a column.",
    fields: [
      { key: "column", label: "Column", kind: "column" },
      { key: "replacements", label: "Find → replace with", kind: "replacements" },
      { key: "use_regex", label: "Treat as regular expression", kind: "boolean", optional: true },
    ],
    defaults: { column: "", replacements: [] },
  },
  {
    type: "parse_dates",
    label: "Parse dates",
    icon: "clock",
    group: "Clean",
    summary: "Convert text into real dates.",
    fields: [
      { key: "columns", label: "Columns", kind: "columns" },
      { key: "format", label: "Format", kind: "text", optional: true, placeholder: "%Y-%m-%d" },
      { key: "errors", label: "On bad value", kind: "select", options: ["coerce", "raise", "ignore"], optional: true },
    ],
    defaults: { columns: [] },
  },

  // --- Combine ---
  {
    type: "join_datasets",
    label: "Join",
    icon: "merge",
    group: "Combine",
    summary: "Bring in columns from another dataset.",
    fields: [
      { key: "right_dataset_id", label: "Dataset to join", kind: "dataset" },
      { key: "left_on", label: "This dataset's key(s)", kind: "columns" },
      { key: "right_on", label: "Other dataset's key(s)", kind: "columns", help: "Type the column names from the other dataset." },
      { key: "how", label: "Join type", kind: "select", options: ["inner", "left", "right", "outer"] },
    ],
    defaults: { right_dataset_id: "", left_on: [], right_on: [], how: "left" },
  },
  {
    type: "union_datasets",
    label: "Append",
    icon: "plus",
    group: "Combine",
    summary: "Stack another dataset's rows underneath.",
    fields: [
      { key: "other_dataset_id", label: "Dataset to append", kind: "dataset" },
      { key: "deduplicate", label: "Remove duplicate rows", kind: "boolean", optional: true },
      {
        key: "column_strategy",
        label: "If columns differ",
        kind: "select",
        options: ["union", "intersect", "strict"],
        optional: true,
      },
    ],
    defaults: { other_dataset_id: "" },
  },

  // --- Reshape ---
  {
    type: "aggregate",
    label: "Group by",
    icon: "sigma",
    group: "Reshape",
    summary: "Summarise rows into totals per group.",
    fields: [
      { key: "group_by", label: "Group by", kind: "columns", optional: true },
      { key: "aggregations", label: "Aggregations", kind: "aggregations" },
    ],
    defaults: { group_by: [], aggregations: [] },
  },
  {
    type: "pivot",
    label: "Pivot",
    icon: "grid",
    group: "Reshape",
    summary: "Turn row values into columns.",
    fields: [
      { key: "index", label: "Rows", kind: "columns" },
      { key: "columns", label: "Column to fan out", kind: "column" },
      { key: "values", label: "Values", kind: "column" },
      {
        key: "aggregation",
        label: "Aggregate with",
        kind: "select",
        options: ["sum", "mean", "min", "max", "count"],
        optional: true,
      },
    ],
    defaults: { index: [], columns: "", values: "" },
  },
  {
    type: "unpivot",
    label: "Unpivot",
    icon: "grid",
    group: "Reshape",
    summary: "Turn columns into rows.",
    fields: [
      { key: "id_columns", label: "Keep as identifiers", kind: "columns" },
      { key: "value_columns", label: "Columns to unpivot", kind: "columns", optional: true },
    ],
    defaults: { id_columns: [] },
  },
];

export const STEP_BY_TYPE = new Map(STEP_CATALOG.map((step) => [step.type, step]));

export const STEP_GROUPS: StepGroup[] = ["Columns", "Rows", "Clean", "Combine", "Reshape"];
