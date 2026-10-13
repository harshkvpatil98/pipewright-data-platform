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
import { Button, FormField, Input, Modal, Select } from "@platform/shared-ui";

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
  const [targetTableName, setTargetTableName] = useState("Data");
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
    setTargetTableName("Data");
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
      setError("Choose a Power BI connection first.");
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
        setError("Power BI did not list any workspaces for this connection.");
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
      setError("Choose a Power BI connection.");
      return;
    }
    if (!workspaceId.trim()) {
      setError("Choose a workspace, or paste its ID.");
      return;
    }
    if (!targetDatasetName.trim()) {
      setError("Name the dataset in Power BI.");
      return;
    }
    if (!targetTableName.trim()) {
      setError("Name the table in Power BI.");
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
      title="Send to Power BI"
      description="Puts this dataset into a Power BI workspace as one table, ready for reports."
      onClose={onClose}
      footer={
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button disabled={submitting || loadingList || connections.length === 0} onClick={() => void onSubmit()}>
            {submitting ? "Sending…" : "Send"}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {loadingList ? (
          <p className="text-sm text-ink-3">Loading your Power BI connections…</p>
        ) : connections.length === 0 ? (
          <p className="text-sm text-ink-3">
            No Power BI connection yet.{" "}
            <Link href={`/projects/${projectId}/bi-connections`} className="text-accent underline">
              Add one
            </Link>{" "}
            first.
          </p>
        ) : (
          <FormField label="Connection" htmlFor="pbi-connection">
            <Select
              id="pbi-connection"
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
            </Select>
          </FormField>
        )}
        {workspaces.length > 0 ? (
          <FormField label="Workspace" htmlFor="pbi-workspace">
            <Select id="pbi-workspace" value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)}>
              {workspaces.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </Select>
          </FormField>
        ) : (
          <div className="flex flex-wrap items-end gap-2">
            <FormField
              label="Workspace"
              htmlFor="pbi-workspace-id"
              description="List the workspaces this connection can reach, or paste a workspace ID from Power BI."
            >
              <Input
                id="pbi-workspace-id"
                className="font-mono"
                value={workspaceId}
                onChange={(e) => setWorkspaceId(e.target.value)}
                autoComplete="off"
              />
            </FormField>
            <Button variant="secondary" size="sm" disabled={!connectionId || loadingMeta} onClick={() => void loadWorkspaces()}>
              {loadingMeta ? "Listing…" : "List workspaces"}
            </Button>
          </div>
        )}
        <FormField label="Dataset name in Power BI" htmlFor="pbi-dataset">
          <Input
            id="pbi-dataset"
            value={targetDatasetName}
            onChange={(e) => setTargetDatasetName(e.target.value)}
            placeholder="Sales"
            autoComplete="off"
          />
        </FormField>
        <FormField label="Table name" htmlFor="pbi-table">
          <Input id="pbi-table" value={targetTableName} onChange={(e) => setTargetTableName(e.target.value)} autoComplete="off" />
        </FormField>
        <FormField
          label="If it is already there"
          htmlFor="pbi-mode"
          description={
            writeMode === "replace"
              ? "Power BI reports built on the old dataset may need reconnecting afterwards."
              : undefined
          }
        >
          <Select id="pbi-mode" value={writeMode} onChange={(e) => setWriteMode(e.target.value as "replace" | "append")}>
            <option value="replace">Replace it with this data</option>
            <option value="append">Add these rows to it</option>
          </Select>
        </FormField>
        {error ? (
          <p className="text-sm text-danger" role="alert">
            {error}
          </p>
        ) : null}
        {result ? (
          <div className="rounded-xl border border-line bg-surface px-3 py-3 text-sm text-ink">
            <p className={result.success ? "text-success" : "text-danger"}>{result.message}</p>
            {result.row_count_published != null ? (
              <p className="mt-1 text-[13px] text-ink-3">{result.row_count_published} rows sent.</p>
            ) : null}
            <Link href={`/projects/${projectId}/runs/${result.run.id}/audit`} className="mt-2 inline-block text-[13px] text-accent underline">
              Open the run
            </Link>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
