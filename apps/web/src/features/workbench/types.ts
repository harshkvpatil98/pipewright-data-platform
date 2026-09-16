export type { Statement } from "./editor-state";

export type Connection = { id: string; name: string; connector_type: string; status: string };

export type Verdict = {
  allowed: boolean;
  reason: string;
  warnings: string[];
  needs_confirmation: boolean;
};

export type Policy = {
  allow_writes: boolean;
  allow_ddl: boolean;
  environment: string;
  row_limit: number;
  description: string;
};

export type PlanResponse = {
  statements: import("./editor-state").Statement[];
  parameters: string[];
  policy: Policy;
  verdict: Verdict;
};

export type StatementResult = {
  index: number;
  sql: string;
  summary: string;
  kind: string;
  duration_ms: number;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  rows_affected: number | null;
  error: string | null;
  skipped: boolean;
};

export type RunResponse = {
  statements: StatementResult[];
  duration_ms: number;
  committed: boolean;
  warnings: string[];
  policy: string;
};

export type ColumnInfo = {
  name: string;
  type: string;
  nullable: boolean;
  primary_key: boolean;
};

export type TableInfo = {
  name: string;
  table_schema: string | null;
  kind: string;
  qualified: string;
  columns: ColumnInfo[];
  loaded: boolean;
};

export type SchemaResponse = {
  dialect: string;
  default_schema: string | null;
  tables: TableInfo[];
  truncated: boolean;
};

export type Completion = { label: string; kind: string; detail: string; insert: string };

export type SavedQuery = {
  id: string;
  name: string;
  description: string | null;
  sql: string;
  parameters: Record<string, unknown>;
  run_count: number;
  last_run_at: string | null;
};

export type QueryRun = {
  id: string;
  sql: string;
  statement_count: number;
  wrote: boolean;
  succeeded: boolean;
  duration_ms: number;
  rows_returned: number;
  rows_affected: number;
  error: string | null;
  created_at: string;
};

export type ExplainResponse = {
  dialect: string;
  text: string;
  rows: Record<string, unknown>[];
  estimated_cost: number | null;
  estimated_rows: number | null;
  notes: string[];
};
