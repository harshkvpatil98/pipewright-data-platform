/** Contracts for charts, dashboards, reports, the catalog, and the glossary. */

export type ChartTypeName =
  | "bar"
  | "column"
  | "line"
  | "area"
  | "scatter"
  | "pie"
  | "kpi"
  | "table";

export type AggregationName =
  | "sum"
  | "avg"
  | "mean"
  | "min"
  | "max"
  | "count"
  | "count_distinct"
  | "median";

export type ExportFormat = "excel" | "csv" | "html";
export type ReportSource = "dataset" | "chart" | "dashboard";

export type ChartMeasure = {
  column: string;
  aggregation: AggregationName;
  label: string | null;
};

export type ChartFilter = {
  column: string;
  operator: string;
  value: unknown;
};

export type ChartQuery = {
  dimensions: string[];
  measures: ChartMeasure[];
  filters: ChartFilter[];
  sort_by: string | null;
  descending: boolean;
  limit: number | null;
};

export type ChartTypeSpec = {
  name: ChartTypeName;
  label: string;
  description: string;
  min_dimensions: number;
  max_dimensions: number;
  min_measures: number;
  max_measures: number;
  /** Above this many categories the chart stops communicating anything. */
  max_categories: number | null;
};

export type ChartCatalogResponse = {
  items: ChartTypeSpec[];
  aggregations: AggregationName[];
  filter_operators: string[];
};

export type ChartSeries = {
  name: string;
  values: (number | string | null)[];
};

export type ChartData = {
  chart_type: ChartTypeName;
  labels: (string | number | null)[];
  series: ChartSeries[];
  row_count: number;
  truncated: boolean;
  warnings: string[];
};

export type SavedChart = {
  id: string;
  project_id: string;
  dataset_id: string;
  dataset_name: string | null;
  name: string;
  description: string | null;
  chart_type: ChartTypeName;
  query: ChartQuery;
  options: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type ChartWithData = SavedChart & { data: ChartData };

export type ChartListResponse = { items: SavedChart[] };

/** One tile as a public share-link viewer sees it: name, shape, and data only. */
export type PublicChartTile = {
  name: string;
  description: string | null;
  chart_type: ChartTypeName;
  position: number;
  width: number;
  height: number;
  data: ChartData;
};

/** A shared dashboard rendered for someone holding only the link. */
export type PublicDashboardView = {
  name: string;
  description: string | null;
  shared_at: string | null;
  tiles: PublicChartTile[];
};

export type PivotResponse = {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  warnings: string[];
};

export type DashboardTile = {
  id: string;
  chart_id: string;
  position: number;
  width: number;
  height: number;
  chart: SavedChart;
};

export type Dashboard = {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  tile_count: number;
  /** Null until somebody shares it; presence is what makes it public. */
  share_token: string | null;
  shared_at: string | null;
  created_at: string;
  updated_at: string;
};

export type DashboardDetail = Dashboard & {
  tiles: DashboardTile[];
  filters: ChartFilter[];
};

export type DashboardListResponse = { items: Dashboard[] };

export type ScheduledReport = {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  source_kind: ReportSource;
  source_id: string;
  file_format: ExportFormat;
  cron_expression: string | null;
  timezone: string | null;
  enabled: boolean;
  next_run_at: string | null;
  recipients: string[];
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
  run_count: number;
  created_at: string;
};

export type ReportListResponse = { items: ScheduledReport[] };

export type ReportDelivery = {
  id: string;
  report_id: string;
  status: string;
  file_format: string;
  file_size_bytes: number | null;
  row_count: number | null;
  generated_ms: number | null;
  message: string | null;
  created_at: string;
};

export type DeliveryListResponse = { items: ReportDelivery[] };

export type CatalogHit = {
  dataset_id: string;
  name: string;
  score: number;
  /** Kept apart from score so a name match outranks incidental column hits. */
  name_score: number;
  reasons: string[];
  matched_columns: string[];
  certified: boolean;
  owner: string | null;
  tags: string[];
  description: string | null;
  row_count: number | null;
};

export type CatalogSearchResponse = {
  query: string;
  items: CatalogHit[];
  total_datasets: number;
  certified_count: number;
  tags: string[];
};

export type CatalogAnnotation = {
  dataset_id: string;
  description: string | null;
  tags: string[];
  certified: boolean;
  certified_at: string | null;
  certified_by_username: string | null;
  owner_username: string | null;
  column_notes: Record<string, string>;
};

export type GlossaryBinding = {
  dataset_id: string;
  column: string;
};

export type GlossaryTerm = {
  id: string;
  project_id: string;
  term: string;
  slug: string;
  definition: string;
  synonyms: string[];
  bindings: GlossaryBinding[];
  owner_username: string | null;
  created_at: string;
  updated_at: string;
};

export type TermListResponse = { items: GlossaryTerm[] };
