"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactElement } from "react";

import type {
  AuthUser,
  BiConnectionMetadataResponse,
  BiIntegrationCreatePayload,
  BiIntegrationRecord,
  BiIntegrationType,
  BiIntegrationUpdatePayload,
  DestinationTestResult,
} from "@platform/shared-types";
import { Button, FormField, Modal, SectionPanel, Select } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { OperationalError } from "@/components/operational/operational-messages";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate, titleCase } from "@/lib/format";

type BiConnectionsPageViewProps = {
  currentUser: AuthUser;
  projectId: string;
  initialItems: BiIntegrationRecord[];
};

type BiFields = {
  tenant_id: string;
  client_id: string;
  client_secret: string;
  workspace_id: string;
  authority_url: string;
  server_url: string;
  site_name: string;
  auth_mode: "password" | "personal_access_token";
  username: string;
  password: string;
  personal_access_token_name: string;
  personal_access_token_secret: string;
  api_version: string;
};

function emptyFields(): BiFields {
  return {
    tenant_id: "",
    client_id: "",
    client_secret: "",
    workspace_id: "",
    authority_url: "",
    server_url: "",
    site_name: "",
    auth_mode: "password",
    username: "",
    password: "",
    personal_access_token_name: "",
    personal_access_token_secret: "",
    api_version: "3.21",
  };
}

function buildConfig(integrationType: BiIntegrationType, fields: BiFields): Record<string, unknown> {
  if (integrationType === "power_bi") {
    const cfg: Record<string, unknown> = {
      tenant_id: fields.tenant_id.trim(),
      client_id: fields.client_id.trim(),
    };
    if (fields.client_secret.trim()) {
      cfg.client_secret = fields.client_secret;
    }
    if (fields.workspace_id.trim()) {
      cfg.workspace_id = fields.workspace_id.trim();
    }
    if (fields.authority_url.trim()) {
      cfg.authority_url = fields.authority_url.trim();
    }
    return cfg;
  }
  const cfg: Record<string, unknown> = {
    server_url: fields.server_url.trim(),
    auth_mode: fields.auth_mode,
    api_version: fields.api_version.trim() || "3.21",
  };
  if (fields.site_name.trim()) {
    cfg.site_name = fields.site_name.trim();
  }
  if (fields.auth_mode === "password") {
    cfg.username = fields.username.trim();
    if (fields.password.trim()) {
      cfg.password = fields.password;
    }
  } else {
    cfg.personal_access_token_name = fields.personal_access_token_name.trim();
    if (fields.personal_access_token_secret.trim()) {
      cfg.personal_access_token_secret = fields.personal_access_token_secret;
    }
  }
  return cfg;
}

function recordToFields(row: BiIntegrationRecord): BiFields {
  const c = row.config_json;
  const base = emptyFields();
  if (row.integration_type === "power_bi") {
    return {
      ...base,
      tenant_id: String(c.tenant_id ?? ""),
      client_id: String(c.client_id ?? ""),
      client_secret: "",
      workspace_id: String(c.workspace_id ?? ""),
      authority_url: String(c.authority_url ?? ""),
    };
  }
  return {
    ...base,
    server_url: String(c.server_url ?? ""),
    site_name: String(c.site_name ?? ""),
    auth_mode: c.auth_mode === "personal_access_token" ? "personal_access_token" : "password",
    username: String(c.username ?? ""),
    password: "",
    personal_access_token_name: String(c.personal_access_token_name ?? ""),
    personal_access_token_secret: "",
    api_version: String(c.api_version ?? "3.21"),
  };
}

function integrationLabel(t: BiIntegrationType): string {
  if (t === "power_bi") {
    return "Power BI";
  }
  return "Tableau";
}

