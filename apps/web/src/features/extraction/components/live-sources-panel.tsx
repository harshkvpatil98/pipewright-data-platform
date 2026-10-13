"use client";

import Link from "next/link";
import { useCallback, useState } from "react";

import type {
  ExtractionConnection,
  StreamEvent,
  StreamMaterialiseResponse,
  StreamPollResponse,
  StreamSource,
  StreamSourceCreated,
} from "@platform/shared-types";
import { Badge, Button, FormField, Input, Modal, SectionPanel, Select } from "@platform/shared-ui";

import { DeleteRowButton } from "@/components/ui/delete-row-button";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { appConfig } from "@/lib/config";
import { formatDateTime } from "@/lib/format";
import { cx } from "@/lib/utils";

type LiveSourcesPanelProps = {
  projectId: string;
  connections: ExtractionConnection[];
  initial: StreamSource[];
};

/**
 * Sources that deliver rows instead of being polled for them (Phase 20, the
 * honest first slice): a webhook endpoint whose posts are stored as events,
 * and PostgreSQL change data capture through a logical replication slot,
 * read in micro-batches by the ticker. Either materialises into one
 * append-only dataset -- a new immutable version each time -- so history,
 * diff and AS OF apply to a stream exactly as to an upload.
 */
export function LiveSourcesPanel({ projectId, connections, initial }: LiveSourcesPanelProps) {
  const [sources, setSources] = useState(initial);
  const [kind, setKind] = useState<"webhook" | "postgres_cdc">("webhook");
  const [name, setName] = useState("");
  const [connectionId, setConnectionId] = useState(
    connections.find((connection) => connection.connector_type === "postgresql")?.id ?? "",
  );
  const [tables, setTables] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [secret, setSecret] = useState<StreamSourceCreated | null>(null);
  const [events, setEvents] = useState<{ source: StreamSource; items: StreamEvent[] } | null>(null);
  // Most projects never need a live feed, so the set-up form waits to be asked for.
  const [formOpen, setFormOpen] = useState(false);

  const postgresConnections = connections.filter((connection) => connection.connector_type === "postgresql");
  const apiOrigin = appConfig.apiBaseUrl.replace(/\/api\/v1\/?$/, "");

  const reload = useCallback(async () => {
    setSources((await apiFetch<{ items: StreamSource[] }>(`/projects/${projectId}/streams`)).items);
  }, [projectId]);

  const run = useCallback(async <T,>(key: string, action: () => Promise<T>): Promise<T | null> => {
    setBusy(key);
    setError(null);
    setFeedback(null);
    try {
      return await action();
    } catch (caught) {
      setError(extractErrorMessage(caught));
      return null;
    } finally {
      setBusy(null);
    }
  }, []);

  const create = async () => {
    const created = await run("create", () =>
      apiFetch<StreamSourceCreated>(`/projects/${projectId}/streams`, {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          kind,
          connection_id: kind === "postgres_cdc" ? connectionId || null : null,
          tables: kind === "postgres_cdc" ? tables.split(",").map((item) => item.trim()).filter(Boolean) : [],
        }),
      }),
    );
    if (!created) return;
    setName("");
    setTables("");
    setFormOpen(false);
    await reload();
    if (created.token) setSecret(created);
    else setFeedback(`${created.name} is following ${created.tables.join(", ")}. Changes are picked up automatically; "Check for changes" reads them now.`);
  };

  const poll = async (source: StreamSource) => {
    const result = await run(`poll-${source.id}`, () =>
      apiFetch<StreamPollResponse>(`/projects/${projectId}/streams/${source.id}/poll`, { method: "POST" }),
    );
    if (!result) return;
    await reload();
    setFeedback(
      `${source.name}: read ${result.changes_read} change(s), stored ${result.events_stored} new event(s)` +
        (result.slot_created ? " (replication slot created)" : "") +
        `. ${result.note}.`,
    );
  };

  const materialise = async (source: StreamSource) => {
    const result = await run(`mat-${source.id}`, () =>
      apiFetch<StreamMaterialiseResponse>(`/projects/${projectId}/streams/${source.id}/materialise`, { method: "POST" }),
    );
    if (!result) return;
    await reload();
    setFeedback(`${source.name}: ${result.rows} event(s) saved as version ${result.version_number} of its dataset.`);
  };

  const showEvents = async (source: StreamSource) => {
    const result = await run(`events-${source.id}`, () =>
      apiFetch<{ items: StreamEvent[] }>(`/projects/${projectId}/streams/${source.id}/events?limit=25`),
    );
    if (result) setEvents({ source, items: result.items });
  };

  return (
    <>
      <SectionPanel
        title="Live feeds"
        description="Data that arrives by itself: events sent to a web address, or changes followed in a PostgreSQL table. Following changes works for PostgreSQL only; other databases are imported on a schedule."
        actions={
          <Button variant="secondary" size="sm" onClick={() => setFormOpen((open) => !open)}>
            {formOpen ? "Cancel" : "Set up a live feed"}
          </Button>
        }
      >
        {feedback ? <p className="mb-3 text-[13px] text-accent">{feedback}</p> : null}
        {error ? (
          <p role="alert" className="mb-3 rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
            {error}
          </p>
        ) : null}
        <div className={cx("grid gap-6", formOpen && "lg:grid-cols-[minmax(0,360px)_1fr]")}>
          {formOpen ? (
          <div className="space-y-3 rounded-2xl border border-line bg-surface p-4">
            <FormField label="Kind of feed" htmlFor="stream-kind">
              <Select id="stream-kind" value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}>
                <option value="webhook">Receive events at a web address (webhook)</option>
                <option value="postgres_cdc">Follow changes in a PostgreSQL table</option>
              </Select>
            </FormField>
            <FormField label="Name" htmlFor="stream-name">
              <Input id="stream-name" value={name} onChange={(event) => setName(event.target.value)} placeholder={kind === "webhook" ? "Shop order events" : "Orders table changes"} />
            </FormField>
            {kind === "postgres_cdc" ? (
              <>
                <FormField
                  label="Database"
                  htmlFor="stream-connection"
                  description={
                    postgresConnections.length === 0
                      ? "Connect a PostgreSQL database above first. Your database administrator may need to turn on change tracking (wal_level = logical)."
                      : "Your database administrator may need to turn on change tracking (wal_level = logical). The first check says so if it is off."
                  }
                >
                  <Select id="stream-connection" value={connectionId} onChange={(event) => setConnectionId(event.target.value)}>
                    <option value="">Choose…</option>
                    {postgresConnections.map((connection) => (
                      <option key={connection.id} value={connection.id}>{connection.name}</option>
                    ))}
                  </Select>
                </FormField>
                <FormField label="Tables to follow" htmlFor="stream-tables" description="Separate several with commas.">
                  <Input id="stream-tables" value={tables} onChange={(event) => setTables(event.target.value)} placeholder="public.orders, public.customers" />
                </FormField>
              </>
            ) : (
              <p className="text-[13px] leading-5 text-muted">
                You get a private web address, shown once. Anything sent to it is stored as an event and becomes rows when you save it to a dataset.
              </p>
            )}
            <Button
              className="w-full"
              onClick={() => void create()}
              disabled={busy === "create" || name.trim().length < 2 || (kind === "postgres_cdc" && (!connectionId || !tables.trim()))}
            >
              {busy === "create" ? "Creating…" : kind === "webhook" ? "Create web address" : "Start following"}
            </Button>
          </div>
          ) : null}

          <div className="space-y-3">
            {sources.length === 0 ? (
              <p className="rounded-2xl border border-dashed border-line px-4 py-6 text-center text-[14px] text-muted">
                No live feeds. Most projects do not need one: files and database imports cover the usual cases.
              </p>
            ) : (
              sources.map((source) => (
                <div key={source.id} className="rounded-2xl border border-line bg-surface px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-sm font-semibold text-ink">{source.name}</h3>
                    <Badge>
                      {source.kind === "webhook" ? "Web address" : "PostgreSQL changes"}
                    </Badge>
                    <Badge tone={source.last_error ? "danger" : "neutral"}>
                      {source.last_error ? "Needs attention" : source.status === "active" ? "On" : source.status}
                    </Badge>
                    <div className="ml-auto flex flex-wrap items-center gap-2">
                      {source.kind === "postgres_cdc" ? (
                        <Button variant="secondary" size="sm" disabled={busy !== null} onClick={() => void poll(source)}>
                          {busy === `poll-${source.id}` ? "Checking…" : "Check for changes"}
                        </Button>
                      ) : null}
                      <Button variant="secondary" size="sm" disabled={busy !== null || source.events_count === 0} onClick={() => void materialise(source)}>
                        {busy === `mat-${source.id}` ? "Saving…" : "Save to a dataset"}
                      </Button>
                      <Button variant="ghost" size="sm" disabled={busy !== null} onClick={() => void showEvents(source)}>
                        Show events
                      </Button>
                      <DeleteRowButton
                        path={`/projects/${projectId}/streams/${source.id}`}
                        name={source.name}
                        kind="live feed"
                        consequences={[
                          "Its stored events go with it.",
                          ...(source.kind === "postgres_cdc" ? ["Its replication slot is dropped, so the database stops keeping change log for it."] : []),
                          ...(source.dataset_id ? ["The dataset it materialised stays, with its versions."] : []),
                        ]}
                        onDeleted={() => setSources((current) => current.filter((item) => item.id !== source.id))}
                      />
                    </div>
                  </div>
                  <div className="mt-1 text-[13px] text-muted">
                    {source.events_count} event{source.events_count === 1 ? "" : "s"}
                    {source.last_event_at ? ` · last ${formatDateTime(source.last_event_at)}` : ""}
                    {source.kind === "postgres_cdc" ? ` · ${source.connection_name ?? "connection"} · ${source.tables.join(", ")} · slot ${source.slot_name}` : ` · ${apiOrigin}${source.webhook_path}`}
                    {source.cursor ? ` · at ${source.cursor}` : ""}
                    {source.last_polled_at ? ` · polled ${formatDateTime(source.last_polled_at)}` : ""}
                  </div>
                  {source.dataset_id ? (
                    <div className="mt-1 text-[13px] text-ink-3">
                      Saved into{" "}
                      <Link href={`/projects/${projectId}/datasets/${source.dataset_id}`} className="text-accent">
                        {source.dataset_name ?? "its dataset"}
                      </Link>
                      {source.last_materialised_at ? ` · ${formatDateTime(source.last_materialised_at)}` : ""}
                    </div>
                  ) : null}
                  {source.last_error ? <p className="mt-1 text-[13px] text-danger">{source.last_error}</p> : null}
                </div>
              ))
            )}
          </div>
        </div>
      </SectionPanel>

      <Modal
        open={secret !== null}
        title="Your feed's web address"
        description="Copy it now: this is the only time it is shown. Anyone who has it can send events to this feed."
        onClose={() => setSecret(null)}
        widthClassName="max-w-lg"
        footer={<Button size="sm" onClick={() => setSecret(null)}>Done</Button>}
      >
        {secret ? (
          <div className="space-y-2 text-sm text-ink-3">
            <code className="block break-all rounded-xl border border-line bg-sunken px-3 py-2 font-mono text-[12px] text-ink">
              POST {apiOrigin}{secret.webhook_path_with_token}
            </code>
            <p className="text-[12px]">Send JSON with <code className="font-mono">Content-Type: application/json</code>. Up to 256 KB per post.</p>
          </div>
        ) : null}
      </Modal>

      <Modal
        open={events !== null}
        title={events ? `${events.source.name} · latest events` : "Events"}
        description="Newest first. Saving to a dataset writes all of them, oldest first, as one new version."
        onClose={() => setEvents(null)}
        widthClassName="max-w-3xl"
        footer={<Button variant="secondary" size="sm" onClick={() => setEvents(null)}>Close</Button>}
      >
        {events && events.items.length === 0 ? (
          <p className="text-[12.5px] text-muted">Nothing has arrived yet.</p>
        ) : events ? (
          <ul className="max-h-[50vh] space-y-1 overflow-auto">
            {events.items.map((event) => (
              <li key={event.id} className="rounded-lg border border-line bg-surface px-3 py-2">
                <div className="flex flex-wrap gap-2 text-[12px] text-muted">
                  <span className="font-mono text-ink">#{event.seq}</span>
                  <span>{event.kind}</span>
                  {event.table_name ? <span>{event.table_name}</span> : null}
                  <span>{formatDateTime(event.received_at)}</span>
                </div>
                <pre className="mt-1 overflow-x-auto font-mono text-[12px] text-ink-2">{JSON.stringify(event.payload_json, null, 1)}</pre>
              </li>
            ))}
          </ul>
        ) : null}
      </Modal>
    </>
  );
}
