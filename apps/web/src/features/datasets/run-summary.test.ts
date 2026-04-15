import type { PipelineRunRecord } from "@platform/shared-types";

import {
  getPipelineRunSecondaryText,
  isDatasetIngestionRunSummary,
  isSamplePipelineRunSummary,
} from "@/features/datasets/run-summary";

function buildRun(summary_json: PipelineRunRecord["summary_json"]): PipelineRunRecord {
  return {
    id: "run-1",
    project_id: "project-1",
    triggered_by_user_id: "user-1",
    pipeline_id: null,
    triggered_by_username: "platform-admin",
    run_type: "dataset_ingestion",
    status: "succeeded",
    started_at: null,
    completed_at: null,
    summary_json,
    logs_json: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

describe("run summary helpers", () => {
  it("detects dataset ingestion summaries", () => {
    const run = buildRun({
      ingestion_type: "dataset_upload",
      dataset: {
        id: "dataset-1",
        name: "Orders April",
        ingestion_status: "succeeded",
        row_count: 42,
        column_count: 6,
      },
      artifact: {
        original_filename: "orders.csv",
        stored_file_name: "abc_orders.csv",
        file_type: "csv",
        file_size_bytes: 2048,
      },
      profile: {
        duplicate_row_count: 0,
        duplicate_row_percentage: 0,
        completeness_score: 98.4,
      },
    });

    expect(isDatasetIngestionRunSummary(run.summary_json)).toBe(true);
    expect(getPipelineRunSecondaryText(run)).toBe("Orders April · CSV upload");
  });

  it("detects sample run summaries", () => {
    const run = buildRun({
      project_slug: "finance-quality",
      project_status: "active",
      project_source_count: 2,
      project_dataset_count: 3,
      project_run_count: 4,
      global_source_count_snapshot: 8,
    });

    expect(isSamplePipelineRunSummary(run.summary_json)).toBe(true);
    expect(getPipelineRunSecondaryText(run)).toBe("Project status snapshot: active");
  });

  it("falls back cleanly for unknown summaries", () => {
    const run = buildRun({ arbitrary: "value" });
    expect(getPipelineRunSecondaryText(run)).toBe("Stored orchestration summary available.");
  });
});
