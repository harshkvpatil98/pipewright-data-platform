"use client";

import { useEffect, useState } from "react";

import { Badge, Button, FormField, Icon, Input, Select, useToast } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import type {
  ApiToken,
  ApiTokenCreatedResponse,
  ApiTokenListResponse,
  ProjectListResponse,
} from "@platform/shared-types";

/** How long a new token lasts (X2): days, or never. */
const LIFETIMES: { days: number | null; label: string }[] = [
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
  { days: 365, label: "A year" },
  { days: 7, label: "7 days" },
  { days: null, label: "Never" },
];

const SCOPE_LABEL: Record<ApiToken["scope"], string> = {
  read: "Read only",
  write: "Read and write",
  admin: "Full access",
};

const SCOPE_HELP: Record<ApiToken["scope"], string> = {
  read: "Read only. Can fetch data but cannot change anything.",
  write: "Read and write. Can create and edit, but cannot manage accounts.",
  admin: "Full access, including account administration. Use sparingly.",
};

/**
 * Create, list and revoke API tokens.
 *
 * A data platform is scripted against on day one; without this the only
 * credential is a password. The secret is shown exactly once — there is no way
 * to retrieve it later, by design — so the UI makes that moment deliberate.
 */
export function ApiTokensPanel() {
  const toast = useToast();
  const [tokens, setTokens] = useState<ApiToken[]>([]);
  const [name, setName] = useState("");
  const [scope, setScope] = useState<ApiToken["scope"]>("read");
  const [busy, setBusy] = useState(false);
  const [freshSecret, setFreshSecret] = useState<string | null>(null);
  // Which projects a new token reaches (X2): all, or the ones chosen.
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [limitTo, setLimitTo] = useState<string[] | null>(null);
  const [lifetime, setLifetime] = useState<number | null>(90);

  const reload = () =>
    apiFetch<ApiTokenListResponse>("/auth/tokens")
      .then((r) => setTokens(r.items))
      .catch(() => setTokens([]));

  useEffect(() => {
    void reload();
    apiFetch<ProjectListResponse>("/projects")
      .then((r) => setProjects(r.items.map((item) => ({ id: item.id, name: item.name }))))
      .catch(() => setProjects([]));
  }, []);
  const projectName = (id: string) => projects.find((item) => item.id === id)?.name ?? "a project you cannot see";

  const create = async () => {
    setBusy(true);
    try {
      const created = await apiFetch<ApiTokenCreatedResponse>("/auth/tokens", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), scope, project_ids: limitTo, expires_in_days: lifetime }),
      });
      setFreshSecret(created.secret);
      setName("");
      setLimitTo(null);
      await reload();
    } catch (caught) {
      toast.error("Could not create token", extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (token: ApiToken) => {
    try {
      await apiFetch(`/auth/tokens/${token.id}`, { method: "DELETE" });
      toast.info("Token revoked", `"${token.name}" can no longer be used.`);
      await reload();
    } catch (caught) {
      toast.error("Could not revoke token", extractErrorMessage(caught));
    }
  };

  const copySecret = async () => {
    if (!freshSecret) return;
    try {
      await navigator.clipboard.writeText(freshSecret);
      toast.success("Copied", "Store it somewhere safe. It will not be shown again.");
    } catch {
      toast.info("Copy it now", "It will not be shown again.");
    }
  };

  return (
    <div className="space-y-4 px-4 py-4">
      {freshSecret ? (
        <div className="rounded-xl border border-success-line bg-success-soft px-3.5 py-3">
          <div className="text-[12px] font-medium text-success">
            Your new token. Copy it now; it will not be shown again.
          </div>
          <div className="mt-2 flex items-center gap-2">
            <code className="flex-1 overflow-x-auto whitespace-nowrap rounded-lg bg-surface px-2.5 py-1.5 font-mono text-[12px] text-ink">
              {freshSecret}
            </code>
            <Button variant="secondary" size="sm" onClick={() => void copySecret()}>
              Copy
            </Button>
            <Button size="sm" onClick={() => setFreshSecret(null)}>
              Done
            </Button>
          </div>
        </div>
      ) : null}

      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[180px] flex-1">
          <FormField label="Name" htmlFor="token-name">
            <Input
              id="token-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Nightly export script"
            />
          </FormField>
        </div>
        <div className="w-[220px]">
          <FormField label="Scope" htmlFor="token-scope" description={SCOPE_HELP[scope]}>
            <Select
              id="token-scope"
              value={scope}
              onChange={(e) => setScope(e.target.value as ApiToken["scope"])}
            >
              <option value="read">Read only</option>
              <option value="write">Read and write</option>
              <option value="admin">Admin</option>
            </Select>
          </FormField>
        </div>
        <div className="w-[150px]">
          <FormField label="Lasts" htmlFor="token-lifetime">
            <Select
              id="token-lifetime"
              value={lifetime === null ? "never" : String(lifetime)}
              onChange={(e) => setLifetime(e.target.value === "never" ? null : Number(e.target.value))}
            >
              {LIFETIMES.map((option) => (
                <option key={option.label} value={option.days === null ? "never" : String(option.days)}>
                  {option.label}
                </option>
              ))}
            </Select>
          </FormField>
        </div>
        <Button onClick={() => void create()} disabled={busy || !name.trim() || (limitTo !== null && limitTo.length === 0)}>
          {busy ? "Creating…" : "Create token"}
        </Button>
      </div>

      <fieldset className="rounded-xl border border-line px-3.5 py-2.5">
        <legend className="px-1 text-[12px] text-muted">Projects it reaches</legend>
        <label className="flex items-center gap-2 text-[13px] text-ink">
          <input type="radio" checked={limitTo === null} onChange={() => setLimitTo(null)} />
          Every project you can reach
        </label>
        <label className="mt-1 flex items-center gap-2 text-[13px] text-ink">
          <input type="radio" checked={limitTo !== null} onChange={() => setLimitTo([])} />
          Only these
        </label>
        {limitTo !== null ? (
          <div className="mt-2 flex flex-wrap gap-1.5 pl-5">
            {projects.length === 0 ? <span className="text-[12px] text-muted">You have no projects yet.</span> : null}
            {projects.map((project) => {
              const on = limitTo.includes(project.id);
              return (
                <button
                  key={project.id}
                  type="button"
                  aria-pressed={on}
                  onClick={() =>
                    setLimitTo((current) =>
                      current === null ? [project.id] : on ? current.filter((id) => id !== project.id) : [...current, project.id],
                    )
                  }
                  className={
                    on
                      ? "rounded-full border border-[color:var(--accent)] bg-[color:var(--accent-soft)] px-2.5 py-1 text-[12px] text-ink"
                      : "rounded-full border border-line px-2.5 py-1 text-[12px] text-ink-3 hover:bg-sunken"
                  }
                >
                  {project.name}
                </button>
              );
            })}
          </div>
        ) : null}
        <p className="mt-2 text-[12px] text-muted">
          A token limited to projects reaches nothing else, and says which projects when it is refused.
        </p>
      </fieldset>

      {tokens.length === 0 ? (
        <p className="text-[12px] text-muted">
          No tokens yet. Create one to call the API from a script or another system.
        </p>
      ) : (
        <ul className="divide-y divide-line rounded-xl border border-line">
          {tokens.map((token) => {
            const revoked = token.revoked_at !== null;
            const expired = !revoked && token.expires_at ? new Date(token.expires_at).getTime() <= Date.now() : false;
            return (
              <li key={token.id} className="flex flex-wrap items-center gap-3 px-3.5 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className={`text-[13px] ${revoked || expired ? "text-muted line-through" : "text-ink"}`}>
                      {token.name}
                    </span>
                    <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[12px] text-ink-3">
                      {token.prefix}…
                    </code>
                    <Badge>
                      {SCOPE_LABEL[token.scope] ?? token.scope}
                    </Badge>
                  </div>
                  <div className="mt-0.5 text-[12px] text-muted">
                    {revoked
                      ? `Revoked ${formatDate(token.revoked_at as string)}`
                      : expired
                        ? `Expired ${formatDate(token.expires_at as string)}`
                        : token.last_used_at
                          ? `Last used ${formatDate(token.last_used_at)}`
                          : "Never used"}
                    {!revoked && !expired && token.expires_at ? ` · Expires ${formatDate(token.expires_at)}` : ""}
                    {!revoked && !expired && !token.expires_at ? " · Never expires" : ""}
                  </div>
                  <div className="mt-0.5 text-[12px] text-ink-3">
                    {token.project_ids?.length
                      ? `Only ${token.project_ids.map(projectName).join(", ")}`
                      : "Every project you can reach"}
                  </div>
                </div>
                {revoked ? null : (
                  <button
                    type="button"
                    onClick={() => void revoke(token)}
                    aria-label={`Revoke ${token.name}`}
                    className="rounded-lg border border-line p-1.5 text-muted transition hover:border-danger-line hover:text-danger"
                  >
                    <Icon name="trash" size={12} />
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
