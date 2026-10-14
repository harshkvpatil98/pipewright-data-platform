"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import type {
  DeliveryMode,
  DeliveryPreview,
  DeliveryRequest,
  DeliveryResult,
  DestinationListResponse,
  DestinationRecord,
} from "@platform/shared-types";
import {
  Button,
  buttonClassName,
  FormField,
  Icon,
  Input,
  Modal,
  Select,
} from "@platform/shared-ui";

import { KIND_BY_TYPE } from "@/features/destinations/destination-kinds";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";
import { countOf, formatCount } from "@/lib/format";

type DeliverDatasetModalProps = {
  open: boolean;
  onClose: () => void;
  projectId: string;
  datasetId: string;
  datasetName: string;
  columns: string[];
};

const TABLE_MODES: { value: DeliveryMode; label: string; detail: string }[] = [
  { value: "replace", label: "Replace the table", detail: "It will hold exactly this data." },
  { value: "append", label: "Add the rows", detail: "Keep what is there and add these." },
  { value: "update", label: "Update matching rows", detail: "Rows with the same key are replaced; new ones added." },
];

const FILE_MODES: { value: DeliveryMode; label: string; detail: string }[] = [
  { value: "replace", label: "Replace the file", detail: "It will hold exactly this data." },
  { value: "append", label: "Add to the file", detail: "Keep what is there and add these rows." },
];

type DeliveryRun = {
  status: string;
  logs_json: { events?: { message?: string }[] } | null;
  summary_json: {
    rows_written?: number;
    rows_updated?: number;
    rows_added?: number;
    table_created?: boolean | null;
    warnings?: string[];
    error?: string;
  } | null;
};

function rowsWords(count: number): string {
  return countOf(count, "row");
}

/** The finished delivery, read from the run the worker wrote. */
export function resultFromRun(started: DeliveryResult, run: DeliveryRun): DeliveryResult {
  const summary = run.summary_json ?? {};
  const messages = (run.logs_json?.events ?? []).map((event) => event.message ?? "").filter(Boolean);
  const written = summary.rows_written ?? 0;
  const succeeded = run.status === "succeeded";
  return {
    ...started,
    status: succeeded ? "succeeded" : "failed",
    message: succeeded
      ? `Delivered ${rowsWords(written)} to ${started.target}.`
      : summary.error ?? messages.at(-1) ?? "The delivery stopped before it began.",
    rows_written: succeeded ? written : 0,
    rows_updated: succeeded ? summary.rows_updated ?? 0 : 0,
    rows_added: succeeded ? summary.rows_added ?? 0 : 0,
    table_created: summary.table_created ?? null,
    warnings: summary.warnings ?? [],
  };
}

/** A database-safe table name from a dataset name: "Sample customers" → "sample_customers". */
export function tableNameFor(datasetName: string): string {
  const cleaned = datasetName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 60);
  return /^[a-z_]/.test(cleaned) ? cleaned || "dataset" : `t_${cleaned}`;
}

/**
 * Deliver a dataset to a destination: pick where, say how, see what will be
 * written, then write it. The look comes before the write, because
 * "replace the table" in the wrong place is not undone by a second click.
 */
