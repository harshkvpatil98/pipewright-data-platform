"use client";

import { useMemo, useState } from "react";

import { Button, EmptyState, FormField, Input, Modal, SectionPanel, Select, StatCard } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { ConfirmDeleteDialog } from "@/components/ui/confirm-delete-dialog";
import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { MAX_SESSION_MINUTES, MIN_SESSION_MINUTES } from "@platform/shared-types";
import {
  isSessionMinutesValid,
  sessionMinutesInput,
  sessionMinutesPayload,
} from "@/features/organisations/session-policy";
import type { AuthUser } from "@platform/shared-types";

export type Organisation = {
  id: string;
  name: string;
  slug: string;
  plan: string;
  max_projects: number | null;
  max_datasets: number | null;
  session_max_minutes: number | null;
  is_active: boolean;
  project_count: number;
  member_count: number;
  created_at: string;
};

type OrganisationsPageViewProps = {
  currentUser: AuthUser;
  organisations: Organisation[];
  users: AuthUser[];
  /** Set when the API refused the listing, which it does for non-admins. */
  restricted?: string | null;
};

/**
 * Tenants: who is in one, and how to take them back out.
 *
 * Membership was append-only in the API and invisible in the product. Nothing
 * here called `/organisations` at all, so an offboarded colleague kept reaching
 * every project in their tenant and the only way to stop it was a terminal.
 *
 * Projects in an organisation are counted but not listed: `/projects` answers
 * with the caller's own projects, not the tenant's, and inventing a
 * cross-tenant listing to fill a table would widen what an admin can see
 * rather than fix what they can do.
 */
