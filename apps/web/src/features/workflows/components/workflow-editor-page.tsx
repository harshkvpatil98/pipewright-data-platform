"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  AuthUser,
  EdgeCondition,
  WorkflowDetail,
  WorkflowEdgeInput,
  WorkflowNodeInput,
  WorkflowNodeRunRecord,
  WorkflowNodeType,
  WorkflowRunDetail,
  WorkflowRunRecord,
} from "@platform/shared-types";

import { useToast } from "@/components/providers/toast-provider";
import { AppFrame } from "@/components/shell/app-frame";
import type { RibbonGroup } from "@/components/shell/ribbon";
import { Icon } from "@/components/ui/icon";
import { toNodeKey, tidyLayout } from "@/features/workflows/canvas-geometry";
import { BackfillDialog } from "@/features/workflows/components/backfill-dialog";
import { NodeInspector, type NodeOptions } from "@/features/workflows/components/node-inspector";
import { RunDiffPanel } from "@/features/workflows/components/run-diff-panel";
import { VersionHistoryPanel } from "@/features/workflows/components/version-history-panel";
import { RunTimelineView } from "@/features/workflows/components/run-timeline";
import { NODE_META, WorkflowCanvas } from "@/features/workflows/components/workflow-canvas";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { cx } from "@/lib/utils";

type WorkflowEditorPageProps = {
  currentUser: AuthUser;
  projectId: string;
  projectName: string;
  workflow: WorkflowDetail;
  options: NodeOptions;
};

const NODE_ORDER: WorkflowNodeType[] = [
  "extraction",
  "transformation",
  "quality_gate",
  "publish",
  "notify",
];

/** How often to re-check a run that is still in flight. */
const POLL_MS = 1500;

