"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import type {
  AuthUser,
  ExtractionConnection,
  LiveKind,
  LiveRecipe,
  LiveTestResult,
  StreamEvent,
  StreamMaterialiseResponse,
  StreamPollResponse,
  StreamSource,
  ThroughputPoint,
  ThroughputResponse,
  TransformationPipelineRecord,
} from "@platform/shared-types";
import { Badge, Button, FormField, Input, SectionPanel, Select, StatTile } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { DeleteRowButton } from "@/components/ui/delete-row-button";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { countOf, formatDateTime, formatDateUtc, formatNumber, formatTimeUtc } from "@/lib/format";
import { useApiAddress } from "@/lib/use-api-address";

import {
  behindWords,
  durationWords,
  everyWords,
  feedState,
  fieldValues,
  guaranteeTone,
  settingsFrom,
  tableList,
  tableState,
} from "../live-words";
import { FeedSettingsForm } from "./feed-settings-form";
import { LiveRecipesPanel } from "./live-recipes-panel";
import { LiveRunnerBanner } from "./live-runner-banner";
import { ThroughputChart } from "./throughput-chart";

type LiveFeedPageProps = {
  currentUser: AuthUser;
  projectId: string;
  initialFeed: StreamSource;
  kinds: LiveKind[];
  connections: ExtractionConnection[];
  initialThroughput: ThroughputPoint[];
  initialEvents: StreamEvent[];
  initialRecipes: LiveRecipe[];
  recipes: TransformationPipelineRecord[];
  datasets: { id: string; name: string }[];
};

const REFRESH_MS = 10_000;

