"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import type {
  BiConnectionMetadataResponse,
  BiIntegrationListResponse,
  BiIntegrationRecord,
  DatasetPublishTableauPayload,
  DatasetPublishTableauResponse,
} from "@platform/shared-types";
import { Button, Modal } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";

type PublishTableauModalProps = {
  open: boolean;
  onClose: () => void;
  projectId: string;
  datasetId: string;
};

export function PublishTableauModal({ open, onClose, projectId, datasetId }: PublishTableauModalProps) {
  const router = useRouter();
  const [connections, setConnections] = useState<BiIntegrationRecord[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [connectionId, setConnectionId] = useState("");
  const [tableauProjectId, setTableauProjectId] = useState("");
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [loadingMeta, setLoadingMeta] = useState(false);
  const [datasourceName, setDatasourceName] = useState("");
  const [writeMode, setWriteMode] = useState<"replace" | "create_only">("create_only");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DatasetPublishTableauResponse | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    setError(null);
    setResult(null);
    setProjects([]);
    setTableauProjectId("");
    setDatasourceName("");
    setWriteMode("create_only");
    let cancelled = false;
    (async () => {
      setLoadingList(true);
      try {
        const data = await apiFetch<BiIntegrationListResponse>(`/projects/${projectId}/bi-connections`);
        if (cancelled) {
          return;
        }
        const t = data.items.filter((c) => c.integration_type === "tableau" && c.status === "active");
        setConnections(t);
        setConnectionId(t[0]?.id ?? "");
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

  async function loadProjects() {
    if (!connectionId) {
      setError("Select a Tableau connection first.");
      return;
    }
    setError(null);
    setLoadingMeta(true);
    try {
      const meta = await apiFetch<BiConnectionMetadataResponse>(
        `/projects/${projectId}/bi-connections/${connectionId}/metadata`,
      );
      if (meta.metadata_kind !== "tableau_projects") {
        setProjects([]);
        setError("This connection did not return project metadata.");
        return;
      }
      const items = meta.items.map((i) => ({ id: i.id, name: i.name }));
      setProjects(items);
      if (items.length > 0) {
        setTableauProjectId(items[0].id);
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
      setError("Select a Tableau connection.");
      return;
    }
    if (!tableauProjectId.trim()) {
      setError("Enter or select a Tableau project ID.");
      return;
    }
    if (!datasourceName.trim()) {
      setError("Enter a datasource name.");
      return;
    }
    setSubmitting(true);
    try {
      const payload: DatasetPublishTableauPayload = {
        connection_id: connectionId,
        tableau_project_id: tableauProjectId.trim(),
        datasource_name: datasourceName.trim(),
        write_mode: writeMode,
      };
      const res = await apiFetch<DatasetPublishTableauResponse>(
        `/projects/${projectId}/datasets/${datasetId}/publish/tableau`,
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
      title="Publish to Tableau"
      description="Builds a single-table Hyper extract from this dataset and publishes it as a datasource in the selected Tableau project. Replace overwrites an existing datasource with the same name; create-only fails if the name already exists."
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
          <p className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100/90">
            Replace overwrites the published datasource if Tableau accepts the overwrite flag. Use with care on shared
            projects.
          </p>
        ) : null}
        {loadingList ? (
          <p className="text-sm text-slate-400">Loading Tableau connections…</p>
        ) : connections.length === 0 ? (
          <p className="text-sm text-slate-400">
            No active Tableau connections.{" "}
            <Link href={`/projects/${projectId}/bi-connections`} className="text-indigo-300 underline">
              Create one
            </Link>{" "}
            first.
          </p>
        ) : (
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
            Tableau connection
            <select
              className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
              value={connectionId}
              onChange={(e) => {
                setConnectionId(e.target.value);
                setProjects([]);
                setTableauProjectId("");
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
          <Button variant="secondary" size="sm" disabled={!connectionId || loadingMeta} onClick={() => void loadProjects()}>
            {loadingMeta ? "Loading…" : "Load projects"}
          </Button>
        </div>
        {projects.length > 0 ? (
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
            Project (from discovery)
            <select
              className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
              value={tableauProjectId}
              onChange={(e) => setTableauProjectId(e.target.value)}
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
          Tableau project ID (UUID)
          <input
            className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 font-mono text-sm text-slate-100"
            value={tableauProjectId}
            onChange={(e) => setTableauProjectId(e.target.value)}
            placeholder="From Tableau REST / discovery"
            autoComplete="off"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
          Datasource name
          <input
            className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
            value={datasourceName}
            onChange={(e) => setDatasourceName(e.target.value)}
            placeholder="e.g. ETL Customers"
            autoComplete="off"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
          Write mode
          <select
            className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
            value={writeMode}
            onChange={(e) => setWriteMode(e.target.value as "replace" | "create_only")}
          >
            <option value="create_only">Create only (fail if datasource name exists)</option>
            <option value="replace">Replace (overwrite if server allows)</option>
          </select>
        </label>
        {error ? (
          <p className="text-sm text-rose-300" role="alert">
            {error}
          </p>
        ) : null}
        {result ? (
          <div className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-3 text-sm text-slate-200">
            <p className={result.success ? "text-emerald-200/90" : "text-rose-200/90"}>{result.message}</p>
            {result.row_count_published != null ? (
              <p className="mt-1 text-xs text-slate-400">Rows published: {result.row_count_published}</p>
            ) : null}
            {result.tableau_datasource_id ? (
              <p className="mt-1 text-xs text-slate-500">Datasource id: {result.tableau_datasource_id}</p>
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
