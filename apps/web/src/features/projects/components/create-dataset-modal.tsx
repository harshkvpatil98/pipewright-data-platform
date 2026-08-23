"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@platform/shared-ui";
import { FormField } from "@platform/shared-ui";
import { Input } from "@platform/shared-ui";
import { Modal } from "@platform/shared-ui";
import { Select } from "@platform/shared-ui";
import { Textarea } from "@platform/shared-ui";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import type { CreateDatasetPayload, DatasetStatus, SourceRecord } from "@platform/shared-types";

type CreateDatasetModalProps = {
  open: boolean;
  onClose: () => void;
  projectId: string;
  sources: SourceRecord[];
};

export function CreateDatasetModal({ open, onClose, projectId, sources }: CreateDatasetModalProps) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [originalFilename, setOriginalFilename] = useState("");
  const [status, setStatus] = useState<DatasetStatus>("registered");
  const [rowCount, setRowCount] = useState("");
  const [columnCount, setColumnCount] = useState("");
  const [schemaText, setSchemaText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleClose = () => {
    setName("");
    setSourceId("");
    setOriginalFilename("");
    setStatus("registered");
    setRowCount("");
    setColumnCount("");
    setSchemaText("");
    setError(null);
    setSubmitting(false);
    onClose();
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (name.trim().length < 2) {
      setError("Dataset name must be at least 2 characters.");
      return;
    }

    let schemaSnapshot: Record<string, unknown> | null = null;
    if (schemaText.trim()) {
      try {
        const parsed = JSON.parse(schemaText);
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
          throw new Error("Schema snapshot must be a JSON object.");
        }
        schemaSnapshot = parsed as Record<string, unknown>;
      } catch (parseError) {
        setError(extractErrorMessage(parseError));
        return;
      }
    }

    const payload: CreateDatasetPayload = {
      name: name.trim(),
      source_id: sourceId || null,
      original_filename: originalFilename.trim() || null,
      status,
      row_count: rowCount ? Number(rowCount) : null,
      column_count: columnCount ? Number(columnCount) : null,
      schema_snapshot: schemaSnapshot,
    };

    try {
      setSubmitting(true);
      await apiFetch(`/projects/${projectId}/datasets`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      handleClose();
      router.refresh();
    } catch (submitError) {
      setError(extractErrorMessage(submitError));
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Register dataset"
      description="Create a dataset record linked to the project and optionally tie it to a registered source."
      footer={
        <div className="flex items-center justify-end gap-3">
          <Button variant="secondary" onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
          <Button type="submit" form="create-dataset-form" disabled={submitting || name.trim().length < 2}>
            {submitting ? "Saving..." : "Add dataset"}
          </Button>
        </div>
      }
    >
      <form id="create-dataset-form" className="space-y-5" onSubmit={handleSubmit}>
        <div className="grid gap-5 lg:grid-cols-2">
          <FormField label="Dataset name" htmlFor="dataset-name" description="Use the logical dataset name that consumers will recognize.">
            <Input id="dataset-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Customer orders snapshot" autoFocus />
          </FormField>
          <FormField label="Linked source" htmlFor="dataset-source" description="Optional source linkage for traceability and future pipeline execution.">
            <Select id="dataset-source" value={sourceId} onChange={(event) => setSourceId(event.target.value)}>
              <option value="">No linked source</option>
              {sources.map((source) => (
                <option key={source.id} value={source.id}>
                  {source.name}
                </option>
              ))}
            </Select>
          </FormField>
        </div>
        <div className="grid gap-5 lg:grid-cols-3">
          <FormField label="Status" htmlFor="dataset-status" description="Registered is appropriate before any processing occurs.">
            <Select id="dataset-status" value={status} onChange={(event) => setStatus(event.target.value as DatasetStatus)}>
              <option value="registered">Registered</option>
              <option value="processing">Processing</option>
              <option value="ready">Ready</option>
              <option value="failed">Failed</option>
            </Select>
          </FormField>
          <FormField label="Row count" htmlFor="dataset-row-count" description="Optional until profiling or ingestion runs populate it.">
            <Input id="dataset-row-count" value={rowCount} onChange={(event) => setRowCount(event.target.value)} inputMode="numeric" placeholder="12500" />
          </FormField>
          <FormField label="Column count" htmlFor="dataset-column-count" description="Optional structural metadata for quick review.">
            <Input id="dataset-column-count" value={columnCount} onChange={(event) => setColumnCount(event.target.value)} inputMode="numeric" placeholder="34" />
          </FormField>
        </div>
        <FormField label="Original filename" htmlFor="dataset-filename" description="Helpful for file-origin registrations and audit context.">
          <Input id="dataset-filename" value={originalFilename} onChange={(event) => setOriginalFilename(event.target.value)} placeholder="orders_2026_04_01.csv" />
        </FormField>
        <FormField label="Schema snapshot JSON" htmlFor="dataset-schema" description="Optional early snapshot of inferred fields or structural hints.">
          <Textarea id="dataset-schema" value={schemaText} onChange={(event) => setSchemaText(event.target.value)} className="font-mono text-[13px]" placeholder='{"columns": [{"name": "order_id", "type": "string"}]}' />
        </FormField>
        {error ? <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div> : null}
      </form>
    </Modal>
  );
}