/** One live feed: is it keeping up, what it keeps, what runs on it, and its settings (D1). */
export function LiveFeedPageView({
  currentUser,
  projectId,
  initialFeed,
  kinds,
  connections,
  initialThroughput,
  initialEvents,
  initialRecipes,
  recipes,
  datasets,
}: LiveFeedPageProps) {
  const router = useRouter();
  const apiAddress = useApiAddress();
  const [feed, setFeed] = useState(initialFeed);
  const [points, setPoints] = useState(initialThroughput);
  const [events, setEvents] = useState(initialEvents);
  const [liveRecipes, setLiveRecipes] = useState(initialRecipes);
  const [busy, setBusy] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const kind = kinds.find((item) => item.key === feed.kind) ?? null;
  const base = `/projects/${projectId}/streams/${feed.id}`;

  const reload = useCallback(async () => {
    const [nextFeed, nextPoints, nextEvents, nextRecipes] = await Promise.all([
      apiFetch<StreamSource>(base),
      apiFetch<ThroughputResponse>(`${base}/throughput`),
      apiFetch<{ items: StreamEvent[] }>(`${base}/events?limit=20`),
      apiFetch<{ items: LiveRecipe[] }>(`${base}/recipes`),
    ]);
    setFeed(nextFeed);
    setPoints(nextPoints.items);
    setEvents(nextEvents.items);
    setLiveRecipes(nextRecipes.items);
  }, [base]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void reload().catch(() => undefined);
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [reload]);

  const act = async <T,>(key: string, action: () => Promise<T>, said: (result: T) => string) => {
    setBusy(key);
    setError(null);
    setFeedback(null);
    try {
      const result = await action();
      await reload();
      setFeedback(said(result));
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(null);
    }
  };

  const post = <T,>(path: string, body?: unknown) =>
    apiFetch<T>(`${base}${path}`, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

  const state = feedState(feed);
  const behind = behindWords(feed.behind);
  const origin = apiAddress.replace(/\/api\/v1\/?$/, "");
  const tablesKept = feed.live_tables;

  return (
    <AppShell
      currentUser={currentUser}
      title={feed.name}
      subtitle={`${feed.kind_label}${feed.connection_name ? ` through ${feed.connection_name}` : ""}.`}
      meta={
        <Badge tone={state.tone} title={feed.last_error ?? undefined}>
          {state.word}
        </Badge>
      }
      actions={
        <>
          {feed.family !== "webhook" ? (
            <Button
              variant="secondary"
              disabled={busy !== null || feed.status === "paused"}
              onClick={() =>
                void act("read", () => post<StreamPollResponse>("/poll"), (result) =>
                  `Read ${countOf(result.read, "event")}, ${countOf(result.stored, "new one")} saved. ${result.notes.join(" ")}`.trim(),
                )
              }
            >
              {busy === "read" ? "Reading…" : "Read now"}
            </Button>
          ) : null}
          <Button
            variant="secondary"
            disabled={busy !== null}
            onClick={() =>
              void act("save", () => post<StreamMaterialiseResponse>("/materialise"), (result) =>
                [
                  result.events_saved ? `${countOf(result.events_saved, "event")} added to the log` : null,
                  result.changes_applied ? `${countOf(result.changes_applied, "change")} applied to its tables` : null,
                  result.recipe_outputs ? `${countOf(result.recipe_outputs, "live recipe output")} saved` : null,
                ]
                  .filter(Boolean)
                  .join("; ") || "Everything was already saved.",
              )
            }
          >
            {busy === "save" ? "Saving…" : "Save now"}
          </Button>
          <Button
            variant="ghost"
            disabled={busy !== null}
            onClick={() =>
              void act(
                "pause",
                () =>
                  apiFetch<StreamSource>(base, {
                    method: "PATCH",
                    body: JSON.stringify({ status: feed.status === "paused" ? "active" : "paused" }),
                  }),
                (result) => (result.status === "paused" ? "Paused. Nothing is read until it is resumed." : "Reading again."),
              )
            }
          >
            {feed.status === "paused" ? "Resume" : "Pause"}
          </Button>
        </>
      }
    >
      <LiveRunnerBanner />
      {feedback ? <p className="text-[14px] text-accent">{feedback}</p> : null}
      {error ? (
        <p role="alert" className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </p>
      ) : null}
      {feed.status === "failing" && feed.last_error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          <p className="font-medium">
            {countOf(feed.failures, "try", "tries")} in a row failed
            {feed.next_read_at ? `; next try at ${formatDateTime(feed.next_read_at)}` : ""}.
          </p>
          <p className="mt-1">{feed.last_error}</p>
        </div>
      ) : null}

      <div className={feed.behind === null ? "grid gap-4 sm:grid-cols-3" : "grid gap-4 sm:grid-cols-2 xl:grid-cols-4"}>
        <StatTile
          label="Events received"
          value={formatNumber(feed.events_count)}
          caption={feed.last_event_at ? `Last at ${formatTimeUtc(feed.last_event_at)}, ${formatDateUtc(feed.last_event_at)}` : "None yet"}
        />
        {feed.behind !== null ? (
          <StatTile
            label="Waiting at the source"
            value={formatNumber(feed.behind)}
            tone={feed.behind ? "warning" : "neutral"}
            caption={`Read ${everyWords(feed.read_every_seconds)}`}
          />
        ) : null}
        <StatTile
          label="Last saved"
          value={feed.last_materialised_at ? formatTimeUtc(feed.last_materialised_at) : "Not yet"}
          caption={`${feed.last_materialised_at ? `${formatDateUtc(feed.last_materialised_at)}. ` : ""}Saves ${everyWords(feed.save_every_seconds)}`}
        />
        <StatTile label="Live recipes" value={formatNumber(liveRecipes.length)} caption={liveRecipes.length ? "Run on every batch" : "None yet"} />
      </div>

      <SectionPanel
        title="Events per minute"
        description={
          behind ??
          (feed.family === "webhook"
            ? "Over the last hour, as they were posted."
            : `Over the last hour, as they were read ${everyWords(feed.read_every_seconds)}.`)
        }
      >
        <ThroughputChart points={points} />
      </SectionPanel>

      <SectionPanel title="Is each event saved once?" description={feed.guarantee_detail}>
        <div className="flex flex-wrap items-center gap-2 text-[14px] text-ink-2">
          <Badge tone={guaranteeTone(feed.guarantee)}>{feed.guarantee_title}</Badge>
          <Badge tone={feed.tier <= 2 ? "success" : "neutral"}>{feed.tier_label}</Badge>
          {feed.family === "webhook" && feed.webhook_path ? (
            <span>
              Posts go to <code className="font-mono text-[13px]">{origin}{feed.webhook_path}</code>, the address shown when it was made.
            </span>
          ) : null}
        </div>
      </SectionPanel>

      <SectionPanel
        title="What it keeps"
        description="Each is a dataset with a new version every time the feed saves, so its history and changes can be seen like any other's."
      >
        <ul className="divide-y divide-[color:var(--line)]">
          <li className="flex flex-wrap items-center justify-between gap-2 py-3 first:pt-0">
            <div>
              <div className="text-[14px] font-medium text-ink">Every event</div>
              <div className="text-[13px] text-ink-3">The log of everything that arrived, added to as it saves.</div>
            </div>
            {feed.dataset_id ? (
              <Link href={`/projects/${projectId}/datasets/${feed.dataset_id}`} className="text-[14px] text-[color:var(--accent-muted)] hover:underline">
                {feed.dataset_name ?? "Its dataset"}
              </Link>
            ) : (
              <span className="text-[13px] text-ink-3">Made at its first save</span>
            )}
          </li>
          {tablesKept.map((table) => {
            const words = tableState(table);
            return (
              <li key={table.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[14px] font-medium text-ink">{table.table_name}</span>
                    <Badge tone={words.tone}>{words.word}</Badge>
                  </div>
                  <div className="text-[13px] text-ink-3">
                    {table.state === "following"
                      ? `As it is now: ${countOf(table.rows_now ?? 0, "row")}, by ${table.key_columns.join(", ")}`
                      : table.state === "log_only"
                        ? "It has no primary key, so its changes are in the log but no table is kept."
                        : table.state === "waiting"
                          ? "Its first copy is taken on the next read."
                          : table.last_error ?? ""}
                  </div>
                  {table.last_error && table.state !== "following" ? (
                    <div className="text-[13px] text-danger">{table.last_error}</div>
                  ) : null}
                </div>
                {table.dataset_id ? (
                  <Link href={`/projects/${projectId}/datasets/${table.dataset_id}`} className="text-[14px] text-[color:var(--accent-muted)] hover:underline">
                    Open the table
                  </Link>
                ) : null}
              </li>
            );
          })}
        </ul>
        {feed.family === "change_capture" ? (
          <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-line pt-3">
            <Button
              variant="ghost"
              size="sm"
              disabled={busy !== null}
              onClick={() =>
                void act("again", () => post<StreamSource>("/start-again"), () =>
                  "Starting again: each table is copied afresh on the next read, and its changes followed from then.",
                )
              }
            >
              Start again with a fresh copy
            </Button>
            <span className="text-[13px] text-ink-3">
              For when the database no longer has the changes since it last read. What is kept now stays as earlier versions.
            </span>
          </div>
        ) : null}
      </SectionPanel>

      <LiveRecipesPanel
        projectId={projectId}
        feed={feed}
        recipes={liveRecipes}
        savedRecipes={recipes}
        datasets={datasets}
        onChanged={reload}
      />

      <SectionPanel title="Latest events" description="Newest first, as they were stored.">
        {events.length === 0 ? (
          <p className="text-[14px] text-ink-3">Nothing has arrived yet.</p>
        ) : (
          <ul className="max-h-[28rem] space-y-1 overflow-auto">
            {events.map((event) => (
              <li key={event.id} className="rounded-lg border border-line bg-surface px-3 py-2">
                <details>
                  <summary className="flex cursor-pointer flex-wrap gap-2 text-[13px] text-ink-3">
                    <span className="font-mono text-ink">#{event.seq}</span>
                    <span>{event.kind}</span>
                    {event.table_name ? <span>{event.table_name}</span> : null}
                    <span>{formatDateTime(event.received_at)}</span>
                  </summary>
                  <pre className="mt-1 overflow-x-auto font-mono text-[12px] text-ink-2">
                    {JSON.stringify(event.payload_json, null, 1)}
                  </pre>
                </details>
              </li>
            ))}
          </ul>
        )}
      </SectionPanel>

      {kind ? (
        <FeedSettingsPanel
          projectId={projectId}
          feed={feed}
          kind={kind}
          connections={connections}
          onSaved={(next) => {
            setFeed(next);
            setFeedback("Settings saved.");
          }}
        />
      ) : null}

      <div className="flex justify-end">
        <DeleteRowButton
          path={base}
          name={feed.name}
          kind="live feed"
          label="Delete this live feed"
          consequences={[
            "Its stored events go with it, and nothing more is read.",
            ...(feed.family === "change_capture" ? ["The database stops keeping its change log for it."] : []),
            ...(feed.dataset_ids.length ? ["The datasets it kept stay, with their versions."] : []),
            ...(liveRecipes.length ? [`${countOf(liveRecipes.length, "live recipe")} on it go too.`] : []),
          ]}
          onDeleted={() => router.push(`/projects/${projectId}/live`)}
        />
      </div>
    </AppShell>
  );
}

const READ_EVERY = [1, 5, 15, 60, 300];
const SAVE_EVERY = [10, 60, 300, 900, 3600];
const KEEP_HOURS = [24, 72, 168, 336, 720];

function FeedSettingsPanel({
  projectId,
  feed,
  kind,
  connections,
  onSaved,
}: {
  projectId: string;
  feed: StreamSource;
  kind: LiveKind;
  connections: ExtractionConnection[];
  onSaved: (feed: StreamSource) => void;
}) {
  const [name, setName] = useState(feed.name);
  const [values, setValues] = useState(() => fieldValues(kind.fields, feed.settings));
  const [tables, setTables] = useState(feed.tables.join(", "));
  const [readEvery, setReadEvery] = useState(feed.read_every_seconds);
  const [saveEvery, setSaveEvery] = useState(feed.save_every_seconds);
  const [keepHours, setKeepHours] = useState(feed.keep_events_hours);
  const [busy, setBusy] = useState<"try" | "save" | null>(null);
  const [tried, setTried] = useState<LiveTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const base = `/projects/${projectId}/streams/${feed.id}`;

  const save = async () => {
    setBusy("save");
    setError(null);
    try {
      const next = await apiFetch<StreamSource>(base, {
        method: "PATCH",
        body: JSON.stringify({
          name: name.trim(),
          read_every_seconds: readEvery,
          save_every_seconds: saveEvery,
          keep_events_hours: keepHours,
          ...(kind.family !== "webhook" ? { settings: settingsFrom(kind.fields, values) } : {}),
          ...(kind.family === "change_capture" ? { tables: tableList(tables) } : {}),
        }),
      });
      onSaved(next);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(null);
    }
  };

  const tryIt = async () => {
    setBusy("try");
    setError(null);
    try {
      setTried(
        await apiFetch<LiveTestResult>(`/projects/${projectId}/streams/try`, {
          method: "POST",
          body: JSON.stringify({
            kind: feed.kind,
            connection_id: feed.connection_id,
            tables: tableList(tables),
            settings: settingsFrom(kind.fields, values),
            source_id: feed.id,
          }),
        }),
      );
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(null);
    }
  };

  return (
    <SectionPanel title="Settings" description="Changing what it reads takes effect on the next read.">
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-4">
          <FormField label="Name" htmlFor="settings-name">
            <Input id="settings-name" value={name} onChange={(event) => setName(event.target.value)} />
          </FormField>
          <FeedSettingsForm
            projectId={projectId}
            kind={kind}
            values={values}
            onValues={setValues}
            saved={feed.settings}
            connections={connections}
            connectionId={feed.connection_id ?? ""}
            tables={tables}
            onTables={setTables}
            idPrefix="settings"
          />
        </div>
        <div className="space-y-4">
          {kind.family !== "webhook" ? (
            <FormField label="Read" htmlFor="settings-read">
              <Select id="settings-read" value={String(readEvery)} onChange={(event) => setReadEvery(Number(event.target.value))}>
                {Array.from(new Set([...READ_EVERY, feed.read_every_seconds])).sort((a, b) => a - b).map((seconds) => (
                  <option key={seconds} value={seconds}>
                    {everyWords(seconds)}
                  </option>
                ))}
              </Select>
            </FormField>
          ) : null}
          <FormField label="Save to datasets" htmlFor="settings-save">
            <Select id="settings-save" value={String(saveEvery)} onChange={(event) => setSaveEvery(Number(event.target.value))}>
              {Array.from(new Set([...SAVE_EVERY, feed.save_every_seconds])).sort((a, b) => a - b).map((seconds) => (
                <option key={seconds} value={seconds}>
                  {everyWords(seconds)}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField
            label="Keep events for"
            htmlFor="settings-keep"
            description="Once every dataset and live recipe has them. The log dataset keeps them after that."
          >
            <Select id="settings-keep" value={String(keepHours)} onChange={(event) => setKeepHours(Number(event.target.value))}>
              {Array.from(new Set([...KEEP_HOURS, feed.keep_events_hours])).sort((a, b) => a - b).map((hours) => (
                <option key={hours} value={hours}>
                  {durationWords(hours * 3600)}
                </option>
              ))}
            </Select>
          </FormField>
          {tried ? (
            <div
              role="status"
              className={
                tried.ok
                  ? "rounded-2xl border border-success-line bg-success-soft px-4 py-3 text-[13px] text-success"
                  : "rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-[13px] text-danger"
              }
            >
              <p>{tried.message}</p>
              {tried.details.length ? (
                <ul className="mt-1 list-disc pl-5 text-ink-2">
                  {tried.details.map((detail) => (
                    <li key={detail}>{detail}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
          {error ? (
            <p role="alert" className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
              {error}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            {kind.family !== "webhook" ? (
              <Button variant="secondary" disabled={busy !== null} onClick={() => void tryIt()}>
                {busy === "try" ? "Trying…" : "Try these settings"}
              </Button>
            ) : null}
            <Button disabled={busy !== null || name.trim().length < 2} onClick={() => void save()}>
              {busy === "save" ? "Saving…" : "Save settings"}
            </Button>
          </div>
        </div>
      </div>
    </SectionPanel>
  );
}