export function WorkflowEditorPage({
  currentUser,
  projectId,
  projectName,
  workflow,
  options,
}: WorkflowEditorPageProps) {
  const toast = useToast();

  const [nodes, setNodes] = useState<WorkflowNodeInput[]>(() =>
    workflow.nodes.map((node) => ({
      node_key: node.node_key,
      name: node.name,
      node_type: node.node_type,
      config: node.config_json,
      continue_on_failure: node.continue_on_failure,
      position_x: node.position_x,
      position_y: node.position_y,
    })),
  );
  const [edges, setEdges] = useState<WorkflowEdgeInput[]>(() =>
    workflow.edges.map((edge) => ({
      from_node_key: edge.from_node_key,
      to_node_key: edge.to_node_key,
      condition: edge.condition,
    })),
  );
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [validation, setValidation] = useState(workflow.validation);
  const [executionOrder, setExecutionOrder] = useState(workflow.execution_order);

  const [activeRun, setActiveRun] = useState<WorkflowRunDetail | null>(null);
  const [showRuns, setShowRuns] = useState(false);
  const [showBackfill, setShowBackfill] = useState(false);
  const [runs, setRuns] = useState<WorkflowRunRecord[]>([]);
  // The older run in a comparison; the active run is always the newer side.
  const [compareRunId, setCompareRunId] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const selected = useMemo(
    () => nodes.find((node) => node.node_key === selectedKey) ?? null,
    [nodes, selectedKey],
  );

  const nodeRuns = useMemo<Record<string, WorkflowNodeRunRecord>>(() => {
    if (!activeRun) return {};
    return Object.fromEntries(activeRun.node_runs.map((run) => [run.node_key, run]));
  }, [activeRun]);

  const mutate = useCallback(() => setDirty(true), []);

  // ------------------------------------------------------------------ editing

  const addNode = useCallback(
    (type: WorkflowNodeType) => {
      setNodes((current) => {
        const key = toNodeKey(NODE_META[type].label, current.map((node) => node.node_key));
        // Drop new nodes in a free column so they never land on top of another.
        const next: WorkflowNodeInput = {
          node_key: key,
          name: NODE_META[type].label,
          node_type: type,
          config: {},
          continue_on_failure: false,
          position_x: 40 + (current.length % 4) * 240,
          position_y: 40 + Math.floor(current.length / 4) * 120,
        };
        setSelectedKey(key);
        return [...current, next];
      });
      mutate();
    },
    [mutate],
  );

  const updateNode = useCallback(
    (updated: WorkflowNodeInput) => {
      setNodes((current) =>
        current.map((node) => (node.node_key === updated.node_key ? updated : node)),
      );
      mutate();
    },
    [mutate],
  );

  const moveNode = useCallback((key: string, x: number, y: number) => {
    setNodes((current) =>
      current.map((node) =>
        node.node_key === key ? { ...node, position_x: x, position_y: y } : node,
      ),
    );
    setDirty(true);
  }, []);

  const deleteNode = useCallback(
    (key: string) => {
      setNodes((current) => current.filter((node) => node.node_key !== key));
      // Edges referencing a removed node would fail validation, so drop them too.
      setEdges((current) =>
        current.filter((edge) => edge.from_node_key !== key && edge.to_node_key !== key),
      );
      setSelectedKey(null);
      mutate();
    },
    [mutate],
  );

  const connect = useCallback(
    (fromKey: string, toKey: string) => {
      setEdges((current) => {
        const exists = current.some(
          (edge) => edge.from_node_key === fromKey && edge.to_node_key === toKey,
        );
        if (exists) return current;
        return [...current, { from_node_key: fromKey, to_node_key: toKey, condition: "on_success" }];
      });
      mutate();
    },
    [mutate],
  );

  const deleteEdge = useCallback(
    (from: string, to: string) => {
      setEdges((current) =>
        current.filter((edge) => !(edge.from_node_key === from && edge.to_node_key === to)),
      );
      mutate();
    },
    [mutate],
  );

  const setEdgeCondition = useCallback(
    (from: string, to: string, condition: EdgeCondition) => {
      setEdges((current) =>
        current.map((edge) =>
          edge.from_node_key === from && edge.to_node_key === to ? { ...edge, condition } : edge,
        ),
      );
      mutate();
    },
    [mutate],
  );

  const tidy = useCallback(() => {
    const layout = tidyLayout(executionOrder, nodes.map((node) => node.node_key));
    setNodes((current) =>
      current.map((node) => {
        const point = layout[node.node_key];
        return point ? { ...node, position_x: point.x, position_y: point.y } : node;
      }),
    );
    mutate();
  }, [executionOrder, nodes, mutate]);

  // ------------------------------------------------------------------- saving

  const save = useCallback(async () => {
    setSaving(true);
    try {
      const updated = await apiFetch<WorkflowDetail>(
        `/projects/${projectId}/workflows/${workflow.id}`,
        { method: "PATCH", body: JSON.stringify({ nodes, edges }) },
      );
      setValidation(updated.validation);
      setExecutionOrder(updated.execution_order);
      setDirty(false);
      toast.success("Workflow saved");
    } catch (caught) {
      toast.error("Could not save", extractErrorMessage(caught));
    } finally {
      setSaving(false);
    }
  }, [projectId, workflow.id, nodes, edges, toast]);

  // Warn before losing unsaved graph edits.
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  // -------------------------------------------------------------------- runs

  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const watchRun = useCallback(
    async (runId: string) => {
      try {
        const detail = await apiFetch<WorkflowRunDetail>(
          `/projects/${projectId}/workflow-runs/${runId}`,
        );
        setActiveRun(detail);

        // Keep polling only while the run can still change.
        if (detail.status === "queued" || detail.status === "running") {
          pollRef.current = setTimeout(() => watchRun(runId), POLL_MS);
        } else {
          const tone =
            detail.status === "succeeded"
              ? "success"
              : detail.status === "failed"
                ? "error"
                : "info";
          const summary = `${detail.nodes_succeeded} succeeded · ${detail.nodes_failed} failed · ${detail.nodes_skipped} skipped`;
          if (tone === "success") toast.success("Run finished", summary);
          else if (tone === "error") toast.error("Run failed", summary);
          else toast.info("Run finished", summary);
          void loadRuns();
        }
      } catch (caught) {
        toast.error("Lost track of the run", extractErrorMessage(caught));
      }
    },
    // loadRuns is defined below and stable enough for this callback.
    [projectId, toast],
  );

  const loadRuns = useCallback(async () => {
    try {
      const response = await apiFetch<{ items: WorkflowRunRecord[] }>(
        `/projects/${projectId}/workflow-runs?workflow_id=${workflow.id}&limit=20`,
      );
      setRuns(response.items);
    } catch {
      /* history is supplementary; a failure here should not disrupt editing */
    }
  }, [projectId, workflow.id]);

  useEffect(() => {
    void loadRuns();
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [loadRuns]);

  const runNow = useCallback(async () => {
    if (dirty) {
      toast.info("Save first", "Run uses the saved workflow, not unsaved edits.");
      return;
    }
    try {
      const run = await apiFetch<WorkflowRunRecord>(
        `/projects/${projectId}/workflows/${workflow.id}/run`,
        { method: "POST", body: JSON.stringify({ parameters: {} }) },
      );
      toast.info("Run queued", "A worker will pick it up shortly.");
      setActiveRun({ ...run, node_runs: [], timeline: null });
      void watchRun(run.id);
    } catch (caught) {
      toast.error("Could not start the run", extractErrorMessage(caught));
    }
  }, [dirty, projectId, workflow.id, toast, watchRun]);

  /**
   * Stop a run before a worker picks it up.
   *
   * Only while it is queued. The API refuses anything else -- "Only queued
   * runs can be cancelled; this one is 'running'" -- because a run already
   * executing is executing inside a worker that this request cannot reach.
   * The button is hidden rather than disabled once that moment passes, and
   * the refusal is still surfaced for the case where the worker claims the
   * run between the render and the click.
   */
  const cancelRun = useCallback(async () => {
    if (!activeRun) return;
    try {
      const cancelled = await apiFetch<WorkflowRunRecord>(
        `/projects/${projectId}/workflow-runs/${activeRun.id}/cancel`,
        { method: "POST" },
      );
      if (pollRef.current) clearTimeout(pollRef.current);
      setActiveRun((current) =>
        current ? { ...current, status: cancelled.status } : current,
      );
      toast.info("Run cancelled", "It was still queued, so nothing had started.");
      void loadRuns();
    } catch (caught) {
      // Most likely a worker claimed it first, which the message says plainly.
      toast.error("Could not cancel the run", extractErrorMessage(caught));
      void watchRun(activeRun.id);
    }
  }, [activeRun, projectId, toast, loadRuns, watchRun]);

  // ------------------------------------------------------------------ ribbon

  const ribbon = useMemo<RibbonGroup[]>(
    () => [
      {
        id: "workflow",
        label: "Workflow",
        actions: [
          {
            id: "save",
            label: dirty ? "Save*" : "Save",
            icon: "check",
            prominent: dirty,
            disabled: saving,
            onClick: save,
          },
          {
            id: "run",
            label: "Run now",
            icon: "play",
            disabled: !validation.valid || nodes.length === 0,
            onClick: runNow,
          },
          // Only while a worker could still be stopped from starting: the API
          // refuses to cancel a run that is already executing, so offering it
          // then would be a button whose only outcome is an error. Spread
          // rather than a `hidden` flag, which `RibbonAction` does not have.
          ...(activeRun?.status === "queued"
            ? [
                {
                  id: "cancel",
                  label: "Cancel run",
                  icon: "close" as const,
                  onClick: cancelRun,
                },
              ]
            : []),
          {
            id: "backfill",
            label: "Backfill",
            icon: "refresh",
            disabled: !validation.valid || nodes.length === 0,
            onClick: () => setShowBackfill(true),
          },
          { id: "tidy", label: "Tidy up", icon: "grid", disabled: nodes.length === 0, onClick: tidy },
          {
            id: "history",
            label: "Runs",
            icon: "clock",
            onClick: () => setShowRuns((open) => !open),
          },
          {
            id: "versions",
            label: "Versions",
            icon: "book",
            onClick: () => setShowHistory((open) => !open),
          },
        ],
      },
      {
        id: "steps",
        label: "Add a step",
        actions: NODE_ORDER.map((type) => ({
          id: type,
          label: NODE_META[type].label,
          icon: NODE_META[type].icon,
          onClick: () => addNode(type),
        })),
      },
    ],
    [dirty, saving, save, runNow, tidy, validation.valid, nodes.length, addNode],
  );

  const scheduleLabel =
    workflow.trigger_type === "cron"
      ? `${workflow.cron_expression} (${workflow.timezone || "UTC"})`
      : "Manual";

  return (
    <AppFrame
      currentUser={currentUser}
      crumbs={[
        { label: "Projects", href: "/projects" },
        { label: projectName, href: `/projects/${projectId}` },
        { label: "Workflows", href: `/projects/${projectId}/workflows` },
        { label: workflow.name },
      ]}
      ribbon={ribbon}
      disableWelcomeTour
      statusItems={[
        { id: "steps", label: "Steps", value: String(nodes.length) },
        { id: "links", label: "Links", value: String(edges.length) },
        { id: "schedule", label: "Trigger", value: scheduleLabel },
        {
          id: "next",
          label: "Next run",
          value: workflow.next_run_at ? formatDate(workflow.next_run_at) : "—",
        },
        {
          id: "state",
          label: "Graph",
          value: validation.valid ? "valid" : "has errors",
          tone: validation.valid ? "good" : "bad",
        },
      ]}
      health={
        activeRun
          ? {
              label: `Run ${activeRun.status}`,
              healthy: activeRun.status !== "failed",
            }
          : undefined
      }
      inspector={{
        title: selected ? "Step settings" : "Workflow",
        content: selected ? (
          <NodeInspector
            node={selected}
            edges={edges}
            allNodes={nodes}
            options={options}
            onChange={updateNode}
            onDelete={() => deleteNode(selected.node_key)}
            onChangeEdgeCondition={setEdgeCondition}
          />
        ) : (
          <WorkflowSummaryPanel
            workflow={workflow}
            validation={validation}
            executionOrder={executionOrder}
            activeRun={activeRun}
          />
        ),
      }}
    >
      <div className="flex h-full min-h-0 flex-col">
        {!validation.valid ? (
          <div className="flex items-start gap-2.5 border-b border-danger-line bg-danger-soft px-4 py-2.5 text-[12.5px] text-danger">
            <Icon name="warning" size={14} className="mt-0.5 shrink-0" />
            <div>
              {validation.errors.map((issue) => (
                <div key={issue.code + (issue.node_key ?? "")}>{issue.message}</div>
              ))}
            </div>
          </div>
        ) : null}

        <div className="relative min-h-0 flex-1">
          <WorkflowCanvas
            nodes={nodes}
            edges={edges}
            selectedKey={selectedKey}
            nodeRuns={nodeRuns}
            onSelect={setSelectedKey}
            onMoveNode={moveNode}
            onConnect={connect}
            onDeleteEdge={deleteEdge}
          />

          {showBackfill ? (
            <BackfillDialog
              projectId={projectId}
              workflowId={workflow.id}
              onClose={() => setShowBackfill(false)}
              onQueued={() => void loadRuns()}
            />
          ) : null}

          {showRuns ? (
            <RunHistory
              runs={runs}
              activeRunId={activeRun?.id ?? null}
              canCompare={activeRun !== null}
              onClose={() => setShowRuns(false)}
              onOpen={(runId) => {
                void watchRun(runId);
                setShowRuns(false);
              }}
              onCompare={(runId) => {
                setCompareRunId(runId);
                setShowRuns(false);
              }}
            />
          ) : null}

          {showHistory ? (
            <VersionHistoryPanel
              projectId={projectId}
              workflowId={workflow.id}
              onClose={() => setShowHistory(false)}
              onRestored={() => window.location.reload()}
            />
          ) : null}

          {compareRunId && activeRun ? (
            <RunDiffPanel
              projectId={projectId}
              leftRunId={compareRunId}
              rightRunId={activeRun.id}
              onClose={() => setCompareRunId(null)}
            />
          ) : null}
        </div>
      </div>
    </AppFrame>
  );
}

function WorkflowSummaryPanel({
  workflow,
  validation,
  executionOrder,
  activeRun,
}: {
  workflow: WorkflowDetail;
  validation: WorkflowDetail["validation"];
  executionOrder: string[][];
  activeRun: WorkflowRunDetail | null;
}) {
  return (
    <div className="space-y-4">
      <div>
        <div className="text-[13px] font-medium text-ink">{workflow.name}</div>
        {workflow.description ? (
          <p className="mt-1 text-[12px] leading-5 text-ink-3">{workflow.description}</p>
        ) : null}
      </div>

      {activeRun ? (
        <div className="rounded-lg border border-line bg-surface p-3">
          <div className="mb-2 text-[11px] uppercase tracking-[0.16em] text-muted">
            Current run
          </div>
          <div className="text-[13px] text-ink">{activeRun.status}</div>
          <div className="mt-1 text-[11px] text-muted">
            {activeRun.nodes_succeeded} succeeded · {activeRun.nodes_failed} failed ·{" "}
            {activeRun.nodes_skipped} skipped
          </div>
          {activeRun.error_message ? (
            <p className="mt-2 text-[11px] text-danger">{activeRun.error_message}</p>
          ) : null}
          {activeRun.timeline && activeRun.timeline.entries.length > 0 ? (
            <div className="mt-3 border-t border-line pt-3">
              <RunTimelineView timeline={activeRun.timeline} />
            </div>
          ) : null}
        </div>
      ) : null}

      {executionOrder.length > 0 ? (
        <div>
          <div className="mb-1.5 text-[11px] uppercase tracking-[0.16em] text-muted">
            Execution order
          </div>
          <ol className="space-y-1">
            {executionOrder.map((level, index) => (
              <li key={index} className="flex gap-2 rounded-md bg-surface px-2 py-1.5">
                <span className="shrink-0 font-mono text-[10px] text-muted">{index + 1}</span>
                <span className="min-w-0 flex-1 text-[12px] text-ink-2">
                  {level.join(", ")}
                  {level.length > 1 ? (
                    <span className="ml-1 text-[10px] text-muted">(in parallel)</span>
                  ) : null}
                </span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {validation.warnings.length > 0 ? (
        <div className="rounded-lg border border-warning-line bg-warning-soft p-2.5">
          {validation.warnings.map((issue) => (
            <div key={issue.code + (issue.node_key ?? "")} className="text-[11px] text-warning">
              {issue.message}
            </div>
          ))}
        </div>
      ) : null}

      <p className="text-[11px] leading-5 text-muted">
        Drag a step to move it. Drag from the dot on its right edge onto another step to make that
        step run after it. Click a link to remove it.
      </p>
    </div>
  );
}

function RunHistory({
  runs,
  activeRunId,
  canCompare,
  onClose,
  onOpen,
  onCompare,
}: {
  runs: WorkflowRunRecord[];
  activeRunId: string | null;
  canCompare: boolean;
  onClose: () => void;
  onOpen: (runId: string) => void;
  onCompare: (runId: string) => void;
}) {
  const tone = (status: string) =>
    status === "succeeded"
      ? "text-success"
      : status === "failed"
        ? "text-danger"
        : status === "partial"
          ? "text-warning"
          : "text-ink-3";

  return (
    <aside className="animate-fade-up absolute bottom-4 right-4 top-4 z-20 flex w-[300px] flex-col overflow-hidden rounded-xl border border-line bg-[color:var(--panel-strong)] shadow-[var(--shadow-lg)] backdrop-blur-xl">
      <div className="flex items-center justify-between border-b border-line px-3 py-2.5">
        <span className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted">
          Run history
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close run history"
          className="rounded p-1 text-muted transition hover:bg-surface-2 hover:text-ink"
        >
          <Icon name="close" size={13} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-1.5">
        {runs.length === 0 ? (
          <p className="px-2 py-8 text-center text-[12px] text-muted">No runs yet.</p>
        ) : (
          runs.map((run) => (
            <div
              key={run.id}
              className={cx(
                "group relative rounded-lg transition hover:bg-surface-2",
                run.id === activeRunId && "bg-[color:var(--accent-faint)]",
              )}
            >
              <button
                type="button"
                onClick={() => onOpen(run.id)}
                className="flex w-full flex-col gap-0.5 px-2.5 py-2 text-left"
              >
                <span className="flex items-center justify-between gap-2">
                  <span className={cx("text-[12px] font-medium", tone(run.status))}>
                    {run.status}
                  </span>
                  <span className="text-[10px] uppercase tracking-[0.14em] text-muted">
                    {run.trigger}
                  </span>
                </span>
                <span className="text-[11px] text-muted">
                  {run.logical_date
                    ? `slot ${run.logical_date.slice(0, 10)}`
                    : formatDate(run.queued_at)}
                </span>
                <span className="tabular text-[10px] text-muted">
                  {run.nodes_succeeded}✓ {run.nodes_failed}✗ {run.nodes_skipped}⤳
                </span>
              </button>
              {canCompare && run.id !== activeRunId ? (
                <button
                  type="button"
                  onClick={() => onCompare(run.id)}
                  title="Compare this run against the one open now"
                  className="absolute bottom-1.5 right-2 rounded border border-line px-1.5 py-0.5 text-[10px] text-muted opacity-0 transition group-hover:opacity-100 hover:text-ink"
                >
                  compare
                </button>
              ) : null}
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
