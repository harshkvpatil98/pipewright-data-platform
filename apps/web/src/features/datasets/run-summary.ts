import type {
  DatasetIngestionRunSummary,
  DatasetTransformationRunSummary,
  PipelineRunRecord,
  PipelineRunSummary,
  SamplePipelineRunSummary,
} from "@platform/shared-types";
import { countOf } from "@/lib/format";

export function isDatasetIngestionRunSummary(
  summary: PipelineRunSummary | null | undefined,
): summary is DatasetIngestionRunSummary {
  return (
    typeof summary === "object" &&
    summary !== null &&
    "ingestion_type" in summary &&
    summary.ingestion_type === "dataset_upload" &&
    "dataset" in summary &&
    typeof summary.dataset === "object" &&
    summary.dataset !== null &&
    "name" in summary.dataset &&
    typeof summary.dataset.name === "string"
  );
}

export function isSamplePipelineRunSummary(
  summary: PipelineRunSummary | null | undefined,
): summary is SamplePipelineRunSummary {
  return (
    typeof summary === "object" &&
    summary !== null &&
    "project_slug" in summary &&
    typeof summary.project_slug === "string" &&
    "project_status" in summary &&
    typeof summary.project_status === "string"
  );
}

export function isDatasetTransformationRunSummary(
  summary: PipelineRunSummary | null | undefined,
): summary is DatasetTransformationRunSummary {
  return (
    typeof summary === "object" &&
    summary !== null &&
    "transformation_type" in summary &&
    summary.transformation_type === "dataset_transformation" &&
    "pipeline" in summary &&
    typeof summary.pipeline === "object" &&
    summary.pipeline !== null &&
    "name" in summary.pipeline &&
    typeof summary.pipeline.name === "string"
  );
}

export function getPipelineRunSecondaryText(run: PipelineRunRecord): string {
  if (isDatasetIngestionRunSummary(run.summary_json)) {
    const artifact = run.summary_json.artifact;
    const dataset = run.summary_json.dataset;
    return `${dataset.name} · ${artifact.file_type.toUpperCase()} upload`;
  }

  if (isDatasetTransformationRunSummary(run.summary_json)) {
    return `Recipe “${run.summary_json.pipeline.name}”`;
  }

  if (isSamplePipelineRunSummary(run.summary_json)) {
    return `Project check: ${run.summary_json.project_status}`;
  }

  const sj = run.summary_json;
  if (
    typeof sj === "object" &&
    sj !== null &&
    "publish_type" in sj &&
    (sj as { publish_type?: string }).publish_type === "dataset_publish_power_bi"
  ) {
    const name =
      "dataset_name" in sj && typeof (sj as { dataset_name?: string }).dataset_name === "string"
        ? (sj as { dataset_name: string }).dataset_name
        : "Dataset";
    return `${name} · Power BI publish`;
  }

  if (
    typeof sj === "object" &&
    sj !== null &&
    "publish_type" in sj &&
    (sj as { publish_type?: string }).publish_type === "dataset_publish_tableau"
  ) {
    const name =
      "dataset_name" in sj && typeof (sj as { dataset_name?: string }).dataset_name === "string"
        ? (sj as { dataset_name: string }).dataset_name
        : "Dataset";
    return `${name} · Tableau publish`;
  }

  // A database import names its job, table and what it added.
  if (typeof sj === "object" && sj !== null && "extraction_type" in sj) {
    const extraction = sj as {
      job?: { name?: string };
      connection?: { name?: string };
      rows_added?: number;
    };
    const parts = [
      extraction.job?.name,
      extraction.connection?.name ? `from ${extraction.connection.name}` : undefined,
      typeof extraction.rows_added === "number"
        ? countOf(extraction.rows_added, "new row")
        : undefined,
    ].filter(Boolean);
    if (parts.length > 0) return parts.join(" · ");
  }

  return "Open for details.";
}
