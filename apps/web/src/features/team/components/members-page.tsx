"use client";

import { useCallback, useEffect, useState } from "react";

import type {
  AuthUser,
  MemberListResponse,
  ProjectMember,
  ProjectRole,
  RoleCatalogResponse,
} from "@platform/shared-types";
import { Button, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";

type MembersPageProps = {
  currentUser: AuthUser;
  projectId: string;
  initial: MemberListResponse;
};

const ROLE_ORDER: ProjectRole[] = ["viewer", "operator", "editor", "admin"];

const ROLE_TONE: Record<ProjectRole, string> = {
  admin: "border-accent-line bg-accent-soft text-accent",
  editor: "border-info-line bg-info-soft text-info",
  operator: "border-accent-line bg-accent-soft text-accent",
  viewer: "border-line bg-surface-2 text-ink-2",
};

export function MembersPageView({ currentUser, projectId, initial }: MembersPageProps) {
  const [data, setData] = useState(initial);
  const [roles, setRoles] = useState<RoleCatalogResponse["items"]>([]);
  const [username, setUsername] = useState("");
  const [role, setRole] = useState<ProjectRole>("viewer");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiFetch<RoleCatalogResponse>("/access/roles")
      .then((response) => setRoles(response.items))
      .catch(() => setRoles([]));
  }, []);

  const reload = useCallback(async () => {
    setData(await apiFetch<MemberListResponse>(`/projects/${projectId}/members`));
  }, [projectId]);

  const invite = useCallback(async () => {
    if (!username.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/projects/${projectId}/members`, {
        method: "POST",
        body: JSON.stringify({ username: username.trim(), role }),
      });
      setUsername("");
      await reload();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }, [projectId, username, role, reload]);

  const changeRole = useCallback(
    async (member: ProjectMember, next: ProjectRole) => {
      if (!member.id) return;
      setError(null);
      try {
        await apiFetch(`/projects/${projectId}/members/${member.id}`, {
          method: "PATCH",
          body: JSON.stringify({ role: next }),
        });
        await reload();
      } catch (caught) {
        setError(extractErrorMessage(caught));
      }
    },
    [projectId, reload],
  );

  const remove = useCallback(
    async (member: ProjectMember) => {
      if (!member.id) return;
      setError(null);
      try {
        await apiFetch(`/projects/${projectId}/members/${member.id}`, { method: "DELETE" });
        await reload();
      } catch (caught) {
        setError(extractErrorMessage(caught));
      }
    },
    [projectId, reload],
  );

  const canManage = data.your_role === "admin";

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Team"
      title="People"
      subtitle="Who can reach this project, and what they may do once they are in. The owner is always an admin and cannot be removed."
    >
      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}

      {canManage ? (
        <SectionPanel
          title="Add someone"
          description="They need an account already; this grants it access to this project."
        >
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[200px] flex-1">
              <label
                htmlFor="member-username"
                className="mb-1.5 block text-[12px] font-medium text-ink"
              >
                Username
              </label>
              <input
                id="member-username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="analyst"
                className="h-9 w-full rounded-lg border border-line bg-sunken px-3 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)]"
              />
            </div>
            <div>
              <span className="mb-1.5 block text-[12px] font-medium text-ink">Role</span>
              <div className="flex rounded-lg border border-line p-0.5">
                {ROLE_ORDER.map((value) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setRole(value)}
                    className={cx(
                      "rounded-md px-2.5 py-1.5 text-[12px] capitalize transition",
                      role === value
                        ? "bg-[color:var(--accent)] text-accent-ink"
                        : "text-ink-3 hover:text-ink",
                    )}
                  >
                    {value}
                  </button>
                ))}
              </div>
            </div>
            <Button onClick={invite} disabled={busy || !username.trim()}>
              {busy ? "Adding…" : "Add"}
            </Button>
          </div>

          {roles.length > 0 ? (
            <p className="mt-3 text-[11.5px] leading-5 text-muted">
              {roles.find((entry) => entry.role === role)?.description}
            </p>
          ) : null}
        </SectionPanel>
      ) : null}

      <SectionPanel
        title={`${data.items.length} ${data.items.length === 1 ? "person" : "people"}`}
        description={
          canManage
            ? "You are an admin here, so you can change roles and remove access."
            : `You have ${data.your_role} access, so this list is read-only.`
        }
      >
        <ul className="divide-y divide-line">
          {data.items.map((member) => (
            <li key={member.user_id} className="flex flex-wrap items-center gap-3 py-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[12px] font-medium text-ink">
                {member.username.slice(0, 2).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] text-ink">{member.username}</span>
                  {member.is_owner ? (
                    <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-ink-3">
                      owner
                    </span>
                  ) : null}
                </div>
                {member.invited_by_username ? (
                  <div className="text-[11px] text-muted">
                    added by {member.invited_by_username}
                  </div>
                ) : null}
              </div>

              {canManage && !member.is_owner && member.user_id !== currentUser.id ? (
                <div className="flex items-center gap-1.5">
                  <select
                    aria-label={`Role for ${member.username}`}
                    value={member.role}
                    onChange={(event) => void changeRole(member, event.target.value as ProjectRole)}
                    className="h-8 rounded-lg border border-line bg-sunken px-2 text-[12px] text-ink outline-none"
                  >
                    {ROLE_ORDER.map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => void remove(member)}
                    aria-label={`Remove ${member.username}`}
                    className="rounded-lg border border-line p-1.5 text-muted transition hover:border-danger-line hover:text-danger"
                  >
                    <Icon name="trash" size={12} />
                  </button>
                </div>
              ) : (
                <span
                  className={cx(
                    "rounded-full border px-2 py-0.5 text-[11px] capitalize",
                    ROLE_TONE[member.role],
                  )}
                >
                  {member.role}
                </span>
              )}
            </li>
          ))}
        </ul>
      </SectionPanel>

      <SectionPanel title="What each role can do">
        <ul className="space-y-2">
          {(roles.length > 0
            ? roles
            : ROLE_ORDER.map((value) => ({ role: value, description: "" }))
          ).map((entry) => (
            <li key={entry.role} className="flex items-start gap-3">
              <span
                className={cx(
                  "mt-0.5 w-20 shrink-0 rounded-full border px-2 py-0.5 text-center text-[11px] capitalize",
                  ROLE_TONE[entry.role],
                )}
              >
                {entry.role}
              </span>
              <span className="text-[12.5px] leading-5 text-ink-3">{entry.description}</span>
            </li>
          ))}
        </ul>
      </SectionPanel>
    </AppShell>
  );
}