export function BiConnectionsPageView({ currentUser, projectId, initialItems }: BiConnectionsPageViewProps) {
  const router = useRouter();
  const [items, setItems] = useState(initialItems);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<BiIntegrationRecord | null>(null);
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState<BiIntegrationType>("power_bi");
  const [newFields, setNewFields] = useState(() => emptyFields());
  const [editFields, setEditFields] = useState(emptyFields());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [testId, setTestId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<DestinationTestResult | null>(null);
  const [metaId, setMetaId] = useState<string | null>(null);
  const [metaResult, setMetaResult] = useState<BiConnectionMetadataResponse | null>(null);

  useEffect(() => {
    setItems(initialItems);
  }, [initialItems]);

  async function refreshList() {
    const data = await apiFetch<{ items: BiIntegrationRecord[] }>(`/projects/${projectId}/bi-connections`);
    setItems(data.items);
    router.refresh();
  }

  function openEdit(row: BiIntegrationRecord) {
    setEditing(row);
    setEditFields(recordToFields(row));
  }

  async function onCreate() {
    setError(null);
    if (!newName.trim()) {
      setError("Name is required.");
      return;
    }
    if (newType === "power_bi" && !newFields.client_secret.trim()) {
      setError("Client secret is required for a new Power BI connection.");
      return;
    }
    if (newType === "tableau") {
      if (!newFields.server_url.trim()) {
        setError("Server URL is required.");
        return;
      }
      if (newFields.auth_mode === "password" && (!newFields.username.trim() || !newFields.password.trim())) {
        setError("Username and password are required for Tableau password auth.");
        return;
      }
      if (
        newFields.auth_mode === "personal_access_token" &&
        (!newFields.personal_access_token_name.trim() || !newFields.personal_access_token_secret.trim())
      ) {
        setError("Personal access token name and secret are required.");
        return;
      }
    }
    setBusy(true);
    try {
      const payload: BiIntegrationCreatePayload = {
        name: newName.trim(),
        integration_type: newType,
        status: "active",
        config_json: buildConfig(newType, newFields),
      };
      await apiFetch(`/projects/${projectId}/bi-connections`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setCreateOpen(false);
      setNewName("");
      setNewType("power_bi");
      setNewFields(emptyFields());
      await refreshList();
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function onSaveEdit() {
    if (!editing) {
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const patch: BiIntegrationUpdatePayload = {
        name: editing.name.trim(),
        config_json: buildConfig(editing.integration_type, editFields),
      };
      await apiFetch(`/projects/${projectId}/bi-connections/${editing.id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      setEditing(null);
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
      const res = await apiFetch<DestinationTestResult>(`/projects/${projectId}/bi-connections/${id}/test`, {
        method: "POST",
      });
      setTestResult(res);
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setTestId(null);
    }
  }

  async function runDiscover(id: string) {
    setError(null);
    setMetaResult(null);
    setMetaId(id);
    try {
      const res = await apiFetch<BiConnectionMetadataResponse>(
        `/projects/${projectId}/bi-connections/${id}/metadata`,
      );
      setMetaResult(res);
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setMetaId(null);
    }
  }

  function renderPowerBiForm(
    fields: BiFields,
    onChange: (f: BiFields) => void,
    isEdit: boolean,
  ): ReactElement {
    const set = (patch: Partial<BiFields>) => onChange({ ...fields, ...patch });
    return (
      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
          Tenant ID
          <input
            className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
            value={fields.tenant_id}
            onChange={(e) => set({ tenant_id: e.target.value })}
            autoComplete="off"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
          Client ID
          <input
            className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
            value={fields.client_id}
            onChange={(e) => set({ client_id: e.target.value })}
            autoComplete="off"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
          Client secret
          <input
            type="password"
            className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
            value={fields.client_secret}
            onChange={(e) => set({ client_secret: e.target.value })}
            placeholder={isEdit ? "Leave blank to keep stored secret" : ""}
            autoComplete="new-password"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
          Workspace ID (optional)
          <input
            className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
            value={fields.workspace_id}
            onChange={(e) => set({ workspace_id: e.target.value })}
            autoComplete="off"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
          Authority URL (optional)
          <input
            className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
            value={fields.authority_url}
            onChange={(e) => set({ authority_url: e.target.value })}
            placeholder="https://login.microsoftonline.com/…"
            autoComplete="off"
          />
        </label>
      </div>
    );
  }

  function renderTableauForm(
    fields: BiFields,
    onChange: (f: BiFields) => void,
    isEdit: boolean,
  ): ReactElement {
    const set = (patch: Partial<BiFields>) => onChange({ ...fields, ...patch });
    return (
      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
          Server URL (https)
          <input
            className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
            value={fields.server_url}
            onChange={(e) => set({ server_url: e.target.value })}
            autoComplete="off"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
          Site / content URL (optional)
          <input
            className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
            value={fields.site_name}
            onChange={(e) => set({ site_name: e.target.value })}
            autoComplete="off"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
          REST API version
          <input
            className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
            value={fields.api_version}
            onChange={(e) => set({ api_version: e.target.value })}
            autoComplete="off"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
          Auth mode
          <select
            className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
            value={fields.auth_mode}
            onChange={(e) =>
              set({ auth_mode: e.target.value === "personal_access_token" ? "personal_access_token" : "password" })
            }
          >
            <option value="password">Username / password</option>
            <option value="personal_access_token">Personal access token</option>
          </select>
        </label>
        {fields.auth_mode === "password" ? (
          <>
            <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
              Username
              <input
                className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
                value={fields.username}
                onChange={(e) => set({ username: e.target.value })}
                autoComplete="off"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
              Password
              <input
                type="password"
                className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
                value={fields.password}
                onChange={(e) => set({ password: e.target.value })}
                placeholder={isEdit ? "Leave blank to keep stored password" : ""}
                autoComplete="new-password"
              />
            </label>
          </>
        ) : (
          <>
            <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
              Token name
              <input
                className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
                value={fields.personal_access_token_name}
                onChange={(e) => set({ personal_access_token_name: e.target.value })}
                autoComplete="off"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
              Token secret
              <input
                type="password"
                className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
                value={fields.personal_access_token_secret}
                onChange={(e) => set({ personal_access_token_secret: e.target.value })}
                placeholder={isEdit ? "Leave blank to keep stored secret" : ""}
                autoComplete="new-password"
              />
            </label>
          </>
        )}
      </div>
    );
  }

  return (
    <>
      <AppShell
        currentUser={currentUser}
        eyebrow="Project workspace"
        title="BI connections"
        subtitle="Save Power BI and Tableau credentials for publishing from dataset detail (push dataset / Hyper upload). Test and Discover validate auth and list workspaces or projects."
        actions={
          <>
            <Link
              href={`/projects/${projectId}`}
              className="inline-flex items-center rounded-full border border-white/10 bg-white/[0.05] px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-slate-200 hover:border-white/20"
            >
              Back to project
            </Link>
            <Button onClick={() => setCreateOpen(true)}>Create connection</Button>
          </>
        }
      >
        <SectionPanel
          title="Saved BI integrations"
          description="Configs are stored encrypted-at-rest only in the sense of normal DB security; API responses mask secrets. Use Test connection before relying on a profile."
        >
          {error ? (
            <div className="mb-4">
              <OperationalError title="BI connection action failed" message={error} />
            </div>
          ) : null}
          {testResult ? (
            <p
              className={`mb-4 rounded-xl border px-3 py-2 text-sm ${
                testResult.success
                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-100"
                  : "border-amber-500/30 bg-amber-500/10 text-amber-100"
              }`}
            >
              {testResult.success ? "Test succeeded" : "Test failed"}: {testResult.message}
              {testResult.latency_ms != null ? ` (${testResult.latency_ms} ms)` : ""}
            </p>
          ) : null}
          {metaResult ? (
            <div className="mb-4 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-200">
              <p className="mb-2 font-medium text-slate-100">
                {metaResult.metadata_kind.replace(/_/g, " ")} ({metaResult.items.length})
              </p>
              <ul className="max-h-40 list-inside list-disc overflow-y-auto text-slate-300">
                {metaResult.items.slice(0, 50).map((it) => (
                  <li key={it.id}>
                    {it.name} <span className="text-slate-500">({it.id})</span>
                  </li>
                ))}
              </ul>
              {metaResult.items.length > 50 ? <p className="mt-1 text-xs text-slate-500">Showing first 50.</p> : null}
            </div>
          ) : null}
          <div className="overflow-x-auto rounded-2xl border border-white/10">
            <table className="min-w-full divide-y divide-white/10 text-left text-sm text-slate-200">
              <thead className="bg-white/[0.03] text-xs uppercase tracking-[0.14em] text-slate-400">
                <tr>
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Created</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {items.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-slate-500">
                      No BI connections yet. Create one to publish datasets to Power BI or Tableau from dataset detail.
                    </td>
                  </tr>
                ) : (
                  items.map((row) => (
                    <tr key={row.id} className="hover:bg-white/[0.02]">
                      <td className="px-4 py-3 font-medium text-slate-100">{row.name}</td>
                      <td className="px-4 py-3">{integrationLabel(row.integration_type)}</td>
                      <td className="px-4 py-3">{titleCase(row.status)}</td>
                      <td className="px-4 py-3 text-slate-400">{formatDate(row.created_at)}</td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex flex-wrap justify-end gap-2">
                          <Button variant="secondary" size="sm" onClick={() => openEdit(row)}>
                            Edit
                          </Button>
                          <Button
                            variant="secondary"
                            size="sm"
                            disabled={testId === row.id}
                            onClick={() => void runTest(row.id)}
                          >
                            {testId === row.id ? "Testing…" : "Test"}
                          </Button>
                          <Button
                            variant="secondary"
                            size="sm"
                            disabled={metaId === row.id}
                            onClick={() => void runDiscover(row.id)}
                          >
                            {metaId === row.id ? "Discover…" : "Discover"}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </SectionPanel>
      </AppShell>

      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="Create BI connection"
        description="Choose integration type and enter service principal or Tableau credentials."
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button disabled={busy} onClick={() => void onCreate()}>
              Save
            </Button>
          </div>
        }
      >
        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
            Name
            <input
              className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
          </label>
          <FormField label="Integration type" htmlFor="bi-new-type">
            <Select
              id="bi-new-type"
              value={newType}
              onChange={(e) => setNewType(e.target.value as BiIntegrationType)}
            >
              <option value="power_bi">Power BI</option>
              <option value="tableau">Tableau</option>
            </Select>
          </FormField>
          {newType === "power_bi"
            ? renderPowerBiForm(newFields, setNewFields, false)
            : renderTableauForm(newFields, setNewFields, false)}
        </div>
      </Modal>

      <Modal
        open={editing !== null}
        onClose={() => setEditing(null)}
        title="Edit BI connection"
        description="Update display name or credentials. Leave secret fields blank to keep stored values."
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button disabled={busy} onClick={() => void onSaveEdit()}>
              Save
            </Button>
          </div>
        }
      >
        {editing ? (
          <div className="flex flex-col gap-4">
            <p className="text-xs text-slate-500">
              Type: <span className="text-slate-300">{integrationLabel(editing.integration_type)}</span>
            </p>
            <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-slate-500">
              Name
              <input
                className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100"
                value={editing.name}
                onChange={(e) => setEditing({ ...editing, name: e.target.value })}
              />
            </label>
            {editing.integration_type === "power_bi"
              ? renderPowerBiForm(editFields, setEditFields, true)
              : renderTableauForm(editFields, setEditFields, true)}
          </div>
        ) : null}
      </Modal>
    </>
  );
}
