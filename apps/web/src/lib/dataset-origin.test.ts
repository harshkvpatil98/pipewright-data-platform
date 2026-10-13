import { describe, expect, it } from "vitest";

import type { DatasetRecord, PipelineRunRecord } from "@platform/shared-types";

import { datasetOrigin, groupDatasets, originHints } from "@/lib/dataset-origin";

function dataset(overrides: Partial<DatasetRecord>): DatasetRecord {
  return {
    id: "d",
    project_id: "p",
    source_id: null,
    uploaded_by_user_id: null,
    pipeline_run_id: null,
    parent_dataset_id: null,
    created_from_pipeline_id: null,
    name: "Orders",
    original_filename: null,
    file_name: null,
    file_type: "csv",
    file_size_bytes: null,
    is_derived: false,
    status: "ready",
    ingestion_status: "succeeded",
    row_count: 10,
    column_count: 3,
    schema_snapshot: null,
    schema_json: null,
    profile_json: null,
    preview_json: null,
    ingestion_error: null,
    last_profiled_at: null,
    ingest_spec_json: null,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    ...overrides,
  } as DatasetRecord;
}

const run = (id: string, run_type: string) => ({ id, run_type }) as PipelineRunRecord;

describe("datasetOrigin", () => {
  const hints = originHints(
    [run("r-db", "database_extraction"), run("r-up", "dataset_upload")],
    [{ dataset_id: "d-feed" } as never],
  );

  it("reads the run that produced it", () => {
    expect(datasetOrigin(dataset({ pipeline_run_id: "r-db" }), hints)).toBe("database");
    expect(datasetOrigin(dataset({ pipeline_run_id: "r-up" }), hints)).toBe("upload");
  });

  it("knows recipe output and live feeds without a run", () => {
    expect(datasetOrigin(dataset({ is_derived: true }), hints)).toBe("recipe");
    expect(datasetOrigin(dataset({ id: "d-feed", original_filename: "feed.csv" }), hints)).toBe(
      "feed",
    );
  });

  it("does not call a database import a csv upload", () => {
    // Database imports are stored as CSV files; the file type is not the source.
    expect(
      datasetOrigin(dataset({ pipeline_run_id: "r-db", original_filename: "Orders.csv" }), hints),
    ).toBe("database");
  });
});

describe("groupDatasets", () => {
  it("shows a name once, newest load first, with every load kept", () => {
    const hints = originHints([run("r1", "database_extraction")]);
    const groups = groupDatasets(
      [
        dataset({ id: "a", name: "Orders", created_at: "2026-10-01T00:00:00Z", pipeline_run_id: "r1" }),
        dataset({ id: "b", name: "orders ", created_at: "2026-10-03T00:00:00Z", pipeline_run_id: "r1" }),
        dataset({ id: "c", name: "Customers", created_at: "2026-10-02T00:00:00Z" }),
      ],
      hints,
    );
    expect(groups.map((group) => group.latest.id)).toEqual(["b", "c"]);
    expect(groups[0].versions.map((record) => record.id)).toEqual(["b", "a"]);
    expect(groups[0].origin).toBe("database");
  });
});
