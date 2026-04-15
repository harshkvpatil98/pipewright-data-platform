"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@platform/shared-ui";
import { FormField } from "@platform/shared-ui";
import { Input } from "@platform/shared-ui";
import { Modal } from "@platform/shared-ui";
import { Select } from "@platform/shared-ui";
import { Textarea } from "@platform/shared-ui";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import type { CreateSourcePayload, SourceStatus, SourceType } from "@platform/shared-types";

type CreateSourceModalProps = {
  open: boolean;
  onClose: () => void;
  projectId: string;
};

const sourceTypeExamples: Record<SourceType, Record<string, unknown>> = {
  csv: { path: "incoming/customers.csv", delimiter: ",", encoding: "utf-8" },
  excel: { workbook: "incoming/finance.xlsx", worksheet: "Sheet1" },
  json: { path: "incoming/orders.json", json_path: "$" },
  api: { base_url: "https://api.example.com", method: "GET", resource: "/v1/data" },
  postgres: { host: "db.internal", port: 5432, database: "warehouse", schema: "public", table: "orders" },
  s3: { bucket: "raw-ingestion", key: "customers/2026-04-01.csv", region: "us-east-1" },
};

export function CreateSourceModal({ open, onClose, projectId }: CreateSourceModalProps) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [sourceType, setSourceType] = useState<SourceType>("csv");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<SourceStatus>("active");
  const [configText, setConfigText] = useState("{}");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const example = useMemo(() => JSON.stringify(sourceTypeExamples[sourceType], null, 2), [sourceType]);

  const handleClose = () => {
    setName("");
    setSourceType("csv");
    setDescription("");
    setStatus("active");
    setConfigText("{}");
    setError(null);
    setSubmitting(false);
    onClose();
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (name.trim().length < 2) {
      setError("Source name must be at least 2 characters.");
      return;
    }

    let configJson: Record<string, unknown>;
    try {
      const parsed = JSON.parse(configText || "{}");
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        throw new Error("Source config must be a JSON object.");
      }
      configJson = parsed as Record<string, unknown>;
    } catch (parseError) {
      setError(extractErrorMessage(parseError));
      return;
    }

    const payload: CreateSourcePayload = {
      name: name.trim(),
      source_type: sourceType,
      description: description.trim() || null,
      status,
      config_json: configJson,
    };

    try {
      setSubmitting(true);
      await apiFetch(`/projects/${projectId}/sources`, {
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
      title="Register source"
      description="Capture where the project data originates and store the initial connection metadata for downstream registration."
      footer={
        <div className="flex items-center justify-end gap-3">
          <Button variant="secondary" onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
          <Button type="submit" form="create-source-form" disabled={submitting || name.trim().length < 2}>
            {submitting ? "Saving..." : "Add source"}
          </Button>
        </div>
      }
    >
      <form id="create-source-form" className="space-y-5" onSubmit={handleSubmit}>
        <div className="grid gap-5 lg:grid-cols-2">
          <FormField label="Source name" htmlFor="source-name" description="Give the registration a stable, human-readable label.">
            <Input id="source-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Finance exports bucket" autoFocus />
          </FormField>
          <FormField label="Source type" htmlFor="source-type" description="Select the current integration class for this registration.">
            <Select id="source-type" value={sourceType} onChange={(event) => setSourceType(event.target.value as SourceType)}>
              <option value="csv">CSV</option>
              <option value="excel">Excel</option>
              <option value="json">JSON</option>
              <option value="api">API</option>
              <option value="postgres">PostgreSQL</option>
              <option value="s3">Amazon S3</option>
            </Select>
          </FormField>
        </div>
        <div className="grid gap-5 lg:grid-cols-2">
          <FormField label="Status" htmlFor="source-status" description="Use pending when the registration is not yet operational.">
            <Select id="source-status" value={status} onChange={(event) => setStatus(event.target.value as SourceStatus)}>
              <option value="active">Active</option>
              <option value="pending">Pending</option>
              <option value="disabled">Disabled</option>
            </Select>
          </FormField>
          <FormField label="Description" htmlFor="source-description" description="Optional context for owners, contracts, or expected refresh patterns.">
            <Input id="source-description" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Raw invoice drops from the shared finance workspace" />
          </FormField>
        </div>
        <FormField
          label="Configuration JSON"
          htmlFor="source-config"
          description="Store structured metadata only for now. Example configuration updates as you change the source type."
        >
          <Textarea id="source-config" value={configText} onChange={(event) => setConfigText(event.target.value)} className="font-mono text-[13px]" />
        </FormField>
        <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-4">
          <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Suggested JSON</div>
          <pre className="mt-3 overflow-x-auto text-xs leading-6 text-slate-300">{example}</pre>
        </div>
        {error ? <div className="rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">{error}</div> : null}
      </form>
    </Modal>
  );
}
