"use client";

import { useCallback, useEffect, useState } from "react";

import type {
  AuthUser,
  MemberListResponse,
  ProjectMember,
  ProjectRole,
  RoleCatalogResponse,
} from "@platform/shared-types";
import { Button, Modal, SectionPanel } from "@platform/shared-ui";

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

export function MembersPageView({
  currentUser,
  projectId,
  initial,
}: MembersPageProps) {
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
    setData(
      await apiFetch<MemberListResponse>(`/projects/${projectId}/members`),
    );
  }, [projectId]);

  const [adding, setAdding] = useState(false);

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
      setAdding(false);
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
        await apiFetch(`/projects/${projectId}/members/${member.id}`, {
          method: "DELETE",
        });
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
      title="People"
      subtitle="Who can see and change this project, and what each person can do."
      actions={
        canManage ? (
          <Button onClick={() => setAdding(true)}>Add a person</Button>
        ) : undefined
      }
    >
      {error ? (
        <div className="border-danger-line bg-danger-soft text-danger rounded-2xl border px-4 py-3 text-sm">
          {error}
        </div>
      ) : null}

      <SectionPanel
        title={`${data.items.length} ${data.items.length === 1 ? "person" : "people"}`}
        description={
          canManage
            ? "You are an admin here, so you can change roles and remove access."
            : `You have ${data.your_role} access, so this list is read-only.`
        }
      >
        <ul className="divide-line divide-y">
          {data.items.map((member) => (
            <li
              key={member.user_id}
              className="flex flex-wrap items-center gap-3 py-3"
            >
              <div className="bg-surface-2 text-ink flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[12px] font-medium">
                {member.username.slice(0, 2).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-ink text-[13px]">
                    {member.username}
                  </span>
                  {member.is_owner ? (
                    <span className="bg-surface-2 text-ink-3 rounded px-1.5 py-0.5 text-[12px]">
                      owner
                    </span>
                  ) : null}
                </div>
                {member.invited_by_username ? (
                  <div className="text-muted text-[12px]">
                    added by {member.invited_by_username}
                  </div>
                ) : null}
              </div>

              {canManage &&
              !member.is_owner &&
              member.user_id !== currentUser.id ? (
                <div className="flex items-center gap-1.5">
                  <select
                    aria-label={`Role for ${member.username}`}
                    value={member.role}
                    onChange={(event) =>
                      void changeRole(member, event.target.value as ProjectRole)
                    }
                    className="border-line bg-sunken text-ink h-8 rounded-lg border px-2 text-[12px] outline-none"
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
                    className="border-line text-muted hover:border-danger-line hover:text-danger rounded-lg border p-1.5 transition"
                  >
                    <Icon name="trash" size={12} />
                  </button>
                </div>
              ) : (
                <span
                  className={cx(
                    "rounded-full border px-2 py-0.5 text-[12px] capitalize",
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
                  "mt-0.5 w-20 shrink-0 rounded-full border px-2 py-0.5 text-center text-[12px] capitalize",
                  ROLE_TONE[entry.role],
                )}
              >
                {entry.role}
              </span>
              <span className="text-ink-3 text-[12.5px] leading-5">
                {entry.description}
              </span>
            </li>
          ))}
        </ul>
      </SectionPanel>
      <Modal
        open={adding}
        onClose={() => setAdding(false)}
        title="Add a person"
        description="They need an account on this platform already. This gives them access to this project."
        widthClassName="max-w-lg"
        footer={
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setAdding(false)}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={invite}
              disabled={busy || !username.trim()}
            >
              {busy ? "Adding…" : "Add to project"}
            </Button>
          </div>
        }
      >
        {error && adding ? (
          <p role="alert" className="text-danger mb-3 text-[13px]">
            {error}
          </p>
        ) : null}
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[200px] flex-1">
            <label
              htmlFor="member-username"
              className="text-ink mb-1.5 block text-[13px] font-medium"
            >
              Username
            </label>
            <input
              id="member-username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="analyst"
              className="border-line bg-sunken text-ink h-9 w-full rounded-lg border px-3 text-[13px] transition outline-none focus:border-[color:var(--accent)]"
            />
          </div>
          <div>
            <span className="text-ink mb-1.5 block text-[13px] font-medium">
              Role
            </span>
            <div className="border-line flex rounded-lg border p-0.5">
              {ROLE_ORDER.map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setRole(value)}
                  className={cx(
                    "rounded-md px-2.5 py-1.5 text-[13px] capitalize transition",
                    role === value
                      ? "text-accent-ink bg-[color:var(--accent)]"
                      : "text-ink-3 hover:text-ink",
                  )}
                >
                  {value}
                </button>
              ))}
            </div>
          </div>
        </div>

        {roles.length > 0 ? (
          <p className="text-ink-3 mt-3 text-[13px] leading-5">
            {roles.find((entry) => entry.role === role)?.description}
          </p>
        ) : null}
      </Modal>
    </AppShell>
  );
}
