"use client";

import { useMemo, useState } from "react";

import {
  Badge,
  Button,
  EmptyState,
  FormField,
  Icon,
  Input,
  Modal,
  SectionPanel,
  Select,
  StatTile,
} from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { ConfirmDeleteDialog } from "@/components/ui/confirm-delete-dialog";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { countOf, formatDate } from "@/lib/format";
import { sentenceLabel } from "@/lib/labels";

import { NetworkAccess } from "./network-access";
import type { AuthUser } from "@platform/shared-types";

export type Organisation = {
  id: string;
  name: string;
  slug: string;
  plan: string;
  max_projects: number | null;
  max_datasets: number | null;
  is_active: boolean;
  project_count: number;
  member_count: number;
  /** Addresses and ranges its people may connect from; empty means anywhere. */
  allowed_networks?: string[];
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
  const [renaming, setRenaming] = useState<Organisation | null>(null);
  const [renameValue, setRenameValue] = useState("");

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

  const renameOrganisation = async () => {
    if (!renaming) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await apiFetch<Organisation>(`/organisations/${renaming.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name: renameValue.trim() }),
      });
      applyCounts(updated);
      setRenaming(null);
      setFeedback(`Renamed to ${updated.name}.`);
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
        title="Organisations"
        subtitle="Separate groups of people and projects."
      >
        {restricted ? (
          <SectionPanel title="Organisations">
            <EmptyState title="Platform admins only" description={restricted} />
          </SectionPanel>
        ) : (
          <>
            <section className="grid gap-4 md:grid-cols-3">
              <StatTile
                label="Organisations"
                value={String(organisations.length)}
                caption="Separate groups on this server."
              />
              <StatTile
                label="Assigned members"
                value={String(totalMembers)}
                caption="Accounts in an organisation."
              />
              <StatTile
                label="Unassigned"
                value={String(unassigned.length)}
                caption="Accounts in none; they see only projects outside every organisation."
              />
            </section>

            <SectionPanel
              title="Your organisations"
              description="Removing someone from an organisation removes their access to its projects. Their project roles stay as they were."
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
                  description="You only need one to keep separate groups of people and projects apart. Until then, everyone shares one space."
                  action={<Button onClick={() => setCreating(true)}>New organisation</Button>}
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
                            <Badge>
                              {sentenceLabel(org.plan)}
                            </Badge>
                          </button>
                          <span className="text-[12px] text-muted">
                            {countOf(org.member_count, "member")} · {countOf(org.project_count, "project")} ·
                            created {formatDate(org.created_at)}
                          </span>
                          <button
                            type="button"
                            onClick={() => {
                              setRenaming(org);
                              setRenameValue(org.name);
                            }}
                            className="rounded-lg border border-line px-2.5 py-1 text-[12px] text-ink transition hover:bg-surface-2"
                          >
                            Rename
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
                                <span className="text-[12px] text-muted">Add somebody:</span>
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
                            <NetworkAccess
                              organisation={org}
                              onSaved={(updated) =>
                                setOrganisations((current) =>
                                  current.map((item) => (item.id === updated.id ? { ...item, ...updated } : item)),
                                )
                              }
                            />
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
        description="People and projects in it see each other; nobody outside does."
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
        open={renaming !== null}
        onClose={() => setRenaming(null)}
        title="Rename organisation"
        widthClassName="max-w-md"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setRenaming(null)}>Cancel</Button>
            <Button size="sm" onClick={() => void renameOrganisation()} disabled={busy || renameValue.trim().length < 2}>
              Save
            </Button>
          </div>
        }
      >
        <FormField label="Name" htmlFor="org-rename">
          <Input id="org-rename" value={renameValue} onChange={(e) => setRenameValue(e.target.value)} />
        </FormField>
      </Modal>

      <ConfirmDeleteDialog
        open={deleting !== null}
        name={deleting?.name ?? ""}
        kind="organisation"
        requireTypedName
        consequences={[
          "Not allowed while it still holds a project or member. Move them first.",
          "Anything left in it would point at an organisation that no longer exists, so it is refused rather than allowed.",
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
