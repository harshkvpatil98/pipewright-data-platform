import type { WorkflowNodeInput } from "@platform/shared-types";

/**
 * What a task still needs before the workflow can run, in words, or null.
 * The same rules as `service_workflows.graph.missing_setting`, checked here
 * as the person builds so the note goes the moment they choose, rather than
 * after a save. The server still decides: a run is refused there too.
 */
export function missingSetting(node: Pick<WorkflowNodeInput, "node_type" | "config">): string | null {
  const config = (node.config ?? {}) as Record<string, unknown>;
  const hasDataset = Boolean(config.dataset_id || config.dataset_from);
  switch (node.node_type) {
    case "extraction":
      return config.extraction_job_id ? null : "choose which import it runs.";
    case "transformation":
      return config.pipeline_id ? null : "choose which recipe it runs.";
    case "quality_gate":
    case "drift_gate":
      return hasDataset ? null : "choose which dataset it checks.";
    case "publish":
      if (!config.destination_id) return "choose where it delivers to.";
      return hasDataset ? null : "choose which dataset it delivers.";
    case "reverse_etl":
      if (!hasDataset) return "choose which dataset it sends.";
      return config.connector_type && String(config.target ?? "").trim() ? null : "choose where it sends the rows.";
    default:
      return null;
  }
}
