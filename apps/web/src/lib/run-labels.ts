/** Human-readable labels for `pipeline_runs.run_type` (operational UX only). */

const RUN_TYPE_LABELS: Record<string, string> = {
  sample_orchestration: "Sample run",
  dataset_ingestion: "File upload",
  dataset_upload: "File upload",
  database_extraction: "Import",
  dataset_transformation: "Recipe run",
  dataset_transformation_replay: "Recipe replay",
  dataset_publish_postgres: "Delivered to PostgreSQL",
  dataset_delivery: "Delivery",
  database_copy: "Database copy",
  dataset_publish_power_bi: "Sent to Power BI",
  dataset_publish_tableau: "Sent to Tableau",
};

/** Labels for `pipeline_runs.status` and schedule `last_run_status` (when set). */
const RUN_STATUS_LABELS: Record<string, string> = {
  queued: "Waiting",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
};

/** Short labels for `user_notifications.type` badges. */
const NOTIFICATION_EVENT_LABELS: Record<string, string> = {
  schedule_run_failed: "Schedule",
  schedule_run_succeeded: "Schedule",
  dataset_publish_failed: "Delivery",
  dataset_publish_succeeded: "Delivery",
  transformation_run_failed: "Recipe run",
  transformation_run_succeeded: "Recipe run",
  workflow_run_failed: "Workflow",
  workflow_run_partial: "Workflow",
  workflow: "Workflow message",
  incident: "Incident",
  metric_alert: "Alert",
  data_contract: "Contract",
  live_source_failed: "Live feed",
  mention: "Mention",
  report: "Report",
};

export function formatRunTypeLabel(runType: string | null | undefined): string {
  if (!runType) {
    return "Run";
  }
  return RUN_TYPE_LABELS[runType] ?? runType.replace(/_/g, " ");
}

export function formatRunStatusLabel(status: string | null | undefined): string {
  if (!status) {
    return "—";
  }
  const key = status.toLowerCase();
  return RUN_STATUS_LABELS[key] ?? status.replace(/_/g, " ");
}

export function formatNotificationEventLabel(type: string | null | undefined): string {
  if (!type) {
    return "Notification";
  }
  return NOTIFICATION_EVENT_LABELS[type] ?? type.replace(/_/g, " ");
}

const STAGE_LABELS: Record<string, string> = {
  queued: "Waiting to start",
  running: "Started",
  upload: "Saving the file",
  parse: "Reading the rows",
  profile: "Working out the columns",
  materialize_profile: "Working out the columns",
  persist: "Saving",
  persist_artifact: "Saving the result",
  extract: "Reading the source",
  shape: "Cleaning at the source",
  merge: "Combining with earlier rows",
  schema_drift: "Checking for schema changes",
  load_artifact: "Reading the input dataset",
  load_dataset: "Reading the dataset",
  finalize: "Recording the version",
  connect_destination: "Connecting",
  authenticate_power_bi: "Signing in to Power BI",
  authenticate_tableau: "Signing in to Tableau",
  validate_workspace: "Checking the workspace",
  resolve_project: "Checking the project",
  prepare_publish_artifact: "Preparing the file",
  push_rows: "Sending the rows",
  publish_datasource: "Sending the file",
  succeeded: "Finished",
  failed: "Stopped",
};

/** A step in a run's history, in words: "parse" reads "Reading the rows". */
export function formatStageLabel(stage: string | null | undefined): string {
  if (!stage) return "Step";
  const step = /^apply_step_(\d+)$/.exec(stage);
  if (step) return `Step ${step[1]}`;
  return STAGE_LABELS[stage] ?? stage.replace(/_/g, " ").replace(/^./, (first) => first.toUpperCase());
}
