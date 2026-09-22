"use client";

import { useEffect, useState } from "react";

import { Button, FormField, Input, Select } from "@platform/shared-ui";

import { useToast } from "@/components/providers/toast-provider";
import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import type { ApiToken, ApiTokenCreatedResponse, ApiTokenListResponse } from "@platform/shared-types";

const SCOPE_HELP: Record<ApiToken["scope"], string> = {
  read: "Read only — can fetch, cannot change anything.",
  write: "Read and write — can create and edit, but not manage accounts.",
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

  const reload = () =>
    apiFetch<ApiTokenListResponse>("/auth/tokens")
      .then((r) => setTokens(r.items))
      .catch(() => setTokens([]));

  useEffect(() => {
    void reload();
  }, []);

  const create = async () => {
    setBusy(true);
    try {
      const created = await apiFetch<ApiTokenCreatedResponse>("/auth/tokens", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), scope }),
      });
      setFreshSecret(created.secret);
      setName("");
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
      toast.success("Copied", "Store it somewhere safe — it will not be shown again.");
    } catch {
      toast.info("Copy it now", "It will not be shown again.");
    }
  };

  return (
    <div className="space-y-4 px-4 py-4">
      {freshSecret ? (
        <div className="rounded-xl border border-success-line bg-success-soft px-3.5 py-3">
          <div className="text-[12px] font-medium text-success">
            Your new token — copy it now, it will not be shown again.
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
              placeholder="CI pipeline"
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
        <Button onClick={() => void create()} disabled={busy || !name.trim()}>
          {busy ? "Creating…" : "Create token"}
        </Button>
      </div>

      {tokens.length === 0 ? (
        <p className="text-[12px] text-muted">
          No tokens yet. Create one to call the API from a script or another system.
        </p>
      ) : (
        <ul className="divide-y divide-line rounded-xl border border-line">
          {tokens.map((token) => {
            const revoked = token.revoked_at !== null;
            return (
              <li key={token.id} className="flex flex-wrap items-center gap-3 px-3.5 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className={`text-[13px] ${revoked ? "text-muted line-through" : "text-ink"}`}>
                      {token.name}
                    </span>
                    <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[10.5px] text-ink-3">
                      {token.prefix}…
                    </code>
                    <span className="rounded-full border border-line px-1.5 py-0.5 text-[10px] uppercase tracking-[0.1em] text-ink-3">
                      {token.scope}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[11px] text-muted">
                    {revoked
                      ? `Revoked ${formatDate(token.revoked_at as string)}`
                      : token.last_used_at
                        ? `Last used ${formatDate(token.last_used_at)}`
                        : "Never used"}
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
