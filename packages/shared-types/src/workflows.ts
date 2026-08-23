/** Contracts for workflow orchestration. Mirrors service-workflows schemas. */

export type WorkflowNodeType =
  | "extraction"
  | "transformation"
  | "quality_gate"
  | "drift_gate"
  | "publish"
  | "reverse_etl"
  | "notify";

export type EdgeCondition = "on_success" | "on_failure" | "always";

export type WorkflowTrigger = "manual" | "cron";

export type WorkflowNodeRecord = {
  id: string;
  node_key: string;
  name: string;
  node_type: WorkflowNodeType;
  config_json: Record<string, unknown>;
  continue_on_failure: boolean;
  position_x: number;
  position_y: number;
};

export type WorkflowEdgeRecord = {
  id: string;
  from_node_key: string;
  to_node_key: string;
  condition: EdgeCondition;
};

export type WorkflowSummary = {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  enabled: boolean;
  trigger_type: WorkflowTrigger;
  cron_expression: string | null;
  timezone: string | null;
  next_run_at: string | null;
  default_parameters: Record<string, unknown> | null;
  last_run_at: string | null;
  last_run_status: string | null;
  execution_count: number;
  created_at: string;
  updated_at: string;
};

export type GraphIssue = {
  code: string;
  message: string;
  node_key: string | null;
};

export type WorkflowValidation = {
  valid: boolean;
  errors: GraphIssue[];
  warnings: GraphIssue[];
};

export type WorkflowDetail = WorkflowSummary & {
  nodes: WorkflowNodeRecord[];
  edges: WorkflowEdgeRecord[];
  validation: WorkflowValidation;
  /** Nodes grouped into dependency levels; each level can run in parallel. */
  execution_order: string[][];
};

export type WorkflowListResponse = {
  items: WorkflowSummary[];
};

export type WorkflowNodeInput = {
  node_key: string;
  name: string;
  node_type: WorkflowNodeType;
  config: Record<string, unknown>;
  continue_on_failure: boolean;
  position_x: number;
  position_y: number;
};

export type WorkflowEdgeInput = {
  from_node_key: string;
  to_node_key: string;
  condition: EdgeCondition;
};

export type WorkflowRunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "partial"
  | "cancelled";

export type WorkflowNodeRunRecord = {
  id: string;
  node_key: string;
  node_name: string;
  node_type: WorkflowNodeType;
  status: "pending" | "running" | "succeeded" | "failed" | "skipped";
  sequence: number;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  output_json: Record<string, unknown> | null;
  message: string | null;
  skip_reason: string | null;
  pipeline_run_id: string | null;
};

export type WorkflowRunRecord = {
  id: string;
  workflow_id: string;
  project_id: string;
  status: WorkflowRunStatus;
  trigger: string;
  /** The slot this run represents; date macros resolve against it. */
  logical_date: string | null;
  parameters_json: Record<string, unknown> | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  nodes_total: number;
  nodes_succeeded: number;
  nodes_failed: number;
  nodes_skipped: number;
  created_at: string;
};

export type TimelineEntry = {
  node_key: string;
  node_name: string;
  node_type: WorkflowNodeType;
  status: string;
  /** Milliseconds from the start of the run, so bars can be positioned. */
  offset_ms: number;
  duration_ms: number;
  share_percentage: number;
};

export type RunTimeline = {
  total_ms: number;
  entries: TimelineEntry[];
  slowest_node_key: string | null;
  summary: string;
};

export type WorkflowRunDetail = WorkflowRunRecord & {
  node_runs: WorkflowNodeRunRecord[];
  timeline: RunTimeline | null;
};

export type NodeDiffVerdict =
  | "same"
  | "slower"
  | "faster"
  | "status_changed"
  | "output_changed"
  | "added"
  | "removed";

export type NodeDiff = {
  node_key: string;
  node_name: string;
  node_type: WorkflowNodeType;
  left_status: string | null;
  right_status: string | null;
  left_duration_ms: number | null;
  right_duration_ms: number | null;
  duration_change_percentage: number | null;
  verdict: NodeDiffVerdict;
  changes: string[];
};

export type RunDiff = {
  left_run_id: string;
  right_run_id: string;
  left: WorkflowRunRecord;
  right: WorkflowRunRecord;
  nodes: NodeDiff[];
  summary: string;
  identical: boolean;
};

export type WorkflowRunListResponse = {
  items: WorkflowRunRecord[];
};
