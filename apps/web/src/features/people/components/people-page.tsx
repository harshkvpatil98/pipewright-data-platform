"use client";

import { useMemo, useState } from "react";

import { Button, EmptyState, Input, SectionPanel, StatCard } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { ConfirmDeleteDialog } from "@/components/ui/confirm-delete-dialog";
import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import type { AuthUser } from "@platform/shared-types";

type PeoplePageViewProps = {
  currentUser: AuthUser;
  users: AuthUser[];
};

const PLATFORM_ROLES = ["admin", "operator", "viewer"] as const;

/**
 * Platform accounts: who exists, what they may administer, and whether they
 * can still sign in.
 *
 * There was no screen for any of this. Accounts could only be created through
 * the API, and `is_active` -- checked on every login and every authenticated
 * request -- had nothing anywhere that could set it, so an account once issued
 * could never be withdrawn.
 *
 * Deactivating is the prominent action and deleting is not, because they are
 * not interchangeable: deactivating stops someone signing in while keeping
 * their name on the projects and runs they own, and the API refuses to delete
 * an account that still owns projects precisely to stop that history being
 * orphaned.
 */
export function PeoplePageView({ currentUser, users: initialUsers }: PeoplePageViewProps) {
  const [users, setUsers] = useState(initialUsers);
  const [query, setQuery] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<AuthUser | null>(null);

  const isPlatformAdmin = currentUser.role === "admin";

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return users;
    return users.filter((user) => user.username.toLowerCase().includes(needle));
  }, [users, query]);

  const activeCount = users.filter((user) => user.is_active).length;
  const adminCount = users.filter((user) => user.role === "admin" && user.is_active).length;

  const patch = async (user: AuthUser, body: Record<string, unknown>, note: string) => {
    setBusyId(user.id);
    setError(null);
    setFeedback(null);
    try {
      const updated = await apiFetch<AuthUser>(`/auth/users/${user.id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      setUsers((current) => current.map((row) => (row.id === user.id ? updated : row)));
      setFeedback(note);
    } catch (caught) {
      // The refusals here are the useful part -- "this is the only active
      // admin", "you cannot change your own account" -- so they are shown as
      // the server wrote them.
      setError(extractErrorMessage(caught));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <>
      <AppShell
        currentUser={currentUser}
        eyebrow="Platform administration"
        title="People"
        subtitle="Everyone with an account on this platform, what they may administer, and whether they can still sign in."
        meta={
          <span className="rounded-full border border-line bg-surface px-3 py-1 text-xs uppercase tracking-[0.18em] text-ink-2">
            {isPlatformAdmin ? "Signed in as a platform admin" : "Read only — platform admins can make changes"}
          </span>
        }
      >
        <section className="grid gap-4 md:grid-cols-3">
          <StatCard label="Accounts" value={String(users.length)} caption="Everyone who has ever been given access." />
          <StatCard label="Active" value={String(activeCount)} caption="Accounts that can sign in right now." />
          <StatCard
            label="Platform admins"
            value={String(adminCount)}
            caption="The last active admin cannot be deactivated, demoted or deleted."
          />
        </section>

        <SectionPanel
          title="Accounts"
          description="Deactivating keeps someone's name on the projects and runs they own; deleting is refused while they still own any."
          actions={
            <div className="w-full min-w-[220px] lg:w-[280px]">
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search by username"
                aria-label="Search accounts by username"
              />
            </div>
          }
        >
          {feedback ? <p className="mb-3 text-sm text-accent">{feedback}</p> : null}
          {error ? (
            <p role="alert" className="mb-3 rounded-2xl border border-danger-line bg-sunken px-4 py-3 text-sm text-danger">
              {error}
            </p>
          ) : null}

          {filtered.length === 0 ? (
            <EmptyState
              title={users.length === 0 ? "No accounts" : "No matching accounts"}
              description="Accounts are created by a platform admin."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-left text-sm">
                <thead className="text-[11px] uppercase tracking-[0.16em] text-muted">
                  <tr className="border-b border-line">
                    <th className="py-2 pr-4">Username</th>
                    <th className="py-2 pr-4">Platform role</th>
                    <th className="py-2 pr-4">Status</th>
                    <th className="py-2 pr-4">Created</th>
                    <th className="py-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((user) => {
                    const isSelf = user.id === currentUser.id;
                    const busy = busyId === user.id;
                    return (
                      <tr key={user.id} className="border-b border-line">
                        <td className="py-3 pr-4 font-medium text-ink">
                          {user.username}
                          {isSelf ? <span className="ml-2 text-[11px] text-muted">(you)</span> : null}
                        </td>
                        <td className="py-3 pr-4">
                          <select
                            value={user.role}
                            aria-label={`Platform role for ${user.username}`}
                            disabled={!isPlatformAdmin || isSelf || busy}
                            onChange={(event) =>
                              void patch(
                                user,
                                { role: event.target.value },
                                `${user.username} is now ${event.target.value}.`,
                              )
                            }
                            className="h-8 rounded-lg border border-line bg-sunken px-2 text-[12px] text-ink outline-none disabled:opacity-50"
                          >
                            {PLATFORM_ROLES.map((role) => (
                              <option key={role} value={role}>
                                {role}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="py-3 pr-4">
                          <span
                            className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] ${
                              user.is_active
                                ? "border-success-line bg-success-soft text-success"
                                : "border-line bg-surface-2 text-ink-2"
                            }`}
                          >
                            {user.is_active ? "Active" : "Deactivated"}
                          </span>
                        </td>
                        <td className="py-3 pr-4 text-xs text-ink-3">{formatDate(user.created_at)}</td>
                        <td className="py-3">
                          <div className="flex flex-wrap justify-end gap-2">
                            <Button
                              variant="secondary"
                              size="sm"
                              disabled={!isPlatformAdmin || isSelf || busy}
                              onClick={() =>
                                void patch(
                                  user,
                                  { is_active: !user.is_active },
                                  user.is_active
                                    ? `${user.username} can no longer sign in.`
                                    : `${user.username} can sign in again.`,
                                )
                              }
                            >
                              {busy ? "Saving…" : user.is_active ? "Deactivate" : "Reactivate"}
                            </Button>
                            <button
                              type="button"
                              disabled={!isPlatformAdmin || isSelf || busy}
                              onClick={() => setDeleting(user)}
                              aria-label={`Delete ${user.username}`}
                              className="rounded-lg border border-line p-1.5 text-muted transition hover:border-danger-line hover:text-danger disabled:opacity-40 disabled:hover:border-line disabled:hover:text-muted"
                            >
                              <Icon name="trash" size={12} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </SectionPanel>
      </AppShell>

      <ConfirmDeleteDialog
        open={deleting !== null}
        name={deleting?.username ?? ""}
        kind="account"
        requireTypedName
        consequences={[
          "Deactivating is usually the better answer — it keeps their name on the projects and runs they own.",
          "Deleting is refused while they still own any project, because a project with no owner is reachable by nobody.",
        ]}
        confirmLabel="Delete account"
        onConfirm={() => apiFetch(`/auth/users/${deleting?.id}`, { method: "DELETE" })}
        onDeleted={() => {
          setUsers((current) => current.filter((row) => row.id !== deleting?.id));
          setFeedback(`${deleting?.username} was deleted.`);
        }}
        onClose={() => setDeleting(null)}
      />
    </>
  );
}
