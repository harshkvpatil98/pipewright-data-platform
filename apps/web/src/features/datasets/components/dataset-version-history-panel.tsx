"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import type {
  ContractCheck,
  DatasetPreview,
  DatasetTemporalQueryRequest,
  DatasetTemporalQueryResponse,
  DatasetVersion,
  DatasetVersionDiff,
  DatasetVersionDiffRequest,
  DatasetVersionListResponse,
} from "@platform/shared-types";
import {
  Badge,
  Button,
  Modal,
  SectionPanel,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { downloadFromApi } from "@/lib/api/download";
import { extractErrorMessage } from "@/lib/api/errors";
import { countOf, formatDateTime, formatDurationMs, formatNumber } from "@/lib/format";
import { cx } from "@/lib/utils";

type DatasetVersionHistoryPanelProps = {
  projectId: string;
  datasetId: string;
  /** The dataset's contract, so a restore says first whether the version keeps it (C1). */
  contract?: { enforcement: "stop" | "warn" } | null;
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
  contract = null,
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
  const [downloadError, setDownloadError] = useState<string | null>(null);

  // Whether the version to restore keeps the dataset's contract, asked as the
  // dialog opens so the answer is there before anyone confirms.
  const [restoreCheck, setRestoreCheck] = useState<ContractCheck | null>(null);
  useEffect(() => {
    setRestoreCheck(null);
    if (!restoring || !contract) return;
    let cancelled = false;
    apiFetch<ContractCheck>(
      `/projects/${projectId}/datasets/${datasetId}/contract/check?version=${restoring.version_number}`,
    )
      .then((found) => {
        if (!cancelled) setRestoreCheck(found);
      })
      .catch(() => {
        if (!cancelled) setRestoreCheck(null);
      });
    return () => {
      cancelled = true;
    };
  }, [restoring, contract, projectId, datasetId]);
  const restoreRefused = restoreCheck !== null && !restoreCheck.kept && contract?.enforcement === "stop";

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
      description="Every run saves a new version and keeps the old ones. Restoring one adds a newer copy of it."
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
            <label className="text-[12px] text-muted"htmlFor="version-as-of">
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
      {downloadError ? (
        <p role="alert" className="mb-3 rounded-2xl border border-danger-line bg-danger-soft px-4 py-2 text-sm text-danger">
          {downloadError}
        </p>
      ) : null}
      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : history === null ? (
        <p className="text-[12.5px] text-muted">Loading history…</p>
      ) : history.items.length === 0 ? (
        <p className="text-[12.5px] text-muted">
          No versions yet. A dataset made before versions were kept starts its history at its
          next run.
        </p>
      ) : (
        <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
          <Table edge="panel">
            <TableHead>
              <TableRow>
                <TableHeaderCell>Version</TableHeaderCell>
                <TableHeaderCell>Saved</TableHeaderCell>
                <TableHeaderCell>Rows</TableHeaderCell>
                <TableHeaderCell>Columns</TableHeaderCell>
                <TableHeaderCell>Fingerprint</TableHeaderCell>
                <TableHeaderCell className="sr-only">Actions</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {history.items.map((version) => {
                const isHead = version.version_number === history.current_version;
                const pruned = version.retention_state === "pruned";
                const scheduled = version.retention_state === "pending_delete";
                return (
                  <TableRow key={version.id}>
                    <TableCell className="text-ink">
                      <span className="inline-flex flex-wrap items-center gap-1.5">
                        v{version.version_number}
                        {isHead ? (
                          <span
                            className={cx(
                              "rounded-full border border-success-line bg-success-soft",
                              "px-1.5 py-0.5 text-[12px] text-success",
                            )}
                          >
                            current
                          </span>
                        ) : null}
                        {pruned ? (
                          <Badge
                            title={
                              version.pruned_at
                                ? `Data removed by retention on ${formatDateTime(version.pruned_at)}; the record is kept.`
                                : "Data removed by retention; the record is kept."
                            }
                          >
                            Data removed
                          </Badge>
                        ) : null}
                        {scheduled ? (
                          <Badge tone="warning"
                            title={
                              version.delete_after
                                ? `Marked by a retention sweep; removable after ${formatDateTime(version.delete_after)} unless restored or replayed first.`
                                : "Marked by a retention sweep for removal after its grace period."
                            }
                          >
                            Due for removal
                          </Badge>
                        ) : null}
                        {version.active_pins > 0 ? (
                          <Badge
                            title="A restore or replay is reading this version right now, so it cannot be removed yet."
                          >
                            In use
                          </Badge>
                        ) : null}
                      </span>
                    </TableCell>
                    <TableCell className="text-ink-2">
                      {formatDateTime(version.created_at)}
                    </TableCell>
                    <TableCell className="text-ink-2">
                      {version.row_count === null ? "--" : formatNumber(version.row_count)}
                    </TableCell>
                    <TableCell className="text-ink-2">
                      {version.column_count === null
                        ? "--"
                        : formatNumber(version.column_count)}
                    </TableCell>
                    <TableCell className="font-mono text-[12px] text-muted">
                      {shortDigest(version.content_hash)}
                    </TableCell>
                    <TableCell className="text-right">
                      {pruned ? (
                        <span className="text-[12px] text-muted">data removed</span>
                      ) : (
                      <div className="flex flex-wrap justify-end gap-1">
                        <button
                          type="button"
                          onClick={() => void openVersion(version)}
                          className="rounded-lg border border-line px-2 py-1 text-[12px] text-ink-3 transition hover:text-ink"
                        >
                          View data
                        </button>
                        <button
                          type="button"
                          onClick={() => openQuery({ version_number: version.version_number })}
                          className="rounded-lg border border-line px-2 py-1 text-[12px] text-ink-3 transition hover:text-ink"
                        >
                          Query
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            void downloadFromApi(
                              `/projects/${projectId}/datasets/${datasetId}/download?format=csv&version=${version.version_number}`,
                              `version-${version.version_number}.csv`,
                            ).catch((caught) => setDownloadError(extractErrorMessage(caught)))
                          }
                          className="rounded-lg border border-line px-2 py-1 text-[12px] text-ink-3 transition hover:text-ink"
                        >
                          Download
                        </button>
                        {!isHead ? (
                          <>
                            <button
                              type="button"
                              onClick={() => openDiff(version)}
                              className="rounded-lg border border-line px-2 py-1 text-[12px] text-ink-3 transition hover:text-ink"
                            >
                              Diff vs current
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setRestoreError(null);
                                setRestoring(version);
                              }}
                              className="rounded-lg border border-line px-2 py-1 text-[12px] text-ink-3 transition hover:text-ink"
                            >
                              Restore
                            </button>
                          </>
                        ) : null}
                      </div>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      <Modal
        open={viewing !== null}
        title={viewing ? `Version ${viewing.version_number}` : "Version"}
        description="The data as it was in this version, not as it is now."
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
            <Table edge="panel">
              <TableHead>
                <TableRow>
                  {preview.columns.map((column) => (
                    <TableHeaderCell key={column}>
                      {column}
                    </TableHeaderCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {preview.rows.slice(0, 50).map((row, index) => (
                  <TableRow key={index}>
                    {preview.columns.map((column) => (
                      <TableCell key={column} className="text-ink-2">
                        {formatCell(row[column])}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
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
        description="What changed between this version and now. Name the columns that identify a row to match rows up."
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
            <span className="text-[12px] text-muted">
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
            The two versions hold identical data. Their content fingerprints match.
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
              <p className="text-[12px] text-muted">{diff.reason}</p>
            ) : null}
            {Object.keys(diff.cells_changed_by_column).length > 0 ? (
              <p className="text-[12px] text-ink-3">
                Cells changed:{" "}
                {Object.entries(diff.cells_changed_by_column)
                  .map(([column, count]) => `${column} (${count})`)
                  .join(", ")}
              </p>
            ) : null}
            <p className="text-[12px] text-muted">
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
        description="Ask this version a question in SQL; it is the table named dataset. Only reading is allowed, so nothing changes."
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
          <span className="text-[12px] text-muted">SQL (Ctrl/⌘ + Enter to run)</span>
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
                Answered from <span className="text-ink">version {queryResult.version_number}</span>, saved{" "}
                {formatDateTime(queryResult.version_published_at)}
                {queryResult.requested_as_of
                  ? ` (the newest at ${formatDateTime(queryResult.requested_as_of)})`
                  : null}
                {" · "}
                {countOf(queryResult.row_count, "row")}
                {queryResult.truncated ? ` (capped at ${queryResult.row_limit})` : null}
                {" · "}
                {formatDurationMs(queryResult.duration_ms)}
              </p>
              {queryResult.columns.length === 0 ? (
                <p className="text-[12.5px] text-muted">The statement returned no columns.</p>
              ) : (
                <div className="max-h-[50vh] overflow-auto rounded-2xl border border-line">
                  <Table edge="panel">
                    <TableHead>
                      <TableRow>
                        {queryResult.columns.map((column) => (
                          <TableHeaderCell key={column}>
                            {column}
                          </TableHeaderCell>
                        ))}
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {queryResult.rows.map((row, index) => (
                        <TableRow key={index}>
                          {queryResult.columns.map((column) => (
                            <TableCell key={column} className="text-ink-2">
                              {formatCell(row[column])}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>
          )}
        </div>
      </Modal>

      <Modal
        open={restoring !== null}
        title={restoring ? `Restore version ${restoring.version_number}` : "Restore"}
        description="Adds a new version with this version's data. Nothing is lost; later versions stay in the history."
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
              disabled={restoreBusy || restoreRefused}
            >
              {restoreBusy ? "Restoring…" : "Restore this version"}
            </Button>
          </div>
        }
      >
        {restoreCheck && !restoreCheck.kept ? (
          <div className="mb-3 rounded-2xl border border-warning-line bg-warning-soft px-4 py-3 text-sm text-ink-2">
            <p className="font-medium text-warning">Version {restoring?.version_number} breaks this dataset&rsquo;s contract.</p>
            <ul className="mt-1 list-disc pl-5">
              {restoreCheck.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
            <p className="mt-1 text-ink-3">
              {restoreRefused
                ? "The contract stops data that breaks it, so this version cannot be restored. Change the contract, or set it to warn, first."
                : "The contract is set to warn, so restoring it is allowed and the problem is recorded."}{" "}
              <Link href={`/projects/${projectId}/datasets/${datasetId}/contract`} className="underline">
                Open the contract
              </Link>
            </p>
          </div>
        ) : restoreCheck?.kept ? (
          <p className="mb-3 text-[12.5px] text-success">Version {restoring?.version_number} keeps this dataset&rsquo;s contract.</p>
        ) : null}
        {restoreError ? (
          <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
            {restoreError}
          </div>
        ) : restoreRefused ? null : (
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
      <div className="text-[12px] text-muted">{label}</div>
      <div className="mt-0.5 text-xl font-semibold text-ink">
        {value === null ? "—" : formatNumber(value)}
      </div>
      {note ? <div className="text-[12px] text-muted">{note}</div> : null}
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