export function DeliverDatasetModal({ open, onClose, projectId, datasetId, datasetName, columns }: DeliverDatasetModalProps) {
  const [destinations, setDestinations] = useState<DestinationRecord[] | null>(null);
  const [destinationId, setDestinationId] = useState("");
  const [tableName, setTableName] = useState(() => tableNameFor(datasetName));
  const [fileName, setFileName] = useState(() => tableNameFor(datasetName));
  const [fileFormat, setFileFormat] = useState<"csv" | "parquet">("csv");
  const [mode, setMode] = useState<DeliveryMode>("replace");
  const [keys, setKeys] = useState<string[]>([]);
  const [preview, setPreview] = useState<DeliveryPreview | null>(null);
  const [previewProblem, setPreviewProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<DeliveryResult | null>(null);
  const [progress, setProgress] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setResult(null);
    setProgress([]);
    setError(null);
    let cancelled = false;
    apiFetch<DestinationListResponse>(`/projects/${projectId}/destinations`)
      .then((data) => {
        if (cancelled) return;
        const usable = data.items.filter((item) => item.status === "active" && KIND_BY_TYPE.has(item.destination_type));
        setDestinations(usable);
        setDestinationId((current) => current || usable[0]?.id || "");
      })
      .catch((caught) => {
        if (!cancelled) setError(extractErrorMessage(caught));
      });
    return () => {
      cancelled = true;
    };
  }, [open, projectId]);

  const destination = destinations?.find((item) => item.id === destinationId) ?? null;
  const kind = destination ? KIND_BY_TYPE.get(destination.destination_type) ?? null : null;
  const delivers = kind?.delivers ?? "table";
  const modes = delivers === "table" ? TABLE_MODES : FILE_MODES;

  // Files cannot update matching rows; fall back rather than send a request that will be refused.
  useEffect(() => {
    if (delivers === "file" && mode === "update") setMode("replace");
  }, [delivers, mode]);

  const request = useMemo<DeliveryRequest | null>(() => {
    if (!destination) return null;
    return delivers === "table"
      ? { destination_id: destination.id, mode, table_name: tableName.trim(), key_columns: mode === "update" ? keys : [] }
      : { destination_id: destination.id, mode, file_name: fileName.trim(), file_format: fileFormat };
  }, [destination, delivers, mode, tableName, keys, fileName, fileFormat]);

  // What would be written, refreshed as the choices change.
  useEffect(() => {
    if (!open || !request || result) return;
    if (delivers === "table" && mode === "update" && keys.length === 0) {
      setPreview(null);
      setPreviewProblem("Choose the column (or columns) that identify a row.");
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      apiFetch<DeliveryPreview>(`/projects/${projectId}/datasets/${datasetId}/deliver/preview`, {
        method: "POST",
        body: JSON.stringify(request),
      })
        .then((next) => {
          if (cancelled) return;
          setPreview(next);
          setPreviewProblem(null);
        })
        .catch((caught) => {
          if (cancelled) return;
          setPreview(null);
          setPreviewProblem(extractErrorMessage(caught));
        });
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [open, request, result, projectId, datasetId, delivers, mode, keys.length]);

  // A large dataset is written by the background worker: follow its run.
  const queued = result?.status === "queued" ? result : null;
  useEffect(() => {
    if (!queued) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const run = await apiFetch<DeliveryRun>(`/projects/${projectId}/runs/${queued.run_id}`);
        if (cancelled) return;
        const messages = (run.logs_json?.events ?? []).map((event) => event.message ?? "").filter(Boolean);
        if (messages.length) setProgress(messages);
        if (run.status === "succeeded" || run.status === "failed") {
          setResult(resultFromRun(queued, run));
          return;
        }
      } catch {
        // A missed poll is not news; the next one tries again.
      }
      if (!cancelled) timer = window.setTimeout(poll, 2000);
    };
    timer = window.setTimeout(poll, 500);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [queued, projectId]);

  const deliver = async () => {
    if (!request) return;
    setBusy(true);
    setError(null);
    try {
      const delivered = await apiFetch<DeliveryResult>(`/projects/${projectId}/datasets/${datasetId}/deliver`, {
        method: "POST",
        body: JSON.stringify(request),
      });
      setResult(delivered);
      if (delivered.status === "queued") setProgress([delivered.message]);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Deliver “${datasetName}”`}
      description="Copy this dataset into a database table or a file in storage."
      widthClassName="max-w-2xl"
      footer={
        result ? (
          <div className="flex justify-end gap-2">
            <Link href={`/projects/${projectId}/runs/${result.run_id}/audit`} className={buttonClassName("ghost", "sm")}>
              See the run
            </Link>
            <Button size="sm" onClick={onClose}>
              {queued ? "Close" : "Done"}
            </Button>
          </div>
        ) : destinations && destinations.length > 0 ? (
          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button size="sm" onClick={() => void deliver()} disabled={busy || !preview}>
              <Icon name="send" size={14} />
              {busy ? "Delivering…" : "Deliver"}
            </Button>
          </div>
        ) : undefined
      }
    >
      {error ? (
        <p role="alert" className="mb-3 rounded-xl border border-danger-line bg-danger-soft px-3 py-2 text-[13px] text-danger">
          {error}
        </p>
      ) : null}

      {queued ? (
        <div role="status" className="rounded-2xl border border-line bg-sunken px-4 py-3 text-[14px] text-ink-2">
          <p className="font-medium text-ink">Delivering in the background</p>
          <ul className="mt-1 space-y-0.5">
            {progress.map((line, index) => (
              <li key={`${index}-${line}`}>{line}</li>
            ))}
          </ul>
          <p className="mt-2 text-[13px] text-ink-3">
            You can close this window. The delivery carries on; the Runs page and your notifications say how it went.
          </p>
        </div>
      ) : result ? (
        <div
          role="status"
          className={cx(
            "rounded-2xl border px-4 py-3 text-[14px]",
            result.status === "succeeded" ? "border-success-line bg-success-soft text-success" : "border-danger-line bg-danger-soft text-danger",
          )}
        >
          <p className="font-medium">{result.status === "succeeded" ? "Delivered" : "Not delivered"}</p>
          <p className="mt-1">{result.message}</p>
          {result.status === "succeeded" && result.mode === "update" ? (
            <p className="mt-1">
              {formatCount(result.rows_updated)} updated, {formatCount(result.rows_added)} added.
            </p>
          ) : null}
          {result.warnings.map((warning) => (
            <p key={warning} className="mt-1 text-[13px]">
              {warning}
            </p>
          ))}
        </div>
      ) : destinations === null ? (
        <p className="py-4 text-[14px] text-muted">Loading destinations…</p>
      ) : destinations.length === 0 ? (
        <div className="rounded-2xl border border-line bg-surface p-4 text-[14px] text-ink-3">
          <p>There is nowhere to deliver to yet. Add a database or a storage bucket first.</p>
          <Link href={`/projects/${projectId}/destinations`} className={cx(buttonClassName("primary", "sm"), "mt-3")}>
            Add a destination
          </Link>
        </div>
      ) : (
        <div className="space-y-4">
          <FormField label="Deliver to" htmlFor="deliver-destination">
            <Select id="deliver-destination" value={destinationId} onChange={(event) => setDestinationId(event.target.value)}>
              {destinations.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} ({KIND_BY_TYPE.get(item.destination_type)?.label ?? item.destination_type})
                </option>
              ))}
            </Select>
          </FormField>

          {delivers === "table" ? (
            <FormField label="Table" htmlFor="deliver-table" description="Created if it is not there.">
              <Input id="deliver-table" value={tableName} onChange={(event) => setTableName(event.target.value)} />
            </FormField>
          ) : (
            <div className="grid gap-3 sm:grid-cols-[1fr_160px]">
              <FormField label="File name" htmlFor="deliver-file" description="Folders are fine: daily/orders.">
                <Input id="deliver-file" value={fileName} onChange={(event) => setFileName(event.target.value)} />
              </FormField>
              <FormField label="Format" htmlFor="deliver-format">
                <Select
                  id="deliver-format"
                  value={fileFormat}
                  onChange={(event) => setFileFormat(event.target.value as "csv" | "parquet")}
                >
                  <option value="csv">CSV</option>
                  <option value="parquet">Parquet</option>
                </Select>
              </FormField>
            </div>
          )}

          <fieldset>
            <legend className="mb-2 text-sm font-medium text-ink">How</legend>
            <div className="grid gap-2 sm:grid-cols-3">
              {modes.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  aria-pressed={mode === option.value}
                  onClick={() => setMode(option.value)}
                  className={cx(
                    "rounded-xl border px-3 py-2 text-left transition",
                    mode === option.value
                      ? "border-[color:var(--accent)] bg-[color:var(--accent-faint)]"
                      : "border-line bg-surface hover:border-line-strong",
                  )}
                >
                  <span className="block text-[14px] font-medium text-ink">{option.label}</span>
                  <span className="block text-[12px] leading-4 text-ink-3">{option.detail}</span>
                </button>
              ))}
            </div>
          </fieldset>

          {delivers === "table" && mode === "update" ? (
            <div>
              <p className="mb-2 text-sm font-medium text-ink">Match rows on</p>
              <div className="flex flex-wrap gap-1.5">
                {columns.map((column) => {
                  const on = keys.includes(column);
                  return (
                    <button
                      key={column}
                      type="button"
                      aria-pressed={on}
                      onClick={() => setKeys((current) => (on ? current.filter((key) => key !== column) : [...current, column]))}
                      className={cx(
                        "rounded-full border px-2.5 py-1 text-[13px] transition",
                        on ? "border-[color:var(--accent)] bg-[color:var(--accent-faint)] text-ink" : "border-line text-ink-3 hover:text-ink",
                      )}
                    >
                      {column}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          <section aria-label="What will be written" className="rounded-2xl border border-line bg-sunken p-3">
            <h3 className="text-[13px] font-semibold text-ink">What will be written</h3>
            {preview ? (
              <>
                <p className="mt-1 break-all text-[13px] text-ink-2">
                  {countOf(preview.rows, "row")} to <span className="font-mono text-[12px]">{preview.target}</span>
                </p>
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {preview.columns.map((column) => (
                    <li key={column.name} className="rounded-lg border border-line bg-surface px-2 py-0.5 text-[12px] text-ink-2">
                      {column.name} <span className="text-muted">{column.type}</span>
                      {column.key ? <span className="ml-1 font-medium text-[color:var(--accent-muted)]">key</span> : null}
                    </li>
                  ))}
                </ul>
                <ul className="mt-2 space-y-0.5 text-[12px] leading-5 text-ink-3">
                  {preview.notes.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="mt-1 text-[13px] text-ink-3">{previewProblem ?? "Working it out…"}</p>
            )}
          </section>
        </div>
      )}
    </Modal>
  );
}
