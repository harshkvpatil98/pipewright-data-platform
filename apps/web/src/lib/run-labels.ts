/** Human-readable labels for `pipeline_runs.run_type` (operational UX only). */

const RUN_TYPE_LABELS: Record<string, string> = {
  sample_orchestration: "Sample orchestration",
  dataset_ingestion: "Dataset ingestion",
  dataset_transformation: "Transformation run",
  dataset_transformation_replay: "Transformation replay",
  dataset_publish_postgres: "PostgreSQL publish",
  dataset_publish_power_bi: "Power BI publish",
  dataset_publish_tableau: "Tableau publish",
};

/** Labels for `pipeline_runs.status` and schedule `last_run_status` (when set). */
const RUN_STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
};

/** Short labels for `user_notifications.type` badges. */
const NOTIFICATION_EVENT_LABELS: Record<string, string> = {
  schedule_run_failed: "Scheduled run",
  schedule_run_succeeded: "Scheduled run",
  dataset_publish_failed: "Dataset publish",
  dataset_publish_succeeded: "Dataset publish",
  transformation_run_failed: "Transformation",
  transformation_run_succeeded: "Transformation",
};

export function formatRunTypeLabel(runType: string | null | undefined): string {
  if (!runType) {
    return "Pipeline run";
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
