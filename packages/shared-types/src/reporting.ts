/** Contracts for charts, dashboards, reports, the catalog, and the glossary. */

export type ChartTypeName =
  | "bar"
  | "column"
  | "line"
  | "area"
  | "scatter"
  | "pie"
  | "donut"
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

export type ExportFormat = "excel" | "csv" | "html" | "pdf";
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

/** A KPI's period comparison: the headline is the latest period's value and
 * this says what it is being compared with. */
export type KpiDelta = {
  period: "day" | "week" | "month" | "quarter" | "year";
  date_column: string;
  current_label: string;
  previous_label: string;
  current: number | null;
  previous: number | null;
  change: number | null;
  change_pct: number | null;
};

export type ChartData = {
  chart_type: ChartTypeName;
  labels: (string | number | null)[];
  series: ChartSeries[];
  row_count: number;
  truncated: boolean;
  warnings: string[];
  meta?: { delta?: KpiDelta } | null;
};

/** Options a chart can carry beyond its query. */
export type ChartOptions = {
  compare?: { date_column: string; period: KpiDelta["period"] } | null;
  [key: string]: unknown;
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
  /** When set, the chart's measure and filters come from this metric. */
  metric_id: string | null;
  metric_name: string | null;
  created_at: string;
  updated_at: string;
};

// -------------------------------------------------------------- metrics

/** One definition of a number: an aggregation over a column or a row-level
 * formula, with the filters that are part of its meaning and the dimensions
 * it may be cut by. Charts name it; changing it changes them all. */
export type Metric = {
  id: string;
  project_id: string;
  dataset_id: string;
  dataset_name: string | null;
  name: string;
  slug: string;
  description: string | null;
  owner_username: string | null;
  aggregation: AggregationName;
  column: string | null;
  formula: string | null;
  filters: ChartFilter[];
  dimensions: string[];
  valid_from: string | null;
  version_number: number;
  used_by_charts: number;
  created_at: string;
  updated_at: string;
};

export type MetricListResponse = { items: Metric[] };

export type MetricCreatePayload = {
  dataset_id: string;
  name: string;
  description?: string | null;
  owner_username?: string | null;
  aggregation: AggregationName;
  column?: string | null;
  formula?: string | null;
  filters?: ChartFilter[];
  dimensions?: string[];
  valid_from?: string | null;
};

export type MetricPreviewResponse = {
  metric_id: string;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  warnings: string[];
};

export type MetricSqlResponse = {
  metric_id: string;
  dialect: string;
  sql: string | null;
  reason: string | null;
  source_placeholder: string;
};

export type MetricUsageResponse = {
  metric_id: string;
  charts: { chart_id: string; chart_name: string; chart_type: ChartTypeName; dashboards: string[] }[];
};

export type ChartWithData = SavedChart & { data: ChartData };

export type ChartListResponse = { items: SavedChart[] };

/** One tile as a public share-link viewer sees it: name, shape, and data only. */
export type TileKind = "chart" | "text";

export type PublicChartTile = {
  kind: TileKind;
  name: string;
  description: string | null;
  chart_type: ChartTypeName | null;
  position: number;
  width: number;
  height: number;
  data: ChartData | null;
  body: string | null;
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
  kind: TileKind;
  chart_id: string | null;
  title: string | null;
  body: string | null;
  position: number;
  width: number;
  height: number;
  chart: SavedChart | null;
};

/** What the API accepts for one tile when a dashboard is created or saved. */
export type DashboardTileInput = {
  kind: TileKind;
  chart_id?: string | null;
  title?: string | null;
  body?: string | null;
  position?: number | null;
  width: number;
  height: number;
};

/** Auto-refresh cadences the API accepts (seconds); null means manual only. */
export const DASHBOARD_REFRESH_CHOICES = [30, 60, 300, 900, 1800, 3600] as const;
export type DashboardRefreshSeconds = (typeof DASHBOARD_REFRESH_CHOICES)[number];

export type Dashboard = {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  tile_count: number;
  /** Null until somebody shares it; presence is what makes it public. */
  share_token: string | null;
  shared_at: string | null;
  refresh_seconds: DashboardRefreshSeconds | null;
  created_at: string;
  updated_at: string;
};

export type DashboardDetail = Dashboard & {
  tiles: DashboardTile[];
  filters: ChartFilter[];
};

export type DashboardDataRequest = {
  /** When given, replaces the saved filters for this computation only. */
  filters?: ChartFilter[] | null;
};

export type DashboardTileData = {
  tile_id: string;
  kind: TileKind;
  position: number;
  width: number;
  height: number;
  title: string | null;
  body: string | null;
  chart_id: string | null;
  chart_name: string | null;
  chart_type: ChartTypeName | null;
  data: ChartData | null;
  error: string | null;
};

export type DashboardDataResponse = {
  dashboard_id: string;
  computed_at: string;
  filters_applied: ChartFilter[];
  tiles: DashboardTileData[];
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
  /** A Slack webhook or email notification target of the project, if any. */
  notification_target_id: string | null;
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
  run_count: number;
  created_at: string;
};

export type ReportListResponse = { items: ScheduledReport[] };

/** One channel a delivery was attempted on, and how it went. */
export type ReportDeliveryChannel = {
  channel: "in_app" | "slack" | "email" | "target" | string;
  ok: boolean;
  detail: string;
  target?: string;
  recipient?: string;
};

export type ReportDelivery = {
  id: string;
  report_id: string;
  status: string;
  file_format: string;
  file_size_bytes: number | null;
  row_count: number | null;
  generated_ms: number | null;
  message: string | null;
  channels: ReportDeliveryChannel[];
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

/** Fields a steward can change about a dataset from its catalog card. Every
 * field is optional; owner_username uses "" to clear and null-absent to leave. */
export type CatalogAnnotationUpdate = {
  description?: string | null;
  tags?: string[];
  certified?: boolean;
  column_notes?: Record<string, string>;
  owner_username?: string;
};

export type GlossaryBinding = {
  dataset_id: string;
  column: string;
};

/** Link an existing glossary term to one column of a dataset. */
export type DatasetTermLink = {
  term_id: string;
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
