"use client";

import { useCallback, useEffect, useState } from "react";

import type { NodeDiff, RunDiff } from "@platform/shared-types";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";
import { Badge, type BadgeTone, Icon } from "@platform/shared-ui";

type RunDiffPanelProps = {
  projectId: string;
  leftRunId: string;
  rightRunId: string;
  onClose: () => void;
};

const VERDICT_TONE: Record<NodeDiff["verdict"], BadgeTone> = {
  same: "neutral",
  slower: "warning",
  faster: "success",
  status_changed: "danger",
  output_changed: "accent",
  added: "info",
  removed: "neutral",
};

const VERDICT_LABEL: Record<NodeDiff["verdict"], string> = {
  same: "unchanged",
  slower: "slower",
  faster: "faster",
  status_changed: "status changed",
  output_changed: "different data",
  added: "new task",
  removed: "removed",
};

/** "It worked yesterday" — answered without opening two tabs. */
export function RunDiffPanel({ projectId, leftRunId, rightRunId, onClose }: RunDiffPanelProps) {
  const [diff, setDiff] = useState<RunDiff | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setDiff(
        await apiFetch<RunDiff>(
          `/projects/${projectId}/workflow-runs/${leftRunId}/diff/${rightRunId}`,
        ),
      );
    } catch (caught) {
      setError(extractErrorMessage(caught));
    }
  }, [projectId, leftRunId, rightRunId]);

  useEffect(() => {
    void load();
  }, [load]);

  const changed = diff?.nodes.filter((node) => node.verdict !== "same") ?? [];

  return (
    <aside className="animate-fade-up absolute bottom-4 left-4 top-4 z-30 flex w-[340px] flex-col overflow-hidden rounded-xl border border-line bg-[color:var(--panel-strong)] shadow-[var(--shadow-lg)] backdrop-blur-xl">
      <div className="flex items-center justify-between border-b border-line px-3 py-2.5">
        <span className="text-[12px] font-medium text-muted">
          Run comparison
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close run comparison"
          className="rounded p-1 text-muted transition hover:bg-surface-2 hover:text-ink"
        >
          <Icon name="close" size={13} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {error ? (
          <div className="rounded-lg border border-danger-line bg-danger-soft px-3 py-2.5 text-[12px] text-danger">
            {error}
          </div>
        ) : !diff ? (
          <p className="py-6 text-center text-[12px] text-muted">Comparing…</p>
        ) : (
          <>
            <p
              className={cx(
                "rounded-lg border px-3 py-2.5 text-[12.5px] leading-5",
                diff.identical
                  ? "border-success-line bg-success-soft text-success"
                  : "border-line bg-surface text-ink",
              )}
            >
              {diff.summary}
            </p>

            <div className="mt-2 flex items-center justify-between text-[12px] text-muted">
              <span>
                older · {diff.left.logical_date?.slice(0, 10) ?? diff.left.queued_at.slice(0, 10)}
              </span>
              <span>
                newer · {diff.right.logical_date?.slice(0, 10) ?? diff.right.queued_at.slice(0, 10)}
              </span>
            </div>

            {changed.length > 0 ? (
              <ul className="mt-3 space-y-2">
                {changed.map((node) => (
                  <li
                    key={node.node_key}
                    className="rounded-lg border border-line bg-surface px-2.5 py-2"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="truncate text-[12px] text-ink">{node.node_name}</span>
                      <Badge tone={VERDICT_TONE[node.verdict]} className="shrink-0">
                        {VERDICT_LABEL[node.verdict]}
                      </Badge>
                    </div>
                    {node.left_status !== node.right_status ? (
                      <div className="mt-1 text-[12px] text-ink-3">
                        {node.left_status ?? "—"} → {node.right_status ?? "—"}
                      </div>
                    ) : null}
                    {node.changes.map((change) => (
                      <div key={change} className="mt-1 text-[12px] text-ink-3">
                        {change}
                      </div>
                    ))}
                    {node.verdict === "slower" || node.verdict === "faster" ? (
                      <div className="mt-1 text-[12px] text-muted">
                        {node.duration_change_percentage !== null
                          ? `${node.duration_change_percentage > 0 ? "+" : ""}${node.duration_change_percentage.toFixed(0)}% duration`
                          : null}
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-[12px] text-muted">
                Every step ran the same way and produced the same numbers.
              </p>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
