"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type {
  AuthUser,
  DestinationCreatePayload,
  DestinationRecord,
  DestinationTestResult,
  DestinationType,
  DestinationUpdatePayload,
} from "@platform/shared-types";
import { Button, Modal, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate, titleCase } from "@/lib/format";

type DestinationsPageViewProps = {
  currentUser: AuthUser;
  projectId: string;
  initialItems: DestinationRecord[];
};

const PG_SSL = ["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] as const;

const emptyFields = (): Record<string, string> => ({
  host: "",
  port: "5432",
  database: "",
  username: "",
  password: "",
  schema: "",
  ssl_mode: "prefer",
  bucket: "",
  region: "",
  access_key_id: "",
  secret_access_key: "",
  prefix: "",
  path: "",
});

function buildConfigForType(
  destinationType: DestinationType,
  fields: Record<string, string>,
): Record<string, unknown> {
  if (destinationType === "postgres") {
    const cfg: Record<string, unknown> = {
      host: fields.host.trim(),
      port: Number.parseInt(fields.port, 10),
      database: fields.database.trim(),
      username: fields.username.trim(),
    };
    if (fields.password.trim()) {
      cfg.password = fields.password;
    }
    if (fields.schema.trim()) {
      cfg.schema = fields.schema.trim();
    }
    if (fields.ssl_mode) {
      cfg.ssl_mode = fields.ssl_mode;
    }
    return cfg;
  }
  if (destinationType === "s3") {
    const cfg: Record<string, unknown> = {
      bucket: fields.bucket.trim(),
      access_key_id: fields.access_key_id.trim(),
    };
    if (fields.secret_access_key.trim()) {
      cfg.secret_access_key = fields.secret_access_key;
    }
    if (fields.region.trim()) {
      cfg.region = fields.region.trim();
    }
    if (fields.prefix.trim()) {
      cfg.prefix = fields.prefix.trim();
    }
    return cfg;
  }
  return { path: fields.path.trim() };
}

function configToFields(destinationType: DestinationType, config: Record<string, unknown>): Record<string, string> {
  const c = config;
  if (destinationType === "postgres") {
    return {
      host: String(c.host ?? ""),
      port: String(c.port ?? "5432"),
      database: String(c.database ?? ""),
      username: String(c.username ?? ""),
      password: "",
      schema: String(c.schema ?? ""),
      ssl_mode: String(c.ssl_mode ?? "prefer"),
      bucket: "",
      region: "",
      access_key_id: "",
      secret_access_key: "",
      prefix: "",
      path: "",
    };
  }
  if (destinationType === "s3") {
    return {
      host: "",
      port: "5432",
      database: "",
      username: "",
      password: "",
      schema: "",
      ssl_mode: "prefer",
      bucket: String(c.bucket ?? ""),
      region: String(c.region ?? ""),
      access_key_id: String(c.access_key_id ?? ""),
      secret_access_key: "",
      prefix: String(c.prefix ?? ""),
      path: "",
    };
  }
  return {
    ...emptyFields(),
    path: String(c.path ?? ""),
  };
}

export function DestinationsPageView({ currentUser, projectId, initialItems }: DestinationsPageViewProps) {
  const router = useRouter();
  const [items, setItems] = useState(initialItems);
  const [createOpen, setCreateOpen] = useState(false);
  const [editDestination, setEditDestination] = useState<DestinationRecord | null>(null);
  const [editFields, setEditFields] = useState<Record<string, string>>(emptyFields());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [testId, setTestId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<DestinationTestResult | null>(null);

  useEffect(() => {
    setItems(initialItems);
  }, [initialItems]);

  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState<DestinationType>("postgres");
  const [newFields, setNewFields] = useState(emptyFields);

  async function refreshList() {
    const data = await apiFetch<{ items: DestinationRecord[] }>(`/projects/${projectId}/destinations`);
    setItems(data.items);
    router.refresh();
  }

  function openEdit(row: DestinationRecord) {
    setEditDestination(row);
    setEditFields(configToFields(row.destination_type, row.config_json));
  }

  async function onCreate() {
    setError(null);
    if (!newName.trim()) {
      setError("Name is required.");
      return;
    }
    if (newType === "postgres" && !newFields.password.trim()) {
      setError("Password is required for a new PostgreSQL destination.");
      return;
    }
    if (newType === "s3" && !newFields.secret_access_key.trim()) {
      setError("Secret access key is required for a new S3 destination.");
      return;
    }
    setBusy(true);
    try {
      const payload: DestinationCreatePayload = {
        name: newName.trim(),
        destination_type: newType,
        status: "active",
        config_json: buildConfigForType(newType, newFields),
      };
      await apiFetch(`/projects/${projectId}/destinations`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setCreateOpen(false);
      setNewName("");
      setNewType("postgres");
      setNewFields(emptyFields());
      await refreshList();
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function onSaveEdit() {
    if (!editDestination) {
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const cfg = buildConfigForType(editDestination.destination_type, editFields);
      const patch: DestinationUpdatePayload = {
        name: editDestination.name.trim(),
        config_json: cfg,
      };
      await apiFetch(`/projects/${projectId}/destinations/${editDestination.id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      setEditDestination(null);
      await refreshList();
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function runTest(id: string) {
    setError(null);
    setTestResult(null);
    setTestId(id);
    try {
      const res = await apiFetch<DestinationTestResult>(`/projects/${projectId}/destinations/${id}/test`, {
        method: "POST",
      });
      setTestResult(res);
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setTestId(null);
    }
  }

  function renderConfigForm(
    t: DestinationType,
    fields: Record<string, string>,
    onChange: (f: Record<string, string>) => void,
    isEdit: boolean,
  ) {
    const set = (key: string, value: string) => onChange({ ...fields, [key]: value });
    if (t === "postgres") {
      return (
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Host
            <input
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={fields.host}
              onChange={(e) => set("host", e.target.value)}
              autoComplete="off"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Port
            <input
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={fields.port}
              onChange={(e) => set("port", e.target.value)}
              autoComplete="off"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Database
            <input
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={fields.database}
              onChange={(e) => set("database", e.target.value)}
              autoComplete="off"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Username
            <input
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={fields.username}
              onChange={(e) => set("username", e.target.value)}
              autoComplete="off"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Password
            <input
              type="password"
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={fields.password}
              onChange={(e) => set("password", e.target.value)}
              placeholder={isEdit ? "Leave blank to keep stored secret" : ""}
              autoComplete="new-password"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Schema (optional)
            <input
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={fields.schema}
              onChange={(e) => set("schema", e.target.value)}
              autoComplete="off"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            SSL mode
            <select
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={fields.ssl_mode}
              onChange={(e) => set("ssl_mode", e.target.value)}
            >
              {PG_SSL.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
        </div>
      );
    }
    if (t === "s3") {
      return (
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Bucket
            <input
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={fields.bucket}
              onChange={(e) => set("bucket", e.target.value)}
              autoComplete="off"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Region (optional)
            <input
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={fields.region}
              onChange={(e) => set("region", e.target.value)}
              autoComplete="off"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Access key ID
            <input
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={fields.access_key_id}
              onChange={(e) => set("access_key_id", e.target.value)}
              autoComplete="off"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Secret access key
            <input
              type="password"
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={fields.secret_access_key}
              onChange={(e) => set("secret_access_key", e.target.value)}
              placeholder={isEdit ? "Leave blank to keep stored secret" : ""}
              autoComplete="new-password"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Prefix (optional)
            <input
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={fields.prefix}
              onChange={(e) => set("prefix", e.target.value)}
              autoComplete="off"
            />
          </label>
        </div>
      );
    }
    return (
      <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
        Directory path
        <input
          className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
          value={fields.path}
          onChange={(e) => set("path", e.target.value)}
          autoComplete="off"
        />
      </label>
    );
  }

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Integrations"
      title="Destinations"
      subtitle="Save connection settings for future delivery. Secrets are redacted in API responses; connection tests run on demand only."
      actions={
        <div className="flex flex-wrap gap-2">
          <Link
            href={`/projects/${projectId}`}
            className="rounded-full border border-line bg-surface px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-ink hover:border-line-strong"
          >
            Back to project
          </Link>
          <Button onClick={() => setCreateOpen(true)}>Create destination</Button>
        </div>
      }
    >
      {error ? (
        <p className="mb-4 text-sm text-danger" role="alert">
          {error}
        </p>
      ) : null}
      {testResult ? (
        <SectionPanel title="Last connection test" description="From the most recent test on this page.">
          <p className={`text-sm ${testResult.success ? "text-success" : "text-danger"}`}>
            {testResult.success ? "Success" : "Failed"} · {testResult.message}
            {testResult.latency_ms != null ? ` · ${testResult.latency_ms.toFixed(0)} ms` : ""}
          </p>
        </SectionPanel>
      ) : null}

      <SectionPanel
        title="Saved destinations"
        description="PostgreSQL is fully supported for save and test. S3 and local directory configs can be saved and tested; publishing comes later."
      >
        {items.length === 0 ? (
          <p className="text-sm text-ink-3">
            No delivery destinations yet. Add a PostgreSQL, S3, or local export target to publish or export pipeline outputs.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse text-left text-sm text-ink">
              <thead>
                <tr className="border-b border-line text-xs uppercase tracking-[0.14em] text-muted">
                  <th className="py-2 pr-4 font-medium">Name</th>
                  <th className="py-2 pr-4 font-medium">Type</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 pr-4 font-medium">Updated</th>
                  <th className="py-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id} className="border-b border-line">
                    <td className="py-3 pr-4 font-medium text-ink">{row.name}</td>
                    <td className="py-3 pr-4 font-mono text-xs text-ink-2">{titleCase(row.destination_type)}</td>
                    <td className="py-3 pr-4 text-xs text-ink-3">{row.status}</td>
                    <td className="py-3 pr-4 text-xs text-ink-3">{formatDate(row.updated_at)}</td>
                    <td className="py-3">
                      <div className="flex flex-wrap gap-2">
                        <Button variant="secondary" size="sm" onClick={() => openEdit(row)}>
                          View / Edit
                        </Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          disabled={testId === row.id}
                          onClick={() => void runTest(row.id)}
                        >
                          {testId === row.id ? "Testing…" : "Test connection"}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionPanel>

      <Modal
        open={createOpen}
        title="Create destination"
        description="Credentials are stored like other integration configs. Use a dedicated DB user with minimal privileges where possible."
        onClose={() => {
          setCreateOpen(false);
          setError(null);
        }}
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button disabled={busy} onClick={() => void onCreate()}>
              {busy ? "Saving…" : "Save"}
            </Button>
          </div>
        }
      >
        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Name
            <input
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              autoComplete="off"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Type
            <select
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={newType}
              onChange={(e) => setNewType(e.target.value as DestinationType)}
            >
              <option value="postgres">PostgreSQL</option>
              <option value="s3">Amazon S3</option>
              <option value="local_export">Local directory</option>
            </select>
          </label>
          {renderConfigForm(newType, newFields, setNewFields, false)}
        </div>
      </Modal>

      <Modal
        open={editDestination !== null}
        title="Edit destination"
        description="Secrets are never shown in full after save. Leave password fields blank to keep the stored value."
        onClose={() => setEditDestination(null)}
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => setEditDestination(null)}>
              Cancel
            </Button>
            <Button disabled={busy || !editDestination} onClick={() => void onSaveEdit()}>
              {busy ? "Saving…" : "Save changes"}
            </Button>
          </div>
        }
      >
        {editDestination ? (
          <div className="flex flex-col gap-4">
            <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
              Name
              <input
                className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
                value={editDestination.name}
                onChange={(e) => setEditDestination({ ...editDestination, name: e.target.value })}
                autoComplete="off"
              />
            </label>
            <p className="text-xs text-muted">
              Type: <span className="font-mono text-ink-2">{editDestination.destination_type}</span> (cannot be
              changed)
            </p>
            {renderConfigForm(editDestination.destination_type, editFields, setEditFields, true)}
          </div>
        ) : null}
      </Modal>
    </AppShell>
  );
}
