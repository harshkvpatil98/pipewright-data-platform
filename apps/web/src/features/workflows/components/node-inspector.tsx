"use client";

import { useId } from "react";

import type {
  DatasetRecord,
  EdgeCondition,
  WorkflowEdgeInput,
  WorkflowNodeInput,
} from "@platform/shared-types";

import { Icon } from "@/components/ui/icon";
import { NODE_META } from "@/features/workflows/components/workflow-canvas";
import { cx } from "@/lib/utils";

const inputClass =
  "h-9 w-full rounded-lg border border-line bg-sunken px-2.5 text-[13px] text-ink outline-none transition placeholder:text-faint focus:border-[color:var(--accent)] focus:ring-2 focus:ring-[color:var(--accent-soft)]";

/** Options a node's config needs, loaded once by the page. */
export type NodeOptions = {
  extractionJobs: { id: string; name: string }[];
  pipelines: { id: string; name: string }[];
  destinations: { id: string; name: string }[];
  datasets: DatasetRecord[];
};

type NodeInspectorProps = {
  node: WorkflowNodeInput;
  edges: WorkflowEdgeInput[];
  allNodes: WorkflowNodeInput[];
  options: NodeOptions;
  onChange: (node: WorkflowNodeInput) => void;
  onDelete: () => void;
  onChangeEdgeCondition: (from: string, to: string, condition: EdgeCondition) => void;
};

