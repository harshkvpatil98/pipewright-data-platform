"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import type {
  BiConnectionMetadataResponse,
  BiIntegrationListResponse,
  BiIntegrationRecord,
  DatasetPublishPowerBiPayload,
  DatasetPublishPowerBiResponse,
} from "@platform/shared-types";
import { Button, Modal } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";

type PublishPowerBiModalProps = {
  open: boolean;
  onClose: () => void;
  projectId: string;
  datasetId: string;
};

export function PublishPowerBiModal({ open, onClose, projectId, datasetId }: PublishPowerBiModalProps) {
  const router = useRouter();
  const [connections, setConnections] = useState<BiIntegrationRecord[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [connectionId, setConnectionId] = useState("");
  const [workspaceId, setWorkspaceId] = useState("");
  const [workspaces, setWorkspaces] = useState<{ id: string; name: string }[]>([]);
  const [loadingMeta, setLoadingMeta] = useState(false);
  const [targetDatasetName, setTargetDatasetName] = useState("");
  const [targetTableName, setTargetTableName] = useState("PublishedData");
  const [writeMode, setWriteMode] = useState<"replace" | "append">("replace");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DatasetPublishPowerBiResponse | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    setError(null);
    setResult(null);
    setWorkspaces([]);
    setWorkspaceId("");
    setTargetDatasetName("");
    setTargetTableName("PublishedData");
    setWriteMode("replace");
    let cancelled = false;
    (async () => {
      setLoadingList(true);
      try {
        const data = await apiFetch<BiIntegrationListResponse>(`/projects/${projectId}/bi-connections`);
        if (cancelled) {
          return;
        }
        const pbi = data.items.filter((c) => c.integration_type === "power_bi" && c.status === "active");
        setConnections(pbi);
        setConnectionId(pbi[0]?.id ?? "");
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

  async function loadWorkspaces() {
    if (!connectionId) {
      setError("Select a Power BI connection first.");
      return;
    }
    setError(null);
    setLoadingMeta(true);
    try {
      const meta = await apiFetch<BiConnectionMetadataResponse>(
        `/projects/${projectId}/bi-connections/${connectionId}/metadata`,
      );
      if (meta.metadata_kind !== "power_bi_workspaces") {
        setWorkspaces([]);
        setError("This connection did not return workspace metadata.");
        return;
      }
      const items = meta.items.map((i) => ({ id: i.id, name: i.name }));
      setWorkspaces(items);
      if (items.length > 0) {
        setWorkspaceId(items[0].id);
      }
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setLoadingMeta(false);
    }
  }

  async function onSubmit() {
    setError(null);
    setResult(null);
    if (!connectionId) {
      setError("Select a Power BI connection.");
      return;
    }
    if (!workspaceId.trim()) {
      setError("Enter or select a workspace ID.");
      return;
    }
    if (!targetDatasetName.trim()) {
      setError("Enter a target dataset name.");
      return;
    }
    if (!targetTableName.trim()) {
      setError("Enter a target table name.");
      return;
    }
    setSubmitting(true);
    try {
      const payload: DatasetPublishPowerBiPayload = {
        connection_id: connectionId,
        workspace_id: workspaceId.trim(),
        target_dataset_name: targetDatasetName.trim(),
        write_mode: writeMode,
      };
      const t = targetTableName.trim();
      if (t) {
        payload.target_table_name = t;
      }
      const res = await apiFetch<DatasetPublishPowerBiResponse>(
        `/projects/${projectId}/datasets/${datasetId}/publish/power-bi`,
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
      title="Publish to Power BI"
      description="Creates or updates a Power BI push dataset in the chosen workspace and uploads this dataset as a single table. Replace deletes an existing dataset with the same name, then recreates it. Append adds rows when the dataset already exists."
      onClose={onClose}
      footer={
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button disabled={submitting || loadingList || connections.length === 0} onClick={() => void onSubmit()}>
            {submitting ? "Publishing…" : "Publish"}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {writeMode === "replace" ? (
          <p className="rounded-xl border border-warning-line bg-warning-soft px-3 py-2 text-xs text-warning">
            Replace removes an existing push dataset with the same name in that workspace, then recreates it. Consumers of the old dataset id may need updates in Power BI.
          </p>
        ) : null}
        {loadingList ? (
          <p className="text-sm text-ink-3">Loading Power BI connections…</p>
        ) : connections.length === 0 ? (
          <p className="text-sm text-ink-3">
            No active Power BI connections.{" "}
            <Link href={`/projects/${projectId}/bi-connections`} className="text-accent underline">
              Create one
            </Link>{" "}
            first.
          </p>
        ) : (
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Power BI connection
            <select
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={connectionId}
              onChange={(e) => {
                setConnectionId(e.target.value);
                setWorkspaces([]);
                setWorkspaceId("");
              }}
            >
              {connections.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="flex flex-wrap items-end gap-2">
          <Button variant="secondary" size="sm" disabled={!connectionId || loadingMeta} onClick={() => void loadWorkspaces()}>
            {loadingMeta ? "Loading…" : "Load workspaces"}
          </Button>
        </div>
        {workspaces.length > 0 ? (
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Workspace (from discovery)
            <select
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={workspaceId}
              onChange={(e) => setWorkspaceId(e.target.value)}
            >
              {workspaces.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
          Workspace ID (paste UUID if not using discovery)
          <input
            className="rounded-xl border border-line bg-surface px-3 py-2 font-mono text-sm text-ink"
            value={workspaceId}
            onChange={(e) => setWorkspaceId(e.target.value)}
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            autoComplete="off"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
          Target dataset name
          <input
            className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
            value={targetDatasetName}
            onChange={(e) => setTargetDatasetName(e.target.value)}
            placeholder="e.g. Sales from ETL"
            autoComplete="off"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
          Target table name
          <input
            className="rounded-xl border border-line bg-surface px-3 py-2 font-mono text-sm text-ink"
            value={targetTableName}
            onChange={(e) => setTargetTableName(e.target.value)}
            placeholder="PublishedData"
            autoComplete="off"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
          Write mode
          <select
            className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
            value={writeMode}
            onChange={(e) => setWriteMode(e.target.value as "replace" | "append")}
          >
            <option value="replace">Replace (delete same-named push dataset, then recreate)</option>
            <option value="append">Append (add rows to existing push dataset if present)</option>
          </select>
        </label>
        {error ? (
          <p className="text-sm text-danger" role="alert">
            {error}
          </p>
        ) : null}
        {result ? (
          <div className="rounded-xl border border-line bg-surface px-3 py-3 text-sm text-ink">
            <p className={result.success ? "text-success" : "text-danger"}>{result.message}</p>
            {result.row_count_published != null ? (
              <p className="mt-1 text-xs text-ink-3">Rows published: {result.row_count_published}</p>
            ) : null}
            {result.power_bi_dataset_id ? (
              <p className="mt-1 text-xs text-muted">Power BI dataset id: {result.power_bi_dataset_id}</p>
            ) : null}
            <Link
              href={`/projects/${projectId}/runs/${result.run.id}/audit`}
              className="mt-2 inline-block text-xs text-accent underline"
            >
              View run audit
            </Link>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
