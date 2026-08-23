"use client";

import { useCallback, useEffect, useState } from "react";

import type { ResourceVersion, RestoreResponse, VersionListResponse } from "@platform/shared-types";

import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { cx } from "@/lib/utils";

type VersionHistoryPanelProps = {
  projectId: string;
  workflowId: string;
  onClose: () => void;
  onRestored: () => void;
};

/**
 * Every edit, and the ability to undo one.
 *
 * Restoring moves history forward rather than truncating it -- the rollback is
 * itself an edit somebody made, and erasing what it undid would lose the record
 * of what went wrong.
 */
export function VersionHistoryPanel({
  projectId,
  workflowId,
  onClose,
  onRestored,
}: VersionHistoryPanelProps) {
  const [versions, setVersions] = useState<ResourceVersion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const response = await apiFetch<VersionListResponse>(
        `/projects/${projectId}/history/workflow/${workflowId}`,
      );
      setVersions(response.items);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    }
  }, [projectId, workflowId]);

  useEffect(() => {
    void load();
  }, [load]);

  const restore = useCallback(
    async (version: number) => {
      setBusy(version);
      setError(null);
      try {
        const response = await apiFetch<RestoreResponse>(
          `/projects/${projectId}/history/workflow/${workflowId}/restore`,
          { method: "POST", body: JSON.stringify({ version }) },
        );
        setNote(response.summary);
        await load();
        onRestored();
      } catch (caught) {
        setError(extractErrorMessage(caught));
      } finally {
        setBusy(null);
      }
    },
    [projectId, workflowId, load, onRestored],
  );

  return (
    <aside className="animate-fade-up absolute bottom-4 right-4 top-4 z-30 flex w-[320px] flex-col overflow-hidden rounded-xl border border-line bg-[color:var(--panel-strong)] shadow-[var(--shadow-lg)] backdrop-blur-xl">
      <div className="flex items-center justify-between border-b border-line px-3 py-2.5">
        <span className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted">
          Version history
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close version history"
          className="rounded p-1 text-muted transition hover:bg-surface-2 hover:text-ink"
        >
          <Icon name="close" size={13} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {error ? (
          <div className="rounded-lg border border-danger-line bg-danger-soft px-3 py-2 text-[12px] text-danger">
            {error}
          </div>
        ) : null}
        {note ? (
          <div className="mb-2 rounded-lg border border-success-line bg-success-soft px-3 py-2 text-[12px] text-success">
            {note}
          </div>
        ) : null}

        {versions.length === 0 && !error ? (
          <p className="px-2 py-8 text-center text-[12px] text-muted">No history yet.</p>
        ) : null}

        <ol className="space-y-1.5">
          {versions.map((version, index) => (
            <li
              key={version.id}
              className={cx(
                "rounded-lg border px-2.5 py-2",
                index === 0 ? "border-[color:var(--accent)]/40 bg-[color:var(--accent-faint)]" : "border-line",
              )}
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[12px] text-ink">
                  v{version.version}
                  {index === 0 ? <span className="ml-1.5 text-[10px] text-ink-3">current</span> : null}
                </span>
                <span className="text-[10.5px] text-muted">
                  {formatDate(version.created_at)}
                </span>
              </div>
              {version.change_summary ? (
                <p className="mt-0.5 text-[11.5px] leading-4 text-ink-3">
                  {version.change_summary}
                </p>
              ) : null}
              <div className="mt-1 flex items-center justify-between gap-2">
                <span className="text-[10.5px] text-muted">
                  {version.created_by_username ?? "unknown"}
                  {version.restored_from_version
                    ? ` · restored v${version.restored_from_version}`
                    : ""}
                </span>
                {index !== 0 ? (
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void restore(version.version)}
                    className="rounded border border-line px-1.5 py-0.5 text-[10.5px] text-ink-3 transition hover:text-ink disabled:opacity-40"
                  >
                    {busy === version.version ? "Restoring…" : "Restore"}
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      </div>
    </aside>
  );
}
