"use client";

import Link from "next/link";
import { useState } from "react";

import { Button, EmptyState, FormField, Input, SectionPanel, StatCard, Textarea } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { ConfirmDeleteDialog } from "@/components/ui/confirm-delete-dialog";
import { Icon } from "@/components/ui/icon";
import { Modal } from "@/components/ui/modal";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import type { AuthUser, Dashboard, SavedChart } from "@platform/shared-types";

type DashboardsPageViewProps = {
  currentUser: AuthUser;
  projectId: string;
  dashboards: Dashboard[];
  charts: SavedChart[];
};

/**
 * Dashboards: what exists, what is on each one, and how to remove them.
 *
 * The route existed as an empty directory. The API could list, create, rename,
 * share, unshare and delete a dashboard, and none of it was reachable from the
 * product -- so a dashboard could only be made with curl and could never be
 * removed by anyone using Pipewright.
 *
 * Sharing is now real end to end. "Share" mints a token and copies the public
 * link (`/shared/dashboards/{token}`), which the unauthenticated viewer route
 * turns back into a read-only render of the dashboard. "Copy link" hands the
 * link out again; "Revoke share" nulls the token so the link stops working
 * immediately. A token is minted on request, never by default -- a dashboard
 * shareable by default is one shared by accident.
 */
