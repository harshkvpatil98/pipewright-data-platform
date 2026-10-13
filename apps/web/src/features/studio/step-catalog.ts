import type { IconName } from "@/components/ui/icon";

/**
 * The built-in steps, as the Studio's "Add a step" palette and step settings
 * show them.
 *
 * Field keys and shapes here mirror the backend step validators exactly, so the
 * editor cannot produce a config the server will reject for structural reasons.
 * Adding a step here surfaces it in the palette and the step settings without
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
  /** What each option is called on screen, when the stored value is a code. */
  optionLabels?: Record<string, string>;
  optional?: boolean;
};

export type StepDefinition = {
  type: string;
  label: string;
  icon: IconName;
  group: StepGroup;
  summary: string;
  /** Other words people search for it by. */
  keywords?: string;
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

export const OPERATOR_LABELS: Record<(typeof FILTER_OPERATORS)[number], string> = {
  equals: "is",
  not_equals: "is not",
  greater_than: "is more than",
  greater_or_equal: "is at least",
  less_than: "is less than",
  less_or_equal: "is at most",
  contains: "contains",
  in: "is one of",
};

export const FUNCTION_LABELS: Record<(typeof AGGREGATION_FUNCTIONS)[number], string> = {
  sum: "Total",
  mean: "Average",
  min: "Lowest",
  max: "Highest",
  count: "Count",
  count_distinct: "Count different",
  median: "Median",
  std: "Spread (std. dev.)",
  first: "First",
  last: "Last",
};

export const CAST_TYPE_LABELS: Record<(typeof CAST_TYPES)[number], string> = {
  string: "Text",
  int: "Whole number",
  float: "Decimal number",
  datetime: "Date and time",
  boolean: "True or false",
};

export const STEP_CATALOG: StepDefinition[] = [
  // --- Columns ---
  {
    type: "select_columns",
    label: "Keep columns",
    icon: "columns",
    group: "Columns",
    summary: "Keep only the columns you name.",
    keywords: "choose select only pick subset",
    fields: [{ key: "columns", label: "Columns to keep", kind: "columns" }],
    defaults: { columns: [] },
  },
  {
    type: "drop_columns",
    label: "Remove columns",
    icon: "trash",
    group: "Columns",
    summary: "Drop columns you do not need.",
    keywords: "drop delete hide",
    fields: [{ key: "columns", label: "Columns to remove", kind: "columns" }],
    defaults: { columns: [] },
  },
  {
    type: "rename_columns",
    label: "Rename columns",
    icon: "table",
    group: "Columns",
    summary: "Give columns clearer names.",
    keywords: "name header title",
    fields: [{ key: "mappings", label: "Current name → new name", kind: "mapping" }],
    defaults: { mappings: {} },
  },
  {
    type: "derive_column",
    label: "Add a column",
    icon: "sparkles",
    group: "Columns",
    summary: "Compute a new column from a formula.",
    keywords: "formula calculate compute new derive expression",
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
    keywords: "convert number text type cast",
    fields: [
      {
        key: "mappings",
        label: "Column → type",
        kind: "mapping",
        help: "Pick a column and the type it should become.",
      },
    ],
    defaults: { mappings: {} },
  },
  {
    type: "split_column",
    label: "Split a column",
    icon: "columns",
    group: "Columns",
    summary: "Split one column into several by a delimiter.",
    keywords: "separate divide delimiter comma",
    fields: [
      { key: "column", label: "Column", kind: "column" },
      {
        key: "delimiter",
        label: "Split at",
        kind: "text",
        placeholder: ",",
        help: "The character between the parts, such as a comma. It starts as a space.",
      },
      { key: "into", label: "New column names", kind: "columns" },
      { key: "drop_original", label: "Remove the original column", kind: "boolean", optional: true },
    ],
    defaults: { column: "", delimiter: " ", into: [] },
  },

  // --- Rows ---
  {
    type: "filter_rows",
    label: "Filter rows",
    icon: "filter",
    group: "Rows",
    summary: "Keep only rows matching your conditions.",
    keywords: "where keep condition only matching",
    fields: [{ key: "conditions", label: "Conditions", kind: "condition" }],
    defaults: { conditions: [] },
  },
  {
    type: "sort_rows",
    label: "Sort rows",
    icon: "sort",
    group: "Rows",
    summary: "Order rows by one or more columns.",
    keywords: "order arrange ascending descending",
    fields: [
      { key: "columns", label: "Sort by", kind: "columns" },
      { key: "ascending", label: "Smallest first (A to Z)", kind: "boolean", optional: true },
    ],
    defaults: { columns: [], ascending: true },
  },
  {
    type: "limit_rows",
    label: "Keep the first rows",
    icon: "grid",
    group: "Rows",
    summary: "Keep a fixed number of rows.",
    keywords: "limit top head sample",
    fields: [
      { key: "count", label: "How many rows", kind: "number", placeholder: "100" },
      { key: "offset", label: "Skip this many first", kind: "number", optional: true },
    ],
    defaults: { count: 100 },
  },
  {
    type: "remove_duplicates",
    label: "Remove duplicates",
    icon: "refresh",
    group: "Rows",
    summary: "Remove repeated rows.",
    keywords: "dedupe unique distinct repeated",
    fields: [
      { key: "subset", label: "Match on columns", kind: "columns", optional: true },
      {
        key: "keep",
        label: "Which copy to keep",
        kind: "select",
        options: ["first", "last", "none"],
        optionLabels: { first: "The first one", last: "The last one", none: "None of them" },
        optional: true,
      },
    ],
    defaults: {},
  },

  // --- Clean ---
  {
    type: "fill_nulls",
    label: "Fill empty cells",
    icon: "check",
    group: "Clean",
    summary: "Replace missing values.",
    keywords: "missing blank null default",
    fields: [
      { key: "columns", label: "Columns", kind: "columns" },
      {
        key: "strategy",
        label: "Fill with",
        kind: "select",
        options: ["constant", "mean", "median", "mode"],
        optionLabels: {
          constant: "A value I type",
          mean: "The column's average",
          median: "The column's median",
          mode: "The most common value",
        },
      },
      {
        key: "constant_value",
        label: "Value",
        kind: "text",
        optional: true,
        help: "Used when filling with a value you type.",
      },
    ],
    defaults: { columns: [], strategy: "constant" },
  },
  {
    type: "drop_null_rows",
    label: "Remove empty rows",
    icon: "trash",
    group: "Clean",
    summary: "Remove rows with missing values.",
    keywords: "missing blank null drop",
    fields: [
      {
        key: "how",
        label: "Remove a row when",
        kind: "select",
        options: ["any", "all"],
        optionLabels: { any: "Any cell is empty", all: "Every cell is empty" },
      },
      {
        key: "columns",
        label: "Columns to check",
        kind: "columns",
        optional: true,
        help: "Leave empty to check every column.",
      },
    ],
    defaults: { how: "any" },
  },
  {
    type: "trim_strings",
    label: "Trim spaces",
    icon: "transform",
    group: "Clean",
    summary: "Remove spaces at the start and end of values.",
    keywords: "whitespace tidy strip clean",
    fields: [{ key: "columns", label: "Columns", kind: "columns" }],
    defaults: { columns: [] },
  },
  {
    type: "replace_values",
    label: "Find and replace",
    icon: "refresh",
    group: "Clean",
    summary: "Find and replace values in a column.",
    keywords: "substitute swap change",
    fields: [
      { key: "column", label: "Column", kind: "column" },
      { key: "replacements", label: "Find → replace with", kind: "replacements" },
      { key: "use_regex", label: "Treat as regular expression", kind: "boolean", optional: true },
    ],
    defaults: { column: "", replacements: [] },
  },
  {
    type: "parse_dates",
    label: "Read dates",
    icon: "clock",
    group: "Clean",
    summary: "Convert text into real dates.",
    keywords: "date time convert parse",
    fields: [
      { key: "columns", label: "Columns", kind: "columns" },
      {
        key: "format",
        label: "Format",
        kind: "text",
        optional: true,
        placeholder: "%Y-%m-%d",
        help: "Leave empty to work it out from the values.",
      },
      {
        key: "errors",
        label: "When a value is not a date",
        kind: "select",
        options: ["coerce", "raise", "ignore"],
        optionLabels: { coerce: "Leave it empty", raise: "Stop with an error", ignore: "Keep the text" },
        optional: true,
      },
    ],
    defaults: { columns: [] },
  },

  // --- Combine ---
  {
    type: "join_datasets",
    label: "Join another dataset",
    icon: "merge",
    group: "Combine",
    summary: "Bring in columns from another dataset.",
    keywords: "lookup merge combine vlookup match",
    fields: [
      { key: "right_dataset_id", label: "Dataset to join", kind: "dataset" },
      { key: "left_on", label: "This dataset's key(s)", kind: "columns" },
      { key: "right_on", label: "Other dataset's key(s)", kind: "columns", help: "Type the column names from the other dataset." },
      {
        key: "how",
        label: "Rows to keep",
        kind: "select",
        options: ["left", "inner", "right", "outer"],
        optionLabels: {
          left: "All rows here",
          inner: "Only matching rows",
          right: "All rows there",
          outer: "All rows from both",
        },
      },
    ],
    defaults: { right_dataset_id: "", left_on: [], right_on: [], how: "left" },
  },
  {
    type: "union_datasets",
    label: "Append another dataset",
    icon: "plus",
    group: "Combine",
    summary: "Stack another dataset's rows underneath.",
    keywords: "stack union combine add rows",
    fields: [
      { key: "other_dataset_id", label: "Dataset to append", kind: "dataset" },
      { key: "deduplicate", label: "Remove duplicate rows", kind: "boolean", optional: true },
      {
        key: "column_strategy",
        label: "If columns differ",
        kind: "select",
        options: ["union", "intersect", "strict"],
        optionLabels: {
          union: "Keep every column",
          intersect: "Keep only shared columns",
          strict: "Stop with an error",
        },
        optional: true,
      },
    ],
    defaults: { other_dataset_id: "" },
  },

  // --- Reshape ---
  {
    type: "aggregate",
    label: "Group and total",
    icon: "sigma",
    group: "Reshape",
    summary: "Summarise rows into totals per group.",
    keywords: "group by summarise sum count average aggregate",
    fields: [
      { key: "group_by", label: "Group by", kind: "columns", optional: true },
      { key: "aggregations", label: "Totals to work out", kind: "aggregations" },
    ],
    defaults: { group_by: [], aggregations: [] },
  },
  {
    type: "pivot",
    label: "Pivot",
    icon: "grid",
    group: "Reshape",
    summary: "Turn row values into columns.",
    keywords: "wide crosstab columns from values",
    fields: [
      { key: "index", label: "Rows", kind: "columns" },
      { key: "columns", label: "Column to fan out", kind: "column" },
      { key: "values", label: "Values", kind: "column" },
      {
        key: "aggregation",
        label: "Aggregate with",
        kind: "select",
        options: ["sum", "mean", "min", "max", "count"],
        optionLabels: { sum: "Total", mean: "Average", min: "Lowest", max: "Highest", count: "Count" },
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
    keywords: "long melt rows from columns",
    fields: [
      { key: "id_columns", label: "Keep as identifiers", kind: "columns" },
      { key: "value_columns", label: "Columns to unpivot", kind: "columns", optional: true },
    ],
    defaults: { id_columns: [] },
  },
];

export const STEP_BY_TYPE = new Map(STEP_CATALOG.map((step) => [step.type, step]));

export const STEP_GROUPS: StepGroup[] = ["Columns", "Rows", "Clean", "Combine", "Reshape"];

/** The broad kind of a column's type, as far as suggesting steps goes. */
export function columnKind(type: string | undefined): "number" | "date" | "text" | "other" {
  const value = (type ?? "").toLowerCase();
  if (/(int|float|double|decimal|numeric|real|number)/.test(value)) return "number";
  if (/(date|time)/.test(value)) return "date";
  if (/(str|text|char|utf8|object|string)/.test(value)) return "text";
  return "other";
}

/** The built-in steps worth offering first for a column of this type. */
export function suggestedFor(type: string | undefined): StepDefinition[] {
  const byKind: Record<ReturnType<typeof columnKind>, string[]> = {
    text: ["trim_strings", "replace_values", "fill_nulls", "drop_null_rows", "split_column", "cast_column_types"],
    number: ["filter_rows", "fill_nulls", "drop_null_rows", "cast_column_types"],
    date: ["filter_rows", "drop_null_rows", "fill_nulls"],
    other: ["filter_rows", "fill_nulls", "drop_null_rows", "cast_column_types"],
  };
  const types = [...byKind[columnKind(type)], "rename_columns", "drop_columns"];
  return types.map((stepType) => STEP_BY_TYPE.get(stepType)).filter((step): step is StepDefinition => !!step);
}

/**
 * A new step's settings, with the column it was started from already chosen.
 * Starting "Trim spaces" from the email column's menu should trim email
 * without asking which column again.
 */
export function prefillConfig(definition: StepDefinition, column: string | null): Record<string, unknown> {
  const config: Record<string, unknown> = structuredClone(definition.defaults ?? {});
  if (!column) return config;
  switch (definition.type) {
    case "filter_rows":
      return { ...config, conditions: [{ column, operator: "equals", value: "" }] };
    case "rename_columns":
      return { ...config, mappings: { [column]: "" } };
    case "cast_column_types":
      return { ...config, mappings: { [column]: "string" } };
    case "remove_duplicates":
      return { ...config, subset: [column] };
    default:
      break;
  }
  const field = definition.fields.find((candidate) => candidate.kind === "columns" || candidate.kind === "column");
  if (!field) return config;
  return { ...config, [field.key]: field.kind === "columns" ? [column] : column };
}
