"use client";

import { useMemo, useState } from "react";

import {
  Button,
  EmptyState,
  FormField,
  Icon,
  Input,
  Modal,
  SectionPanel,
  Select,
  StatTile,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { ConfirmDeleteDialog } from "@/components/ui/confirm-delete-dialog";
import { OneTimeCodeModal } from "@/components/ui/one-time-code-modal";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import type { AuthUser, OneTimeCode } from "@platform/shared-types";

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
  const [codeResult, setCodeResult] = useState<OneTimeCode | null>(null);
  const [inviting, setInviting] = useState(false);
  const [inviteName, setInviteName] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("viewer");
  const [inviteError, setInviteError] = useState<string | null>(null);

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

  const invite = async () => {
    setInviteError(null);
    try {
      const result = await apiFetch<OneTimeCode>("/auth/invite", {
        method: "POST",
        body: JSON.stringify({
          username: inviteName.trim(),
          email: inviteEmail.trim() || null,
          role: inviteRole,
        }),
      });
      setInviting(false);
      setInviteName("");
      setInviteEmail("");
      setInviteRole("viewer");
      setCodeResult(result);
      // The new account exists immediately, though inactive until activated.
      setUsers((current) => [
        {
          id: result.user_id,
          username: result.username,
          role: inviteRole,
          is_active: false,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        } as AuthUser,
        ...current,
      ]);
    } catch (caught) {
      setInviteError(extractErrorMessage(caught));
    }
  };

  const generateResetCode = async (user: AuthUser) => {
    setBusyId(user.id);
    setError(null);
    try {
      const result = await apiFetch<OneTimeCode>(`/auth/users/${user.id}/reset-code`, {
        method: "POST",
      });
      setCodeResult(result);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <>
      <AppShell
        currentUser={currentUser}
        title="Accounts"
        subtitle="Everyone who can sign in to this platform: invite, reset and deactivate."
        meta={
          <span className="rounded-full border border-line bg-surface px-3 py-1 text-[13px] text-ink-2">
            {isPlatformAdmin ? "You can make changes here" : "Read only: platform administrators can make changes"}
          </span>
        }
      >
        <section className="grid gap-4 md:grid-cols-3">
          <StatTile label="Accounts" value={String(users.length)} caption="Everyone who has ever been given access." />
          <StatTile label="Active" value={String(activeCount)} caption="Accounts that can sign in right now." />
          <StatTile
            label="Platform admins"
            value={String(adminCount)}
            caption="The last active admin cannot be deactivated, demoted or deleted."
          />
        </section>

        <SectionPanel
          title="Accounts"
          description="Deactivating keeps someone's name on the projects and runs they own; deleting is refused while they still own any."
          actions={
            <div className="flex w-full items-center gap-2 lg:w-auto">
              <div className="min-w-[200px] flex-1 lg:w-[260px]">
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search by username"
                  aria-label="Search accounts by username"
                />
              </div>
              {isPlatformAdmin ? (
                <Button onClick={() => setInviting(true)}>Invite person</Button>
              ) : null}
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
              description={
                users.length === 0
                  ? "Accounts are created by a platform admin."
                  : "No account matches that search."
              }
              action={
                users.length === 0 ? undefined : (
                  <Button variant="secondary" size="sm" onClick={() => setQuery("")}>
                    Clear search
                  </Button>
                )
              }
            />
          ) : (
            <Table minWidth={720}>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Username</TableHeaderCell>
                  <TableHeaderCell>Platform role</TableHeaderCell>
                  <TableHeaderCell>Status</TableHeaderCell>
                  <TableHeaderCell>Created</TableHeaderCell>
                  <TableHeaderCell className="text-right">Actions</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {filtered.map((user) => {
                  const isSelf = user.id === currentUser.id;
                  const busy = busyId === user.id;
                  return (
                    <TableRow key={user.id}>
                      <TableCell className="font-medium text-ink">
                        {user.display_name || user.username}
                        {user.display_name ? (
                          <span className="ml-2 text-[12px] text-muted">{user.username}</span>
                        ) : null}
                        {isSelf ? <span className="ml-2 text-[12px] text-muted">(you)</span> : null}
                      </TableCell>
                      <TableCell>
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
                      </TableCell>
                      <TableCell>
                        <span
                          className={`rounded-full border px-2.5 py-1 text-[12px] font-semibold ${
                            user.is_active
                              ? "border-success-line bg-success-soft text-success"
                              : "border-line bg-surface-2 text-ink-2"
                          }`}
                        >
                          {user.is_active ? "Active" : "Deactivated"}
                        </span>
                      </TableCell>
                      <TableCell className="text-xs text-ink-3">{formatDate(user.created_at)}</TableCell>
                      <TableCell>
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
                          <Button
                            variant="secondary"
                            size="sm"
                            disabled={!isPlatformAdmin || busy}
                            onClick={() => void generateResetCode(user)}
                          >
                            Reset code
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
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </SectionPanel>
      </AppShell>

      <Modal
        open={inviting}
        onClose={() => setInviting(false)}
        title="Invite a person"
        description="They get an account immediately, but cannot sign in until they set a password with the one-time code you will receive."
        widthClassName="max-w-md"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setInviting(false)}>
              Cancel
            </Button>
            <Button size="sm" onClick={() => void invite()} disabled={inviteName.trim().length < 3}>
              Send invitation
            </Button>
          </div>
        }
      >
        <div className="space-y-3">
          <FormField label="Username" htmlFor="invite-username">
            <Input
              id="invite-username"
              value={inviteName}
              onChange={(e) => setInviteName(e.target.value)}
              placeholder="jordan"
            />
          </FormField>
          <FormField label="Email (optional)" htmlFor="invite-email">
            <Input
              id="invite-email"
              type="email"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder="jordan@company.com"
            />
          </FormField>
          <FormField label="Platform role" htmlFor="invite-role">
            <Select id="invite-role" value={inviteRole} onChange={(e) => setInviteRole(e.target.value)}>
              <option value="viewer">Viewer</option>
              <option value="operator">Operator</option>
              <option value="admin">Admin</option>
            </Select>
          </FormField>
          {inviteError ? <p role="alert" className="text-[12px] text-danger">{inviteError}</p> : null}
        </div>
      </Modal>

      <OneTimeCodeModal code={codeResult} onClose={() => setCodeResult(null)} />

      <ConfirmDeleteDialog
        open={deleting !== null}
        name={deleting?.username ?? ""}
        kind="account"
        requireTypedName
        consequences={[
          "Deactivating is usually better. It keeps their name on the projects and runs they own.",
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
