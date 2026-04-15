"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import type {
  DatasetPublishPostgresPayload,
  DatasetPublishPostgresResponse,
  DestinationListResponse,
  DestinationRecord,
} from "@platform/shared-types";
import { Button, Modal } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";

type PublishDatasetModalProps = {
  open: boolean;
  onClose: () => void;
  projectId: string;
  datasetId: string;
};

export function PublishDatasetModal({ open, onClose, projectId, datasetId }: PublishDatasetModalProps) {
  const router = useRouter();
  const [destinations, setDestinations] = useState<DestinationRecord[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [destinationId, setDestinationId] = useState("");
  const [tableName, setTableName] = useState("");
  const [writeMode, setWriteMode] = useState<"replace" | "append">("append");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DatasetPublishPostgresResponse | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    setError(null);
    setResult(null);
    setTableName("");
    setWriteMode("append");
    let cancelled = false;
    (async () => {
      setLoadingList(true);
      try {
        const data = await apiFetch<DestinationListResponse>(`/projects/${projectId}/destinations`);
        if (cancelled) {
          return;
        }
        const pg = data.items.filter((d) => d.destination_type === "postgres" && d.status === "active");
        setDestinations(pg);
        setDestinationId(pg[0]?.id ?? "");
      } catch (e) {
        if (!cancelled) {
          setError(extractErrorMessage(e));
        }
      } finally {
        if (!cancelled) {
          setLoadingList(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, projectId]);

  async function onSubmit() {
    setError(null);
    setResult(null);
    if (!destinationId) {
      setError("Select a PostgreSQL destination.");
      return;
    }
    if (!tableName.trim()) {
      setError("Enter a target table name.");
      return;
    }
    setSubmitting(true);
    try {
      const payload: DatasetPublishPostgresPayload = {
        destination_id: destinationId,
        table_name: tableName.trim(),
        write_mode: writeMode,
      };
      const res = await apiFetch<DatasetPublishPostgresResponse>(
        `/projects/${projectId}/datasets/${datasetId}/publish/postgres`,
        {
          method: "POST",
          body: JSON.stringify(payload),
        },
      );
      setResult(res);
      if (res.success) {
        router.refresh();
      }
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      title="Publish to PostgreSQL"
      description="Writes the current dataset file to a saved destination. Replace drops and recreates the target table. Append creates the table if needed, then inserts rows."
      onClose={onClose}
      footer={
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button disabled={submitting || loadingList} onClick={() => void onSubmit()}>
            {submitting ? "Publishing…" : "Publish"}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {writeMode === "replace" ? (
          <p className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100/90">
            Replace mode overwrites the target table (drop and recreate). Use with care on shared databases.
          </p>
        ) : null}
        {loadingList ? (
          <p className="text-sm text-slate-400">Loading destinations…</p>
        ) : destinations.length === 0 ? (
          <p className="text-sm text-slate-400">
            No active PostgreSQL destinations.{" "}
            <Link href={`/projects/${projectId}/destinations`} className="text-indigo-300 underline">
              Create one
            </Link>{" "}
            first.
          </p>
        ) : (
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
            Destination
            <select
              className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
              value={destinationId}
              onChange={(e) => setDestinationId(e.target.value)}
            >
              {destinations.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
          Target table name
          <input
            className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 font-mono text-sm text-slate-100"
            value={tableName}
            onChange={(e) => setTableName(e.target.value)}
            placeholder="e.g. clean_customers"
            autoComplete="off"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
          Write mode
          <select
            className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
            value={writeMode}
            onChange={(e) => setWriteMode(e.target.value as "replace" | "append")}
          >
            <option value="append">Append (create table if missing)</option>
            <option value="replace">Replace (overwrite table)</option>
          </select>
        </label>
        <p className="text-xs text-slate-500">
          <Link
            href={`/projects/${projectId}/schedules?new=1&type=postgres_publish&datasetId=${datasetId}`}
            className="text-indigo-300 underline"
          >
            Schedule publish
          </Link>{" "}
          saves this dataset and target as a recurring job. Runs fire on the cron you set when the due-schedule executor is running (see README / system status).
        </p>
        {error ? (
          <p className="text-sm text-rose-300" role="alert">
            {error}
          </p>
        ) : null}
        {result ? (
          <div className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-3 text-sm text-slate-200">
            <p className={result.success ? "text-emerald-200/90" : "text-rose-200/90"}>{result.message}</p>
            {result.row_count_written != null ? (
              <p className="mt-1 text-xs text-slate-400">Rows written: {result.row_count_written}</p>
            ) : null}
            <Link
              href={`/projects/${projectId}/runs/${result.run.id}/audit`}
              className="mt-2 inline-block text-xs text-indigo-300 underline"
            >
              View run audit
            </Link>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
