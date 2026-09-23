"use client";

import { useCallback, useEffect, useState } from "react";

import type {
  DatasetPreview,
  DatasetTemporalQueryRequest,
  DatasetTemporalQueryResponse,
  DatasetVersion,
  DatasetVersionDiff,
  DatasetVersionDiffRequest,
  DatasetVersionListResponse,
} from "@platform/shared-types";
import { Button, SectionPanel } from "@platform/shared-ui";

import { Modal } from "@/components/ui/modal";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDateTime, formatDurationMs, formatNumber } from "@/lib/format";
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

  // The version being previewed in the modal, its data, and load state.
  const [viewing, setViewing] = useState<DatasetVersion | null>(null);
  const [preview, setPreview] = useState<DatasetPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

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

  const openVersion = useCallback(
    async (version: DatasetVersion) => {
      setViewing(version);
      setPreview(null);
      setPreviewError(null);
      try {
        setPreview(
          await apiFetch<DatasetPreview>(
            `/projects/${projectId}/datasets/${datasetId}/versions/${version.version_number}/preview`,
          ),
        );
      } catch (caught) {
        setPreviewError(extractErrorMessage(caught));
      }
    },
    [projectId, datasetId],
  );

  // Diff modal state: the version being compared against the head.
  const [diffing, setDiffing] = useState<DatasetVersion | null>(null);
  const [diff, setDiff] = useState<DatasetVersionDiff | null>(null);
  const [diffError, setDiffError] = useState<string | null>(null);
  const [identityText, setIdentityText] = useState("");

  const runDiff = useCallback(
    async (version: DatasetVersion, identity: string) => {
      if (!history?.current_version) return;
      setDiff(null);
      setDiffError(null);
      try {
        const payload: DatasetVersionDiffRequest = {
          from_version: version.version_number,
          to_version: history.current_version,
          identity_columns: identity
            .split(",")
            .map((column) => column.trim())
            .filter(Boolean),
        };
        setDiff(
          await apiFetch<DatasetVersionDiff>(
            `/projects/${projectId}/datasets/${datasetId}/versions/diff`,
            { method: "POST", body: JSON.stringify(payload) },
          ),
        );
      } catch (caught) {
        setDiffError(extractErrorMessage(caught));
      }
    },
    [projectId, datasetId, history],
  );

  const openDiff = useCallback(
    (version: DatasetVersion) => {
      setDiffing(version);
      setIdentityText("");
      void runDiff(version, "");
    },
    [runDiff],
  );

  // Restore (rollback): appends a new version with the target's data.
  const [restoring, setRestoring] = useState<DatasetVersion | null>(null);
  const [restoreBusy, setRestoreBusy] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);

  const restore = useCallback(async () => {
    if (!restoring) return;
    setRestoreBusy(true);
    setRestoreError(null);
    try {
      await apiFetch<DatasetVersion>(
        `/projects/${projectId}/datasets/${datasetId}/versions/${restoring.version_number}/rollback`,
        { method: "POST" },
      );
      setRestoring(null);
      await load();
    } catch (caught) {
      setRestoreError(extractErrorMessage(caught));
    } finally {
      setRestoreBusy(false);
    }
  }, [restoring, projectId, datasetId, load]);

  // Temporal SQL: query the data as of a version or an instant.
  const [queryTarget, setQueryTarget] = useState<
    { version_number: number } | { as_of: string } | null
  >(null);
  const [sql, setSql] = useState(DEFAULT_SQL);
  const [queryResult, setQueryResult] = useState<DatasetTemporalQueryResponse | null>(null);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [queryBusy, setQueryBusy] = useState(false);
  const [asOfInput, setAsOfInput] = useState("");

  const runQuery = useCallback(
    async (target: { version_number: number } | { as_of: string }, statement: string) => {
      setQueryBusy(true);
      setQueryError(null);
      try {
        const payload: DatasetTemporalQueryRequest = { sql: statement, row_limit: 200, ...target };
        setQueryResult(
          await apiFetch<DatasetTemporalQueryResponse>(
            `/projects/${projectId}/datasets/${datasetId}/versions/query`,
            { method: "POST", body: JSON.stringify(payload) },
          ),
        );
      } catch (caught) {
        setQueryResult(null);
        setQueryError(extractErrorMessage(caught));
      } finally {
        setQueryBusy(false);
      }
    },
    [projectId, datasetId],
  );

  const openQuery = useCallback(
    (target: { version_number: number } | { as_of: string }) => {
      setQueryTarget(target);
      setQueryResult(null);
      setQueryError(null);
      setSql(DEFAULT_SQL);
      void runQuery(target, DEFAULT_SQL);
    },
    [runQuery],
  );

  return (
    <SectionPanel
      title="Version history"
      description="Every materialisation appends an immutable snapshot. The newest is the current data; older versions stay readable, and rolling back will append a new version rather than rewrite the past."
      actions={
        history && history.items.length > 0 ? (
          <form
            className="flex flex-wrap items-center gap-1.5"
            onSubmit={(event) => {
              event.preventDefault();
              if (!asOfInput) return;
              openQuery({ as_of: new Date(asOfInput).toISOString() });
            }}
          >
            <label className="text-[11px] text-muted" htmlFor="version-as-of">
              Query as of
            </label>
            <input
              id="version-as-of"
              type="datetime-local"
              value={asOfInput}
              onChange={(event) => setAsOfInput(event.target.value)}
              className="h-8 rounded-lg border border-line bg-sunken px-2 text-[12px] text-ink outline-none transition focus:border-[color:var(--accent)]"
            />
            <Button type="submit" variant="secondary" size="sm" disabled={!asOfInput}>
              Query
            </Button>
          </form>
        ) : null
      }
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
                  <th className="cell-pad font-medium sr-only">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {history.items.map((version) => {
                  const isHead = version.version_number === history.current_version;
                  const pruned = version.retention_state === "pruned";
                  const scheduled = version.retention_state === "pending_delete";
                  return (
                    <tr key={version.id} className="transition hover:bg-surface">
                      <td className="cell-pad align-top text-ink">
                        <span className="inline-flex flex-wrap items-center gap-1.5">
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
                          {pruned ? (
                            <span
                              className="rounded-full border border-line bg-sunken px-1.5 py-0.5 text-[10px] text-muted"
                              title={
                                version.pruned_at
                                  ? `Data removed by retention on ${formatDateTime(version.pruned_at)}; the record is kept.`
                                  : "Data removed by retention; the record is kept."
                              }
                            >
                              pruned
                            </span>
                          ) : null}
                          {scheduled ? (
                            <span
                              className="rounded-full border border-warning-line bg-warning-soft px-1.5 py-0.5 text-[10px] text-warning"
                              title={
                                version.delete_after
                                  ? `Marked by a retention sweep; removable after ${formatDateTime(version.delete_after)} unless restored or replayed first.`
                                  : "Marked by a retention sweep for removal after its grace period."
                              }
                            >
                              scheduled for removal
                            </span>
                          ) : null}
                          {version.active_pins > 0 ? (
                            <span
                              className="rounded-full border border-line bg-sunken px-1.5 py-0.5 text-[10px] text-ink-3"
                              title="A rollback or replay is reading this version right now; it cannot be pruned while held."
                            >
                              held open
                            </span>
                          ) : null}
                        </span>
                      </td>
                      <td className="cell-pad align-top text-ink-2">
                        {formatDateTime(version.created_at)}
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
                      <td className="cell-pad align-top text-right">
                        {pruned ? (
                          <span className="text-[11px] text-muted">data removed</span>
                        ) : (
                        <div className="flex flex-wrap justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => void openVersion(version)}
                            className="rounded-lg border border-line px-2 py-1 text-[11.5px] text-ink-3 transition hover:text-ink"
                          >
                            View data
                          </button>
                          <button
                            type="button"
                            onClick={() => openQuery({ version_number: version.version_number })}
                            className="rounded-lg border border-line px-2 py-1 text-[11.5px] text-ink-3 transition hover:text-ink"
                          >
                            Query
                          </button>
                          {!isHead ? (
                            <>
                              <button
                                type="button"
                                onClick={() => openDiff(version)}
                                className="rounded-lg border border-line px-2 py-1 text-[11.5px] text-ink-3 transition hover:text-ink"
                              >
                                Diff vs current
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  setRestoreError(null);
                                  setRestoring(version);
                                }}
                                className="rounded-lg border border-line px-2 py-1 text-[11.5px] text-ink-3 transition hover:text-ink"
                              >
                                Restore
                              </button>
                            </>
                          ) : null}
                        </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Modal
        open={viewing !== null}
        title={viewing ? `Version ${viewing.version_number}` : "Version"}
        description="The data as it was published in this version — a snapshot, not the current head."
        onClose={() => setViewing(null)}
        widthClassName="max-w-4xl"
        footer={
          <Button variant="secondary" size="sm" onClick={() => setViewing(null)}>
            Close
          </Button>
        }
      >
        {previewError ? (
          <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
            {previewError}
          </div>
        ) : preview === null ? (
          <p className="text-[12.5px] text-muted">Loading preview…</p>
        ) : preview.columns.length === 0 ? (
          <p className="text-[12.5px] text-muted">
            No preview was captured for this version.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-2xl border border-line">
            <table className="min-w-full divide-y divide-line text-left text-[12.5px]">
              <thead className="bg-surface text-ink-3">
                <tr>
                  {preview.columns.map((column) => (
                    <th key={column} className="cell-pad font-medium">
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {preview.rows.slice(0, 50).map((row, index) => (
                  <tr key={index} className="transition hover:bg-surface">
                    {preview.columns.map((column) => (
                      <td key={column} className="cell-pad align-top text-ink-2">
                        {formatCell(row[column])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Modal>

      <Modal
        open={diffing !== null}
        title={
          diffing
            ? `v${diffing.version_number} → v${history?.current_version ?? "?"}`
            : "Diff"
        }
        description="What changed between this version and the current data. Supplying identity columns lets rows be matched; without them the diff reports duplicate-aware added/removed counts and says why."
        onClose={() => setDiffing(null)}
        widthClassName="max-w-3xl"
        footer={
          <Button variant="secondary" size="sm" onClick={() => setDiffing(null)}>
            Close
          </Button>
        }
      >
        <div className="mb-3 flex flex-wrap items-end gap-2">
          <label className="flex-1 space-y-1">
            <span className="text-[11px] text-muted">
              Identity columns (comma-separated, optional)
            </span>
            <input
              value={identityText}
              onChange={(event) => setIdentityText(event.target.value)}
              placeholder="id"
              className="h-9 w-full rounded-lg border border-line bg-sunken px-3 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)]"
            />
          </label>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => diffing && void runDiff(diffing, identityText)}
          >
            Recompute
          </Button>
        </div>
        {diffError ? (
          <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
            {diffError}
          </div>
        ) : diff === null ? (
          <p className="text-[12.5px] text-muted">Comparing…</p>
        ) : diff.identical ? (
          <p className="text-[12.5px] text-success">
            The two versions hold identical data — answered from the content digests.
          </p>
        ) : (
          <div className="space-y-3">
            <div className="grid gap-2 sm:grid-cols-3">
              <DiffStat label="Added" value={diff.rows_added} />
              <DiffStat label="Removed" value={diff.rows_removed} />
              <DiffStat
                label="Changed"
                value={diff.changed_available ? diff.rows_changed : null}
                note={diff.changed_available ? undefined : "needs identity"}
              />
            </div>
            {diff.columns_added.length > 0 || diff.columns_removed.length > 0 ? (
              <p className="text-[12px] text-ink-3">
                Schema: {diff.columns_added.length > 0 ? `+${diff.columns_added.join(", +")}` : null}
                {diff.columns_added.length > 0 && diff.columns_removed.length > 0 ? " · " : null}
                {diff.columns_removed.length > 0 ? `−${diff.columns_removed.join(", −")}` : null}
              </p>
            ) : null}
            {diff.reason ? (
              <p className="text-[11.5px] text-muted">{diff.reason}</p>
            ) : null}
            {Object.keys(diff.cells_changed_by_column).length > 0 ? (
              <p className="text-[12px] text-ink-3">
                Cells changed:{" "}
                {Object.entries(diff.cells_changed_by_column)
                  .map(([column, count]) => `${column} (${count})`)
                  .join(", ")}
              </p>
            ) : null}
            <p className="text-[10.5px] text-muted">
              {diff.method}. Samples capped at {diff.sample_limit}; counts are exact.
            </p>
          </div>
        )}
      </Modal>

      <Modal
        open={queryTarget !== null}
        title={
          queryTarget && "version_number" in queryTarget
            ? `Query version ${queryTarget.version_number}`
            : "Query as of a time"
        }
        description="SQL runs against a private copy of the snapshot, exposed as a table named dataset. Only a SELECT can run; nothing is written, and the current data is untouched."
        onClose={() => setQueryTarget(null)}
        widthClassName="max-w-4xl"
        footer={
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setQueryTarget(null)}>
              Close
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={queryBusy || !sql.trim()}
              onClick={() => queryTarget && void runQuery(queryTarget, sql)}
            >
              {queryBusy ? "Running…" : "Run"}
            </Button>
          </div>
        }
      >
        <label className="block space-y-1">
          <span className="text-[11px] text-muted">SQL (Ctrl/⌘ + Enter to run)</span>
          <textarea
            value={sql}
            onChange={(event) => setSql(event.target.value)}
            onKeyDown={(event) => {
              if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && queryTarget) {
                event.preventDefault();
                void runQuery(queryTarget, sql);
              }
            }}
            rows={3}
            spellCheck={false}
            className="w-full rounded-lg border border-line bg-sunken px-3 py-2 font-mono text-[12.5px] text-ink outline-none transition focus:border-[color:var(--accent)]"
          />
        </label>
        <div className="mt-3">
          {queryError ? (
            <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
              {queryError}
            </div>
          ) : queryResult === null ? (
            <p className="text-[12.5px] text-muted">{queryBusy ? "Running…" : "No result yet."}</p>
          ) : (
            <div className="space-y-2">
              <p className="text-[12px] text-ink-3">
                Resolved to <span className="text-ink">version {queryResult.version_number}</span>, published{" "}
                {formatDateTime(queryResult.version_published_at)}
                {queryResult.requested_as_of
                  ? ` (the newest at ${formatDateTime(queryResult.requested_as_of)})`
                  : null}
                {" · "}
                {queryResult.row_count.toLocaleString()} row{queryResult.row_count === 1 ? "" : "s"}
                {queryResult.truncated ? ` (capped at ${queryResult.row_limit})` : null}
                {" · "}
                {formatDurationMs(queryResult.duration_ms)}
              </p>
              {queryResult.columns.length === 0 ? (
                <p className="text-[12.5px] text-muted">The statement returned no columns.</p>
              ) : (
                <div className="max-h-[50vh] overflow-auto rounded-2xl border border-line">
                  <table className="min-w-full divide-y divide-line text-left text-[12.5px]">
                    <thead className="bg-surface text-ink-3">
                      <tr>
                        {queryResult.columns.map((column) => (
                          <th key={column} className="cell-pad font-medium">
                            {column}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {queryResult.rows.map((row, index) => (
                        <tr key={index} className="transition hover:bg-surface">
                          {queryResult.columns.map((column) => (
                            <td key={column} className="cell-pad align-top text-ink-2">
                              {formatCell(row[column])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </Modal>

      <Modal
        open={restoring !== null}
        title={restoring ? `Restore version ${restoring.version_number}` : "Restore"}
        description="Restoring appends a new version whose data is this snapshot's. Nothing is rewritten or lost — the versions after it stay in the history."
        onClose={() => setRestoring(null)}
        footer={
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setRestoring(null)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => void restore()}
              disabled={restoreBusy}
            >
              {restoreBusy ? "Restoring…" : "Restore this version"}
            </Button>
          </div>
        }
      >
        {restoreError ? (
          <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
            {restoreError}
          </div>
        ) : (
          <p className="text-[12.5px] text-ink-2">
            The current data will become version {history ? (history.current_version ?? 0) + 1 : "…"},
            holding exactly what version {restoring?.version_number} holds. The restored
            version's fingerprint will match this one's, so the copy can be verified.
          </p>
        )}
      </Modal>
    </SectionPanel>
  );
}

const DEFAULT_SQL = "SELECT * FROM dataset LIMIT 100";

function DiffStat({
  label,
  value,
  note,
}: {
  label: string;
  value: number | null;
  note?: string;
}) {
  return (
    <div className="rounded-xl border border-line bg-sunken px-3 py-2.5">
      <div className="text-[11px] uppercase tracking-[0.14em] text-muted">{label}</div>
      <div className="mt-0.5 text-xl font-semibold text-ink">
        {value === null ? "—" : value.toLocaleString()}
      </div>
      {note ? <div className="text-[10.5px] text-muted">{note}</div> : null}
    </div>
  );
}

/** A content hash is long; the first few hex characters are enough to eyeball
 * whether two versions hold the same data. */
function shortDigest(hash: string | null): string {
  if (!hash) return "--";
  const hex = hash.includes(":") ? hash.split(":")[1] : hash;
  return hex.slice(0, 12);
}

/** Render a preview cell as text; a null is shown as the word, not a blank that
 * an empty string would also produce. */
function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
