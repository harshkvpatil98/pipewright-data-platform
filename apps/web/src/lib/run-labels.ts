/** Human-readable labels for `pipeline_runs.run_type` (operational UX only). */

const RUN_TYPE_LABELS: Record<string, string> = {
  sample_orchestration: "Sample run",
  dataset_ingestion: "File upload",
  dataset_upload: "File upload",
  database_extraction: "Database import",
  dataset_transformation: "Recipe run",
  dataset_transformation_replay: "Recipe replay",
  dataset_publish_postgres: "Delivered to PostgreSQL",
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
  schedule_run_failed: "Scheduled run",
  schedule_run_succeeded: "Scheduled run",
  dataset_publish_failed: "Delivery",
  dataset_publish_succeeded: "Delivery",
  transformation_run_failed: "Recipe run",
  transformation_run_succeeded: "Recipe run",
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
