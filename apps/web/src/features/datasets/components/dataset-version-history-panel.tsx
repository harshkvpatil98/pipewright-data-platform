"use client";

import { useCallback, useEffect, useState } from "react";

import type { DatasetVersionListResponse } from "@platform/shared-types";
import { SectionPanel } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate, formatNumber } from "@/lib/format";
import { cx } from "@/lib/utils";

type DatasetVersionHistoryPanelProps = {
  projectId: string;
  datasetId: string;
};

/**
 * The recorded snapshot history of a dataset (Phase 18, time travel).
 *
 * Every materialisation appends an immutable version; this reads them newest
 * first and marks the head. It shows what changed and when -- rows, columns, a
 * short content fingerprint -- but never the storage key, which is not part of
 * the API by design.
 */
export function DatasetVersionHistoryPanel({
  projectId,
  datasetId,
}: DatasetVersionHistoryPanelProps) {
  const [history, setHistory] = useState<DatasetVersionListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setHistory(
        await apiFetch<DatasetVersionListResponse>(
          `/projects/${projectId}/datasets/${datasetId}/versions`,
        ),
      );
    } catch (caught) {
      setError(extractErrorMessage(caught));
    }
  }, [projectId, datasetId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <SectionPanel
      title="Version history"
      description="Every materialisation appends an immutable snapshot. The newest is the current data; older versions stay readable, and rolling back will append a new version rather than rewrite the past."
    >
      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : history === null ? (
        <p className="text-[12.5px] text-muted">Loading history…</p>
      ) : history.items.length === 0 ? (
        <p className="text-[12.5px] text-muted">
          No recorded versions yet. A dataset materialised before versioning shows its history
          from its next run onward.
        </p>
      ) : (
        <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-line text-left text-sm">
              <thead className="bg-surface text-ink-3">
                <tr>
                  <th className="cell-pad font-medium">Version</th>
                  <th className="cell-pad font-medium">Published</th>
                  <th className="cell-pad font-medium">Rows</th>
                  <th className="cell-pad font-medium">Columns</th>
                  <th className="cell-pad font-medium">Fingerprint</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {history.items.map((version) => {
                  const isHead = version.version_number === history.current_version;
                  return (
                    <tr key={version.id} className="transition hover:bg-surface">
                      <td className="cell-pad align-top text-ink">
                        <span className="inline-flex items-center gap-1.5">
                          v{version.version_number}
                          {isHead ? (
                            <span
                              className={cx(
                                "rounded-full border border-success-line bg-success-soft",
                                "px-1.5 py-0.5 text-[10px] text-success",
                              )}
                            >
                              current
                            </span>
                          ) : null}
                        </span>
                      </td>
                      <td className="cell-pad align-top text-ink-2">
                        {formatDate(version.created_at)}
                      </td>
                      <td className="cell-pad align-top text-ink-2">
                        {version.row_count === null ? "--" : formatNumber(version.row_count)}
                      </td>
                      <td className="cell-pad align-top text-ink-2">
                        {version.column_count === null
                          ? "--"
                          : formatNumber(version.column_count)}
                      </td>
                      <td className="cell-pad align-top font-mono text-[11px] text-muted">
                        {shortDigest(version.content_hash)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </SectionPanel>
  );
}

/** A content hash is long; the first few hex characters are enough to eyeball
 * whether two versions hold the same data. */
function shortDigest(hash: string | null): string {
  if (!hash) return "--";
  const hex = hash.includes(":") ? hash.split(":")[1] : hash;
  return hex.slice(0, 12);
}
