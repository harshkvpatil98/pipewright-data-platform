/**
 * Where a dataset came from, in words, and the same name collapsed to one row.
 *
 * A dataset record does not say how it arrived; the run that produced it
 * does. Every database import and every recipe run currently writes a new
 * dataset (HANDOFF section 7), so a list of records shows "Orders" five times.
 * Grouping by name shows it once, with how many times it has been loaded and a
 * link to the newest, which is what a person means by "the Orders dataset".
 */

import type { DatasetRecord, PipelineRunRecord, StreamSource } from "@platform/shared-types";

export type DatasetOrigin = "upload" | "database" | "recipe" | "feed" | "other";

export const ORIGIN_LABELS: Record<DatasetOrigin, string> = {
  upload: "Uploaded file",
  database: "Database import",
  recipe: "Made by a recipe",
  feed: "Live feed",
  other: "Other",
};

const RUN_TYPE_ORIGIN: Record<string, DatasetOrigin> = {
  dataset_upload: "upload",
  dataset_ingestion: "upload",
  database_extraction: "database",
  dataset_transformation: "recipe",
  dataset_transformation_replay: "recipe",
};

/** What is known about where datasets came from, gathered once per page. */
export type OriginHints = {
  runTypeById: ReadonlyMap<string, string>;
  /** Datasets a live feed writes into; those carry no run of their own. */
  feedDatasetIds: ReadonlySet<string>;
};

export function originHints(runs: PipelineRunRecord[], feeds: StreamSource[] = []): OriginHints {
  return {
    runTypeById: new Map(runs.map((run) => [run.id, run.run_type])),
    feedDatasetIds: new Set(
      feeds.map((feed) => feed.dataset_id).filter((id): id is string => Boolean(id)),
    ),
  };
}

export function datasetOrigin(dataset: DatasetRecord, hints: OriginHints): DatasetOrigin {
  if (hints.feedDatasetIds.has(dataset.id)) return "feed";
  if (dataset.is_derived || dataset.created_from_pipeline_id) return "recipe";
  const runType = dataset.pipeline_run_id
    ? hints.runTypeById.get(dataset.pipeline_run_id)
    : undefined;
  if (runType && RUN_TYPE_ORIGIN[runType]) return RUN_TYPE_ORIGIN[runType];
  // Uploads predating run records still carry the file they came from.
  if (dataset.original_filename && !dataset.parent_dataset_id && !dataset.pipeline_run_id) {
    return "upload";
  }
  return "other";
}

export type DatasetGroup = {
  name: string;
  latest: DatasetRecord;
  /** Every record with this name, newest first. */
  versions: DatasetRecord[];
  origin: DatasetOrigin;
};

/** One row per dataset name, newest first by the latest load. */
export function groupDatasets(datasets: DatasetRecord[], hints: OriginHints): DatasetGroup[] {
  const byName = new Map<string, DatasetRecord[]>();
  for (const dataset of datasets) {
    const key = dataset.name.trim().toLowerCase();
    byName.set(key, [...(byName.get(key) ?? []), dataset]);
  }
  const groups: DatasetGroup[] = [];
  for (const records of byName.values()) {
    const versions = [...records].sort((a, b) => b.created_at.localeCompare(a.created_at));
    const latest = versions[0];
    groups.push({
      name: latest.name,
      latest,
      versions,
      origin: datasetOrigin(latest, hints),
    });
  }
  return groups.sort((a, b) => b.latest.created_at.localeCompare(a.latest.created_at));
}
