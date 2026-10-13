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
import { Button, FormField, Input, Modal, Select } from "@platform/shared-ui";

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
      setError("Choose a Tableau connection.");
      return;
    }
    if (!tableauProjectId.trim()) {
      setError("Choose a Tableau project, or paste its ID.");
      return;
    }
    if (!datasourceName.trim()) {
      setError("Name the data source in Tableau.");
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
      title="Send to Tableau"
      description="Puts this dataset into a Tableau project as a data source, ready for workbooks."
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
          <p className="text-sm text-ink-3">Loading your Tableau connections…</p>
        ) : connections.length === 0 ? (
          <p className="text-sm text-ink-3">
            No Tableau connection yet.{" "}
            <Link href={`/projects/${projectId}/bi-connections`} className="text-accent underline">
              Add one
            </Link>{" "}
            first.
          </p>
        ) : (
          <FormField label="Connection" htmlFor="tableau-connection">
            <Select
              id="tableau-connection"
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
            </Select>
          </FormField>
        )}
        {projects.length > 0 ? (
          <FormField label="Tableau project" htmlFor="tableau-project">
            <Select id="tableau-project" value={tableauProjectId} onChange={(e) => setTableauProjectId(e.target.value)}>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </FormField>
        ) : (
          <div className="flex flex-wrap items-end gap-2">
            <FormField
              label="Tableau project"
              htmlFor="tableau-project-id"
              description="List the projects this connection can reach, or paste a project ID from Tableau."
            >
              <Input
                id="tableau-project-id"
                className="font-mono"
                value={tableauProjectId}
                onChange={(e) => setTableauProjectId(e.target.value)}
                autoComplete="off"
              />
            </FormField>
            <Button variant="secondary" size="sm" disabled={!connectionId || loadingMeta} onClick={() => void loadProjects()}>
              {loadingMeta ? "Listing…" : "List projects"}
            </Button>
          </div>
        )}
        <FormField label="Data source name in Tableau" htmlFor="tableau-name">
          <Input
            id="tableau-name"
            value={datasourceName}
            onChange={(e) => setDatasourceName(e.target.value)}
            placeholder="Customers"
            autoComplete="off"
          />
        </FormField>
        <FormField
          label="If it is already there"
          htmlFor="tableau-mode"
          description={writeMode === "replace" ? "Workbooks using the old data source see the new data." : undefined}
        >
          <Select id="tableau-mode" value={writeMode} onChange={(e) => setWriteMode(e.target.value as "replace" | "create_only")}>
            <option value="create_only">Stop, and leave it as it is</option>
            <option value="replace">Replace it with this data</option>
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