export function OrganisationsPageView({
  currentUser,
  organisations: initialOrganisations,
  users: initialUsers,
  restricted,
}: OrganisationsPageViewProps) {
  const [organisations, setOrganisations] = useState(initialOrganisations);
  const [users, setUsers] = useState(initialUsers);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Organisation | null>(null);
  const [assigning, setAssigning] = useState<string>("");
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [editing, setEditing] = useState<Organisation | null>(null);
  const [nameValue, setNameValue] = useState("");
  // "" means "follow the deployment default" -- the same thing null means
  // in the database. A tenant that never set a policy must not acquire one
  // just because somebody opened this dialog.
  const [sessionValue, setSessionValue] = useState("");

  const membersByOrg = useMemo(() => {
    const map = new Map<string, AuthUser[]>();
    for (const user of users) {
      const org = (user as AuthUser & { organisation_id?: string | null }).organisation_id;
      if (!org) continue;
      map.set(org, [...(map.get(org) ?? []), user]);
    }
    return map;
  }, [users]);

  const unassigned = useMemo(
    () =>
      users.filter(
        (user) => !(user as AuthUser & { organisation_id?: string | null }).organisation_id,
      ),
    [users],
  );

  const sessionValid = isSessionMinutesValid(sessionValue);
  const settingsValid = nameValue.trim().length >= 2 && sessionValid;

  const setOrganisationOf = (userId: string, organisationId: string | null) =>
    setUsers((current) =>
      current.map((user) =>
        user.id === userId ? { ...user, organisation_id: organisationId } : user,
      ),
    );

  const applyCounts = (updated: Organisation) =>
    setOrganisations((current) =>
      current.map((org) => (org.id === updated.id ? updated : org)),
    );

  const createOrganisation = async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await apiFetch<Organisation>("/organisations", {
        method: "POST",
        body: JSON.stringify({ name: newName.trim() }),
      });
      setOrganisations((current) => [created, ...current]);
      setCreating(false);
      setNewName("");
      setFeedback(`${created.name} created.`);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const saveOrganisation = async () => {
    if (!editing) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await apiFetch<Organisation>(`/organisations/${editing.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: nameValue.trim(),
          session_max_minutes: sessionMinutesPayload(sessionValue),
        }),
      });
      applyCounts(updated);
      setEditing(null);
      setFeedback(
        updated.session_max_minutes === null
          ? `Saved ${updated.name}. Sessions follow the deployment default.`
          : `Saved ${updated.name}. Sessions last ${updated.session_max_minutes} minutes.`,
      );
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (organisationId: string, user: AuthUser) => {
    setBusy(true);
    setError(null);
    setFeedback(null);
    try {
      const updated = await apiFetch<Organisation>(
        `/organisations/${organisationId}/users/${user.id}`,
        { method: "DELETE" },
      );
      applyCounts(updated);
      setOrganisationOf(user.id, null);
      setFeedback(`${user.username} no longer belongs to ${updated.name}.`);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const assign = async (organisationId: string, userId: string) => {
    if (!userId) return;
    setBusy(true);
    setError(null);
    setFeedback(null);
    try {
      const updated = await apiFetch<Organisation>(
        `/organisations/${organisationId}/users/${userId}`,
        { method: "POST" },
      );
      applyCounts(updated);
      setOrganisationOf(userId, organisationId);
      setAssigning("");
      setFeedback(`Added to ${updated.name}.`);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const totalMembers = users.filter(
    (user) => (user as AuthUser & { organisation_id?: string | null }).organisation_id,
  ).length;

  return (
    <>
      <AppShell
        currentUser={currentUser}
        eyebrow="Platform administration"
        title="Organisations"
        subtitle="Tenants, who belongs to them, and how to revoke that membership. A user with no organisation stops matching every project that has one."
      >
        {restricted ? (
          <SectionPanel title="Organisations" description="Tenant administration.">
            <EmptyState title="Platform admins only" description={restricted} />
          </SectionPanel>
        ) : (
          <>
            <section className="grid gap-4 md:grid-cols-3">
              <StatCard
                label="Organisations"
                value={String(organisations.length)}
                caption="Tenant boundaries on this platform."
              />
              <StatCard
                label="Assigned members"
                value={String(totalMembers)}
                caption="Accounts that belong to a tenant."
              />
              <StatCard
                label="Unassigned"
                value={String(unassigned.length)}
                caption="Accounts in no tenant; they see only tenant-less projects."
              />
            </section>

            <SectionPanel
              title="Tenants"
              description="Removing somebody from an organisation cuts their access to every project in it, without touching any project membership row."
              actions={<Button onClick={() => setCreating(true)}>New organisation</Button>}
            >
              {feedback ? <p className="mb-3 text-sm text-accent">{feedback}</p> : null}
              {error ? (
                <p
                  role="alert"
                  className="mb-3 rounded-2xl border border-danger-line bg-sunken px-4 py-3 text-sm text-danger"
                >
                  {error}
                </p>
              ) : null}

              {organisations.length === 0 ? (
                <EmptyState
                  title="No organisations"
                  description="A single-tenant install needs none; projects and users simply belong to no organisation."
                />
              ) : (
                <ul className="space-y-3">
                  {organisations.map((org) => {
                    const members = membersByOrg.get(org.id) ?? [];
                    const open = expanded === org.id;
                    return (
                      <li
                        key={org.id}
                        className="rounded-xl border border-line bg-surface px-4 py-3"
                      >
                        <div className="flex flex-wrap items-center gap-3">
                          <button
                            type="button"
                            onClick={() => setExpanded(open ? null : org.id)}
                            aria-expanded={open}
                            className="flex min-w-0 flex-1 items-center gap-2 text-left"
                          >
                            <Icon name={open ? "chevronDown" : "chevronRight"} size={14} />
                            <span className="truncate text-[13.5px] font-medium text-ink">
                              {org.name}
                            </span>
                            <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] uppercase text-ink-3">
                              {org.plan}
                            </span>
                          </button>
                          <span className="text-[11.5px] text-muted">
                            {org.member_count} member(s) · {org.project_count} project(s) ·
                            sessions{" "}
                            {org.session_max_minutes === null
                              ? "default"
                              : `${org.session_max_minutes} min`}{" "}
                            · created {formatDate(org.created_at)}
                          </span>
                          <button
                            type="button"
                            onClick={() => {
                              setEditing(org);
                              setNameValue(org.name);
                              setSessionValue(sessionMinutesInput(org.session_max_minutes));
                            }}
                            className="rounded-lg border border-line px-2.5 py-1 text-[12px] text-ink transition hover:bg-surface-2"
                          >
                            Settings
                          </button>
                          <button
                            type="button"
                            onClick={() => setDeleting(org)}
                            aria-label={`Delete ${org.name}`}
                            className="rounded-lg border border-line p-1.5 text-muted transition hover:border-danger-line hover:text-danger"
                          >
                            <Icon name="trash" size={12} />
                          </button>
                        </div>

                        {open ? (
                          <div className="mt-3 border-t border-line pt-3">
                            {members.length === 0 ? (
                              <p className="text-[12.5px] text-muted">
                                Nobody belongs to this organisation.
                              </p>
                            ) : (
                              <ul className="space-y-1.5">
                                {members.map((member) => (
                                  <li
                                    key={member.id}
                                    className="flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 hover:bg-sunken"
                                  >
                                    <span className="text-[12.5px] text-ink">
                                      {member.username}
                                    </span>
                                    <Button
                                      variant="secondary"
                                      size="sm"
                                      disabled={busy}
                                      onClick={() => void revoke(org.id, member)}
                                    >
                                      Remove from organisation
                                    </Button>
                                  </li>
                                ))}
                              </ul>
                            )}

                            {unassigned.length > 0 ? (
                              <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
                                <span className="text-[11.5px] text-muted">Add somebody:</span>
                                <Select
                                  value={assigning}
                                  aria-label={`Add a user to ${org.name}`}
                                  onChange={(event) => setAssigning(event.target.value)}
                                  className="h-8 w-auto text-xs"
                                >
                                  <option value="">Choose an account…</option>
                                  {unassigned.map((user) => (
                                    <option key={user.id} value={user.id}>
                                      {user.username}
                                    </option>
                                  ))}
                                </Select>
                                <Button
                                  size="sm"
                                  disabled={!assigning || busy}
                                  onClick={() => void assign(org.id, assigning)}
                                >
                                  Add
                                </Button>
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              )}
            </SectionPanel>
          </>
        )}
      </AppShell>

      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title="New organisation"
        description="A tenant boundary. Projects and people assigned to it see each other; nobody outside does."
        widthClassName="max-w-md"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setCreating(false)}>Cancel</Button>
            <Button size="sm" onClick={() => void createOrganisation()} disabled={busy || newName.trim().length < 2}>
              Create
            </Button>
          </div>
        }
      >
        <FormField label="Name" htmlFor="org-name">
          <Input id="org-name" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Acme Corp" />
        </FormField>
      </Modal>

      <Modal
        open={editing !== null}
        onClose={() => setEditing(null)}
        title="Organisation settings"
        widthClassName="max-w-md"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setEditing(null)}>Cancel</Button>
            <Button size="sm" onClick={() => void saveOrganisation()} disabled={busy || !settingsValid}>
              Save
            </Button>
          </div>
        }
      >
        <div className="space-y-4">
          <FormField label="Name" htmlFor="org-rename">
            <Input id="org-rename" value={nameValue} onChange={(e) => setNameValue(e.target.value)} />
          </FormField>
          <FormField label="Session length (minutes)" htmlFor="org-session">
            <Input
              id="org-session"
              type="number"
              min={MIN_SESSION_MINUTES}
              max={MAX_SESSION_MINUTES}
              value={sessionValue}
              onChange={(e) => setSessionValue(e.target.value)}
              placeholder="Deployment default"
            />
          </FormField>
          {sessionValid ? null : (
            <p className="text-[11.5px] text-danger">
              Enter a whole number of minutes between {MIN_SESSION_MINUTES} and{" "}
              {MAX_SESSION_MINUTES}, or leave it empty for the deployment default.
            </p>
          )}
          <p className="text-[11.5px] text-muted">
            How long a session lasts for this tenant&apos;s people, however they sign in.
            Leave it empty to follow the deployment default. It applies from the next
            sign-in — a session already issued carries its own expiry, and ending those
            now is what sign-out-everywhere does.
          </p>
        </div>
      </Modal>

      <ConfirmDeleteDialog
        open={deleting !== null}
        name={deleting?.name ?? ""}
        kind="organisation"
        requireTypedName
        consequences={[
          "Refused while it still holds any project or member — move them first.",
          "Nothing in the database enforces this: `organisation_id` has no foreign key, so leftover rows would point at a tenant that no longer exists and match nothing.",
        ]}
        confirmLabel="Delete organisation"
        onConfirm={() => apiFetch(`/organisations/${deleting?.id}`, { method: "DELETE" })}
        onDeleted={() => {
          setOrganisations((current) => current.filter((org) => org.id !== deleting?.id));
          setFeedback(`${deleting?.name} was deleted.`);
        }}
        onClose={() => setDeleting(null)}
      />
    </>
  );
}
