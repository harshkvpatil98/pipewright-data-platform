/** Contracts for metric history, anomalies, freshness, and incidents. */

export type IncidentStatus = "open" | "acknowledged" | "resolved";
export type IncidentSeverity = "low" | "medium" | "high" | "critical";
export type IncidentSource = "quality" | "drift" | "freshness" | "anomaly" | "workflow";
export type AnomalySensitivity = "low" | "medium" | "high";
export type FreshnessStatus = "fresh" | "stale" | "unknown";

export type MetricPoint = {
  value: number;
  captured_at: string;
  logical_date: string | null;
  workflow_run_id: string | null;
};

export type MetricSeries = {
  metric_key: string;
  column_name: string | null;
  label: string;
  unit: string | null;
  points: MetricPoint[];
  latest: number | null;
  previous: number | null;
  change_percentage: number | null;
};

export type MetricHistory = {
  dataset_id: string;
  series: MetricSeries[];
};

export type MetricCaptureResult = {
  dataset_id: string;
  metrics_recorded: number;
  captured_at: string;
};

export type Anomaly = {
  metric_key: string;
  column_name: string | null;
  label: string;
  value: number;
  baseline: number | null;
  score: number | null;
  status: "ok" | "anomalous" | "no_baseline";
  direction: "above" | "below" | "flat";
  sample_size: number;
  severity: IncidentSeverity;
  explanation: string;
};

export type AnomalyScan = {
  dataset_id: string;
  dataset_name: string;
  sensitivity: AnomalySensitivity;
  anomalies: Anomaly[];
  checked_count: number;
  summary: string;
};

export type FreshnessPolicy = {
  id: string;
  project_id: string;
  dataset_id: string;
  dataset_name: string | null;
  max_age_minutes: number;
  severity: IncidentSeverity;
  enabled: boolean;
  last_checked_at: string | null;
  last_status: string | null;
  last_age_minutes: number | null;
  created_at: string;
  updated_at: string;
};

export type FreshnessPolicyListResponse = {
  items: FreshnessPolicy[];
};

export type FreshnessCheckItem = {
  dataset_id: string;
  dataset_name: string;
  status: FreshnessStatus;
  age_minutes: number | null;
  max_age_minutes: number;
  overdue_minutes: number;
  explanation: string;
  incident_id: string | null;
};

export type FreshnessCheckResult = {
  checked: number;
  stale: number;
  incidents_opened: number;
  incidents_resolved: number;
  items: FreshnessCheckItem[];
};

export type IncidentEvent = {
  id: string;
  sequence: number;
  kind: string;
  message: string;
  actor_user_id: string | null;
  actor_name: string | null;
  data_json: Record<string, unknown> | null;
  created_at: string;
};

export type Incident = {
  id: string;
  project_id: string;
  title: string;
  summary: string | null;
  fingerprint: string;
  source_kind: IncidentSource;
  source_id: string | null;
  severity: IncidentSeverity;
  status: IncidentStatus;
  dataset_id: string | null;
  dataset_name: string | null;
  workflow_id: string | null;
  assignee_user_id: string | null;
  assignee_name: string | null;
  opened_at: string;
  last_seen_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  resolution_note: string | null;
  /** How many times this same problem has been seen since it opened. */
  occurrence_count: number;
  context_json: Record<string, unknown> | null;
};

export type IncidentDetail = Incident & {
  events: IncidentEvent[];
};

export type IncidentListResponse = {
  items: Incident[];
  open_count: number;
  acknowledged_count: number;
  resolved_count: number;
};
