"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type {
  ExtractionConnection,
  LiveKind,
  LiveTestResult,
  StreamSourceCreate,
  StreamSourceCreated,
} from "@platform/shared-types";
import { Badge, Button, FormField, Input, Modal, Select } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { useApiAddress } from "@/lib/use-api-address";

import { FAMILIES, everyWords, fieldValues, firstMissing, guaranteeTone, kindsOf, settingsFrom, tableList } from "../live-words";
import { FeedSettingsForm } from "./feed-settings-form";

type AddLiveFeedProps = {
  projectId: string;
  kinds: LiveKind[];
  connections: ExtractionConnection[];
  open: boolean;
  onClose: () => void;
};

const READ_EVERY = [1, 5, 15, 60, 300];
const SAVE_EVERY = [10, 60, 300, 900, 3600];

/** Choose a kind, fill in its settings, try them, save. A webhook's address is shown once, at the end. */
export function AddLiveFeed({ projectId, kinds, connections, open, onClose }: AddLiveFeedProps) {
  const router = useRouter();
  const apiAddress = useApiAddress();
  const [kind, setKind] = useState<LiveKind | null>(null);
  const [name, setName] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [connectionId, setConnectionId] = useState("");
  const [tables, setTables] = useState("");
  const [readEvery, setReadEvery] = useState(5);
  const [saveEvery, setSaveEvery] = useState(60);
  const [busy, setBusy] = useState<"try" | "save" | null>(null);
  const [tried, setTried] = useState<LiveTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<StreamSourceCreated | null>(null);

  const choose = (next: LiveKind) => {
    setKind(next);
    setValues(fieldValues(next.fields));
    setConnectionId(connections.find((c) => next.connection_types.includes(c.connector_type))?.id ?? "");
    setTables("");
    setTried(null);
    setError(null);
  };

  const close = () => {
    setKind(null);
    setName("");
    setTried(null);
    setError(null);
    setCreated(null);
    onClose();
  };

  const missing = kind
    ? (name.trim().length < 2 ? "A name" : null) ??
      (kind.connection_types.length && !connectionId ? "A connection" : null) ??
      (kind.family === "change_capture" && tableList(tables).length === 0 ? "A table to follow" : null) ??
      firstMissing(kind.fields, values)
    : null;

  const body = (): StreamSourceCreate | null =>
    kind
      ? {
          name: name.trim(),
          kind: kind.key,
          connection_id: kind.connection_types.length ? connectionId || null : null,
          tables: kind.family === "change_capture" ? tableList(tables) : [],
          settings: settingsFrom(kind.fields, values),
          read_every_seconds: readEvery,
          save_every_seconds: saveEvery,
        }
      : null;

  const tryIt = async () => {
    const payload = body();
    if (!payload) return;
    setBusy("try");
    setError(null);
    try {
      setTried(
        await apiFetch<LiveTestResult>(`/projects/${projectId}/streams/try`, {
          method: "POST",
          body: JSON.stringify({
            kind: payload.kind,
            connection_id: payload.connection_id,
            tables: payload.tables,
            settings: payload.settings,
          }),
        }),
      );
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    const payload = body();
    if (!payload) return;
    setBusy("save");
    setError(null);
    try {
      const made = await apiFetch<StreamSourceCreated>(`/projects/${projectId}/streams`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (made.token) {
        setCreated(made);
      } else {
        close();
        router.push(`/projects/${projectId}/live/${made.id}`);
      }
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(null);
    }
  };

  const origin = apiAddress.replace(/\/api\/v1\/?$/, "");

  if (created) {
    return (
      <Modal
        open={open}
        title="Your feed's web address"
        description="Copy it now: this is the only time it is shown. Anyone who has it can send events to this feed."
        onClose={close}
        widthClassName="max-w-lg"
        footer={
          <Button
            size="sm"
            onClick={() => {
              const id = created.id;
              close();
              router.push(`/projects/${projectId}/live/${id}`);
            }}
          >
            Done
          </Button>
        }
      >
        <div className="space-y-2 text-sm text-ink-3">
          <code className="block break-all rounded-xl border border-line bg-sunken px-3 py-2 font-mono text-[12px] text-ink">
            POST {origin}
            {created.webhook_path_with_token}
          </code>
          <p className="text-[13px]">
            Send JSON with <code className="font-mono">Content-Type: application/json</code>, up to 256 KB a post. Add an{" "}
            <code className="font-mono">Idempotency-Key</code> header to each post and a post sent twice is saved once.
          </p>
        </div>
      </Modal>
    );
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title={kind ? `Add ${kind.label}` : "Add a live feed"}
      description={kind ? kind.description : "Data that arrives by itself, saved as datasets every so often."}
      widthClassName="max-w-2xl"
      footer={
        kind ? (
          <div className="flex w-full flex-wrap items-center justify-between gap-2">
            <Button variant="ghost" size="sm" onClick={() => setKind(null)}>
              Choose another kind
            </Button>
            <div className="flex gap-2">
              {kind.family !== "webhook" ? (
                <Button variant="secondary" size="sm" disabled={busy !== null || Boolean(missing)} onClick={() => void tryIt()}>
                  {busy === "try" ? "Trying…" : "Try these settings"}
                </Button>
              ) : null}
              <Button size="sm" disabled={busy !== null || Boolean(missing)} onClick={() => void save()}>
                {busy === "save" ? "Saving…" : kind.family === "webhook" ? "Make the address" : "Start reading"}
              </Button>
            </div>
          </div>
        ) : (
          <Button variant="secondary" size="sm" onClick={close}>
            Cancel
          </Button>
        )
      }
    >
      {!kind ? (
        <div className="space-y-5">
          {FAMILIES.map((family) => (
            <section key={family.family} className="space-y-2">
              <div>
                <h3 className="text-sm font-semibold text-ink">{family.label}</h3>
                <p className="text-[13px] text-ink-3">{family.description}</p>
              </div>
              <ul className="grid gap-2 sm:grid-cols-2">
                {kindsOf(kinds, family.family).map((option) => (
                  <li key={option.key}>
                    <button
                      type="button"
                      disabled={!option.available}
                      onClick={() => choose(option)}
                      className="h-full w-full rounded-2xl border border-line bg-surface px-4 py-3 text-left transition hover:border-[color:var(--accent)] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[14px] font-medium text-ink">{option.label}</span>
                        <Badge tone={option.tier <= 2 ? "success" : "neutral"} title={option.tier_explanation}>
                          {option.tier_label}
                        </Badge>
                      </div>
                      <p className="mt-1 text-[13px] text-ink-3">
                        {option.available ? option.guarantee_title : option.unavailable_reason}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-line bg-sunken px-4 py-3">
            <Badge tone={guaranteeTone(kind.guarantee)}>{kind.guarantee_title}</Badge>
            <span className="text-[13px] text-ink-3">{kind.guarantee_detail}</span>
          </div>
          <FormField label="Name" htmlFor="feed-name">
            <Input
              id="feed-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={kind.family === "change_capture" ? "Shop database changes" : "Order events"}
              autoFocus
            />
          </FormField>
          <FeedSettingsForm
            projectId={projectId}
            kind={kind}
            values={values}
            onValues={setValues}
            connections={connections}
            connectionId={connectionId}
            onConnection={setConnectionId}
            tables={tables}
            onTables={setTables}
            idPrefix="feed"
          />
          <div className="grid gap-4 sm:grid-cols-2">
            {kind.family !== "webhook" ? (
              <FormField label="Read" htmlFor="feed-read-every">
                <Select id="feed-read-every" value={String(readEvery)} onChange={(event) => setReadEvery(Number(event.target.value))}>
                  {READ_EVERY.map((seconds) => (
                    <option key={seconds} value={seconds}>
                      {everyWords(seconds)}
                    </option>
                  ))}
                </Select>
              </FormField>
            ) : null}
            <FormField label="Save to datasets" htmlFor="feed-save-every">
              <Select id="feed-save-every" value={String(saveEvery)} onChange={(event) => setSaveEvery(Number(event.target.value))}>
                {SAVE_EVERY.map((seconds) => (
                  <option key={seconds} value={seconds}>
                    {everyWords(seconds)}
                  </option>
                ))}
              </Select>
            </FormField>
          </div>
          {missing ? <p className="text-[13px] text-ink-3">{missing} is still needed.</p> : null}
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
        </div>
      )}
    </Modal>
  );
}