export function DashboardsPageView({
  currentUser,
  projectId,
  dashboards: initialDashboards,
  charts,
}: DashboardsPageViewProps) {
  const [dashboards, setDashboards] = useState(initialDashboards);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Dashboard | null>(null);
  const [deleting, setDeleting] = useState<Dashboard | null>(null);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [tileIds, setTileIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const resetForm = () => {
    setName("");
    setDescription("");
    setTileIds([]);
    setError(null);
  };

  const openCreate = () => {
    resetForm();
    setCreating(true);
  };

  const openEdit = (dashboard: Dashboard) => {
    setName(dashboard.name);
    setDescription(dashboard.description ?? "");
    setTileIds([]);
    setError(null);
    setEditing(dashboard);
  };

  const toggleTile = (chartId: string) =>
    setTileIds((current) =>
      current.includes(chartId)
        ? current.filter((id) => id !== chartId)
        : [...current, chartId],
    );

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await apiFetch<Dashboard>(`/projects/${projectId}/dashboards`, {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          description: description.trim() ? description.trim() : null,
          // Position follows the order they were picked in; the API treats
          // null as "wherever it lands", which would lose that order.
          tiles: tileIds.map((chartId, index) => ({ chart_id: chartId, position: index })),
        }),
      });
      setDashboards((current) => [created, ...current]);
      setCreating(false);
      setFeedback(`${created.name} created.`);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!editing) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await apiFetch<Dashboard>(
        `/projects/${projectId}/dashboards/${editing.id}`,
        {
          method: "PATCH",
          // Tiles are deliberately not sent: this form edits the label, and
          // sending an empty list would clear every tile on the dashboard.
          body: JSON.stringify({
            name: name.trim(),
            description: description.trim() ? description.trim() : null,
          }),
        },
      );
      setDashboards((current) =>
        current.map((row) => (row.id === updated.id ? { ...row, ...updated } : row)),
      );
      setEditing(null);
      setFeedback(`${updated.name} updated.`);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const shareLink = (token: string) =>
    typeof window === "undefined" ? "" : `${window.location.origin}/shared/dashboards/${token}`;

  const copyLink = async (token: string) => {
    const url = shareLink(token);
    try {
      await navigator.clipboard.writeText(url);
      setFeedback("Share link copied to your clipboard.");
    } catch {
      // Clipboard can be blocked (insecure origin, permissions); show the link
      // so it can still be copied by hand rather than failing silently.
      setError(`Copy this link manually: ${url}`);
    }
  };

  const shareDashboard = async (dashboard: Dashboard) => {
    setBusy(true);
    setError(null);
    try {
      const updated = await apiFetch<Dashboard>(
        `/projects/${projectId}/dashboards/${dashboard.id}/share`,
        { method: "POST" },
      );
      setDashboards((current) =>
        current.map((row) => (row.id === updated.id ? { ...row, ...updated } : row)),
      );
      if (updated.share_token) {
        await copyLink(updated.share_token);
        setFeedback(`${updated.name} is now shared — link copied to your clipboard.`);
      }
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const revokeShare = async (dashboard: Dashboard) => {
    setBusy(true);
    setError(null);
    try {
      const updated = await apiFetch<Dashboard>(
        `/projects/${projectId}/dashboards/${dashboard.id}/share`,
        { method: "DELETE" },
      );
      setDashboards((current) =>
        current.map((row) => (row.id === updated.id ? { ...row, ...updated } : row)),
      );
      setFeedback(`${updated.name} is no longer shared.`);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const sharedCount = dashboards.filter((row) => row.share_token !== null).length;
  const totalTiles = dashboards.reduce((sum, row) => sum + row.tile_count, 0);

  return (
    <>
      <AppShell
        currentUser={currentUser}
        eyebrow="Reporting"
        title="Dashboards"
        subtitle="Saved charts arranged on a page. Build the charts first, then group the ones that belong together; open a dashboard to arrange, filter and share it."
        actions={
          <Button onClick={openCreate} disabled={charts.length === 0}>
            New dashboard
          </Button>
        }
      >
        <section className="grid gap-4 md:grid-cols-3">
          <StatCard
            label="Dashboards"
            value={String(dashboards.length)}
            caption="Saved arrangements in this project."
          />
          <StatCard label="Tiles" value={String(totalTiles)} caption="Charts placed across them." />
          <StatCard
            label="Shared"
            value={String(sharedCount)}
            caption="Dashboards holding a share token."
          />
        </section>

        <SectionPanel
          title="Saved dashboards"
          description="Deleting one removes its tiles; the charts themselves are not touched and stay in the chart builder."
        >
          {feedback ? <p className="mb-3 text-sm text-accent">{feedback}</p> : null}
          {error && !creating && !editing ? (
            <p
              role="alert"
              className="mb-3 rounded-2xl border border-danger-line bg-sunken px-4 py-3 text-sm text-danger"
            >
              {error}
            </p>
          ) : null}

          {charts.length === 0 ? (
            <EmptyState
              title="No charts to arrange yet"
              description="A dashboard is a group of saved charts, so there has to be at least one before this is useful."
              action={
                <Link href={`/projects/${projectId}/charts`}>
                  <Button>Open the chart builder</Button>
                </Link>
              }
            />
          ) : dashboards.length === 0 ? (
            <EmptyState
              title="No dashboards yet"
              description="Group the charts that answer one question into a single page."
              action={<Button onClick={openCreate}>New dashboard</Button>}
            />
          ) : (
            <ul className="space-y-2">
              {dashboards.map((dashboard) => (
                <li
                  key={dashboard.id}
                  className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface px-3.5 py-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Link
                        href={`/projects/${projectId}/dashboards/${dashboard.id}`}
                        className="text-[13.5px] font-medium text-ink hover:text-accent"
                      >
                        {dashboard.name}
                      </Link>
                      <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] uppercase text-ink-3">
                        {dashboard.tile_count} tile{dashboard.tile_count === 1 ? "" : "s"}
                      </span>
                      {dashboard.share_token ? (
                        <span className="rounded-full border border-warning-line bg-warning-soft px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] text-warning">
                          Shared
                        </span>
                      ) : null}
                    </div>
                    <div className="mt-0.5 truncate text-[11.5px] text-muted">
                      {dashboard.description ?? "No description."} · updated{" "}
                      {formatDate(dashboard.updated_at)}
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <Link
                      href={`/projects/${projectId}/dashboards/${dashboard.id}`}
                      className="rounded-full bg-[color:var(--accent)] px-3 py-1.5 text-[11px] font-medium uppercase tracking-[0.14em] text-accent-ink"
                    >
                      Open
                    </Link>
                    {dashboard.share_token ? (
                      <>
                        <Button
                          variant="secondary"
                          size="sm"
                          disabled={busy}
                          onClick={() => void copyLink(dashboard.share_token as string)}
                        >
                          Copy link
                        </Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          disabled={busy}
                          onClick={() => void revokeShare(dashboard)}
                        >
                          Revoke share
                        </Button>
                      </>
                    ) : (
                      <Button
                        size="sm"
                        disabled={busy}
                        onClick={() => void shareDashboard(dashboard)}
                      >
                        Share
                      </Button>
                    )}
                    <Button variant="secondary" size="sm" onClick={() => openEdit(dashboard)}>
                      Rename
                    </Button>
                    <button
                      type="button"
                      onClick={() => setDeleting(dashboard)}
                      aria-label={`Delete ${dashboard.name}`}
                      className="rounded-lg border border-line p-1.5 text-muted transition hover:border-danger-line hover:text-danger"
                    >
                      <Icon name="trash" size={12} />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </SectionPanel>
      </AppShell>

      <Modal
        open={creating}
        title="New dashboard"
        description="Pick the charts that belong together. They are placed in the order you choose them."
        onClose={() => setCreating(false)}
      >
        <div className="space-y-4">
          <FormField label="Name" htmlFor="dashboard-name">
            <Input
              id="dashboard-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Revenue overview"
            />
          </FormField>
          <FormField label="Description" htmlFor="dashboard-description">
            <Textarea
              id="dashboard-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              rows={2}
              placeholder="What question this page answers."
            />
          </FormField>

          <div className="space-y-1.5">
            <span className="text-[12px] text-ink-3">
              Charts ({tileIds.length} selected)
            </span>
            <ul className="max-h-56 space-y-1 overflow-y-auto rounded-xl border border-line bg-sunken p-2">
              {charts.map((chart) => (
                <li key={chart.id}>
                  <label className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-[12.5px] text-ink hover:bg-surface">
                    <input
                      type="checkbox"
                      checked={tileIds.includes(chart.id)}
                      onChange={() => toggleTile(chart.id)}
                    />
                    <span className="truncate">{chart.name}</span>
                    <span className="ml-auto shrink-0 text-[10.5px] capitalize text-muted">
                      {chart.chart_type}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </div>

          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}

          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setCreating(false)} disabled={busy}>
              Cancel
            </Button>
            <Button size="sm" onClick={() => void create()} disabled={busy || !name.trim()}>
              {busy ? "Creating…" : "Create dashboard"}
            </Button>
          </div>
        </div>
      </Modal>

      <Modal
        open={editing !== null}
        title="Rename dashboard"
        description="Changes the label only — the tiles on it are left exactly as they are."
        onClose={() => setEditing(null)}
        widthClassName="max-w-md"
      >
        <div className="space-y-4">
          <FormField label="Name" htmlFor="dashboard-rename">
            <Input
              id="dashboard-rename"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </FormField>
          <FormField label="Description" htmlFor="dashboard-redescribe">
            <Textarea
              id="dashboard-redescribe"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              rows={2}
            />
          </FormField>

          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}

          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setEditing(null)} disabled={busy}>
              Cancel
            </Button>
            <Button size="sm" onClick={() => void save()} disabled={busy || !name.trim()}>
              {busy ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>
      </Modal>

      <ConfirmDeleteDialog
        open={deleting !== null}
        name={deleting?.name ?? ""}
        kind="dashboard"
        consequences={[
          `Its ${deleting?.tile_count ?? 0} tile(s) go with it. The charts themselves stay in the chart builder.`,
          ...(deleting?.share_token
            ? ["It is currently shared, so the share token stops working too."]
            : []),
        ]}
        onConfirm={() => apiFetch(`/projects/${projectId}/dashboards/${deleting?.id}`, { method: "DELETE" })}
        onDeleted={() => {
          setDashboards((current) => current.filter((row) => row.id !== deleting?.id));
          setFeedback(`${deleting?.name} was deleted.`);
        }}
        onClose={() => setDeleting(null)}
      />
    </>
  );
}