export function NodeInspector({
  node,
  edges,
  allNodes,
  options,
  onChange,
  onDelete,
  onChangeEdgeCondition,
}: NodeInspectorProps) {
  const fieldId = useId();
  const meta = NODE_META[node.node_type];

  const setConfig = (key: string, value: unknown) =>
    onChange({ ...node, config: { ...node.config, [key]: value } });

  const incoming = edges.filter((edge) => edge.to_node_key === node.node_key);
  const upstreamKeys = incoming.map((edge) => edge.from_node_key);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2.5">
        <span
          className="flex h-8 w-8 items-center justify-center rounded-lg"
          style={{ background: `color-mix(in srgb, ${meta.accent} 18%, transparent)` }}
        >
          <Icon name={meta.icon} size={16} />
        </span>
        <div className="min-w-0">
          <div className="truncate text-[13px] font-medium text-ink">{meta.label}</div>
          <div className="truncate font-mono text-[10px] text-muted">{node.node_key}</div>
        </div>
      </div>

      <Field label="Step name" htmlFor={`${fieldId}-name`}>
        <input
          id={`${fieldId}-name`}
          className={inputClass}
          value={node.name}
          onChange={(event) => onChange({ ...node, name: event.target.value })}
        />
      </Field>

      {node.node_type === "extraction" ? (
        <Field label="Extraction job" htmlFor={`${fieldId}-job`}>
          <select
            id={`${fieldId}-job`}
            className={inputClass}
            value={String(node.config.extraction_job_id ?? "")}
            onChange={(event) => setConfig("extraction_job_id", event.target.value)}
          >
            <option value="">Choose a job…</option>
            {options.extractionJobs.map((job) => (
              <option key={job.id} value={job.id}>
                {job.name}
              </option>
            ))}
          </select>
        </Field>
      ) : null}

      {node.node_type === "transformation" ? (
        <Field label="Pipeline" htmlFor={`${fieldId}-pipeline`}>
          <select
            id={`${fieldId}-pipeline`}
            className={inputClass}
            value={String(node.config.pipeline_id ?? "")}
            onChange={(event) => setConfig("pipeline_id", event.target.value)}
          >
            <option value="">Choose a pipeline…</option>
            {options.pipelines.map((pipeline) => (
              <option key={pipeline.id} value={pipeline.id}>
                {pipeline.name}
              </option>
            ))}
          </select>
        </Field>
      ) : null}

      {node.node_type === "quality_gate" || node.node_type === "publish" ? (
        <DatasetSource
          fieldId={fieldId}
          node={node}
          upstreamKeys={upstreamKeys}
          allNodes={allNodes}
          datasets={options.datasets}
          setConfig={setConfig}
        />
      ) : null}

      {node.node_type === "quality_gate" ? (
        <label className="flex items-start gap-2.5 text-[12px] text-ink-2">
          <input
            type="checkbox"
            checked={Boolean(node.config.quarantine)}
            onChange={(event) => setConfig("quarantine", event.target.checked)}
            className="mt-0.5 h-3.5 w-3.5 rounded border-line-strong bg-sunken"
          />
          <span>
            Quarantine failing rows
            <span className="mt-0.5 block text-[11px] text-muted">
              Passes the clean rows downstream instead of the original dataset.
            </span>
          </span>
        </label>
      ) : null}

      {node.node_type === "publish" ? (
        <>
          <Field label="Destination" htmlFor={`${fieldId}-destination`}>
            <select
              id={`${fieldId}-destination`}
              className={inputClass}
              value={String(node.config.destination_id ?? "")}
              onChange={(event) => setConfig("destination_id", event.target.value)}
            >
              <option value="">Choose a destination…</option>
              {options.destinations.map((destination) => (
                <option key={destination.id} value={destination.id}>
                  {destination.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Table name" htmlFor={`${fieldId}-table`}>
            <input
              id={`${fieldId}-table`}
              className={inputClass}
              value={String(node.config.table_name ?? "")}
              placeholder="public_orders"
              onChange={(event) => setConfig("table_name", event.target.value)}
            />
          </Field>
          <Field label="Write mode" htmlFor={`${fieldId}-mode`}>
            <select
              id={`${fieldId}-mode`}
              className={inputClass}
              value={String(node.config.write_mode ?? "replace")}
              onChange={(event) => setConfig("write_mode", event.target.value)}
            >
              <option value="replace">Replace the table</option>
              <option value="append">Append rows</option>
            </select>
          </Field>
        </>
      ) : null}

      {node.node_type === "notify" ? (
        <>
          <Field label="Title" htmlFor={`${fieldId}-title`}>
            <input
              id={`${fieldId}-title`}
              className={inputClass}
              value={String(node.config.title ?? "")}
              placeholder="Nightly load finished"
              onChange={(event) => setConfig("title", event.target.value)}
            />
          </Field>
          <Field label="Message" htmlFor={`${fieldId}-message`}>
            <textarea
              id={`${fieldId}-message`}
              className={cx(inputClass, "h-20 py-2")}
              value={String(node.config.message ?? "")}
              onChange={(event) => setConfig("message", event.target.value)}
            />
          </Field>
          <Field label="Level" htmlFor={`${fieldId}-level`}>
            <select
              id={`${fieldId}-level`}
              className={inputClass}
              value={String(node.config.level ?? "info")}
              onChange={(event) => setConfig("level", event.target.value)}
            >
              <option value="info">Info</option>
              <option value="warning">Warning</option>
              <option value="error">Error</option>
            </select>
          </Field>
        </>
      ) : null}

      <label className="flex items-start gap-2.5 text-[12px] text-ink-2">
        <input
          type="checkbox"
          checked={node.continue_on_failure}
          onChange={(event) => onChange({ ...node, continue_on_failure: event.target.checked })}
          className="mt-0.5 h-3.5 w-3.5 rounded border-line-strong bg-sunken"
        />
        <span>
          Keep going if this step fails
          <span className="mt-0.5 block text-[11px] text-muted">
            The run is marked partial rather than failed.
          </span>
        </span>
      </label>

      {incoming.length > 0 ? (
        <div>
          <div className="mb-1.5 text-[11px] uppercase tracking-[0.16em] text-muted">
            Runs after
          </div>
          <div className="space-y-1.5">
            {incoming.map((edge) => (
              <div
                key={`${edge.from_node_key}-${edge.to_node_key}`}
                className="flex items-center gap-2 rounded-lg bg-surface px-2 py-1.5"
              >
                <span className="min-w-0 flex-1 truncate text-[12px] text-ink">
                  {allNodes.find((item) => item.node_key === edge.from_node_key)?.name ??
                    edge.from_node_key}
                </span>
                <select
                  aria-label={`Condition from ${edge.from_node_key}`}
                  className="h-7 rounded-md border border-line bg-sunken px-1.5 text-[11px] text-ink outline-none"
                  value={edge.condition}
                  onChange={(event) =>
                    onChangeEdgeCondition(
                      edge.from_node_key,
                      edge.to_node_key,
                      event.target.value as EdgeCondition,
                    )
                  }
                >
                  <option value="on_success">on success</option>
                  <option value="on_failure">on failure</option>
                  <option value="always">always</option>
                </select>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <button
        type="button"
        onClick={onDelete}
        className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-danger-line py-2 text-[12px] text-danger transition hover:bg-danger-soft"
      >
        <Icon name="trash" size={13} />
        Remove step
      </button>
    </div>
  );
}

function DatasetSource({
  fieldId,
  node,
  upstreamKeys,
  allNodes,
  datasets,
  setConfig,
}: {
  fieldId: string;
  node: WorkflowNodeInput;
  upstreamKeys: string[];
  allNodes: WorkflowNodeInput[];
  datasets: DatasetRecord[];
  setConfig: (key: string, value: unknown) => void;
}) {
  const usingUpstream = Boolean(node.config.dataset_from);

  return (
    <div>
      <div className="mb-1.5 text-[12px] font-medium text-ink">Dataset</div>
      <div className="mb-2 flex rounded-lg border border-line p-0.5">
        <button
          type="button"
          onClick={() => {
            setConfig("dataset_from", upstreamKeys[0] ?? "");
            setConfig("dataset_id", undefined);
          }}
          disabled={upstreamKeys.length === 0}
          className={cx(
            "flex-1 rounded-md px-2 py-1 text-[11px] transition disabled:opacity-40",
            usingUpstream ? "bg-[color:var(--accent)] text-accent-ink" : "text-ink-3",
          )}
        >
          From a previous step
        </button>
        <button
          type="button"
          onClick={() => {
            setConfig("dataset_from", undefined);
            setConfig("dataset_id", "");
          }}
          className={cx(
            "flex-1 rounded-md px-2 py-1 text-[11px] transition",
            usingUpstream ? "text-ink-3" : "bg-[color:var(--accent)] text-accent-ink",
          )}
        >
          A fixed dataset
        </button>
      </div>

      {usingUpstream ? (
        <select
          aria-label="Upstream step"
          className={inputClass}
          value={String(node.config.dataset_from ?? "")}
          onChange={(event) => setConfig("dataset_from", event.target.value)}
        >
          <option value="">Choose a step…</option>
          {upstreamKeys.map((key) => (
            <option key={key} value={key}>
              {allNodes.find((item) => item.node_key === key)?.name ?? key}
            </option>
          ))}
        </select>
      ) : (
        <select
          id={`${fieldId}-dataset`}
          aria-label="Dataset"
          className={inputClass}
          value={String(node.config.dataset_id ?? "")}
          onChange={(event) => setConfig("dataset_id", event.target.value)}
        >
          <option value="">Choose a dataset…</option>
          {datasets.map((dataset) => (
            <option key={dataset.id} value={dataset.id}>
              {dataset.name}
            </option>
          ))}
        </select>
      )}

      {upstreamKeys.length === 0 && usingUpstream ? (
        <p className="mt-1.5 text-[11px] text-warning">
          Connect a step into this one first.
        </p>
      ) : (
        <p className="mt-1.5 text-[11px] text-muted">
          {usingUpstream
            ? "Uses whatever that step produced on this run."
            : "Always reads the same dataset."}
        </p>
      )}
    </div>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="mb-1.5 block text-[12px] font-medium text-ink">
        {label}
      </label>
      {children}
    </div>
  );
}
