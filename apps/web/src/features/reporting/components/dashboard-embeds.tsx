"use client";

import Link from "next/link";
import { useState } from "react";

import type { DashboardEmbed } from "@platform/shared-types";
import { EMBED_DAYS } from "@platform/shared-types";
import {
  Badge,
  Button,
  FormField,
  Input,
  Modal,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
  useToast,
} from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import type { EmbedOrigins } from "@/lib/embed-origins";
import { formatDate } from "@/lib/format";

const DAYS_WORDS: Record<(typeof EMBED_DAYS)[number], string> = {
  1: "1 day",
  7: "1 week",
  30: "30 days",
  90: "90 days",
  365: "1 year",
};

/** The embed's own link: the API's when it knows the web's address, else this site's. */
export function embedLink(embed: Pick<DashboardEmbed, "url" | "token">, origin: string): string {
  return embed.url ?? `${origin}/embed/${embed.token ?? ""}`;
}

/** What a site pastes into its page to show the dashboard. */
export function frameCode(link: string, title: string): string {
  const safeTitle = title.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  return `<iframe src="${link}" title="${safeTitle}" width="100%" height="640" style="border:0" loading="lazy"></iframe>`;
}

/** "On until 14 Nov 2026", "Turned off", "Ran out on 2 Oct 2026". */
export function embedState(embed: Pick<DashboardEmbed, "state" | "expires_at" | "revoked_at">): string {
  if (embed.state === "off") return "Turned off";
  if (embed.state === "expired") return `Ran out on ${formatDate(embed.expires_at)}`;
  return `On until ${formatDate(embed.expires_at)}`;
}

/**
 * Show a dashboard inside another site (A8, Y4): a link that runs out, the
 * code to paste, and the secret a site's server signs links of its own with.
 */
export function DashboardEmbeds({
  projectId,
  dashboardId,
  dashboardName,
  origins,
}: {
  projectId: string;
  dashboardId: string;
  dashboardName: string;
  origins: EmbedOrigins;
}) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<DashboardEmbed[] | null>(null);
  const [name, setName] = useState("");
  const [days, setDays] = useState<(typeof EMBED_DAYS)[number]>(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fresh, setFresh] = useState<DashboardEmbed | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const base = `/projects/${projectId}/dashboards/${dashboardId}/embeds`;
  const origin = typeof window === "undefined" ? "" : window.location.origin;

  const show = async () => {
    setOpen(true);
    setError(null);
    try {
      setItems((await apiFetch<{ items: DashboardEmbed[] }>(base)).items);
    } catch (caught) {
      setError(extractErrorMessage(caught));
      setItems([]);
    }
  };

  const copy = async (text: string, what: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Copied", what);
    } catch {
      toast.error("Could not copy", "Select it and copy it by hand.");
    }
  };

  const make = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const made = await apiFetch<DashboardEmbed>(base, { method: "POST", body: JSON.stringify({ name, days }) });
      setItems((current) => [{ ...made, signing_secret: null }, ...(current ?? [])]);
      setFresh(made);
      setName("");
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const turnOff = async (embed: DashboardEmbed) => {
    setBusy(true);
    try {
      const off = await apiFetch<DashboardEmbed>(`${base}/${embed.id}`, { method: "DELETE" });
      setItems((current) => (current ?? []).map((item) => (item.id === off.id ? off : item)));
      if (fresh?.id === off.id) setFresh(null);
      toast.success("Turned off", `“${off.name}” no longer shows the dashboard.`);
    } catch (caught) {
      toast.error("Could not turn it off", extractErrorMessage(caught));
    } finally {
      setBusy(false);
      setConfirming(null);
    }
  };

  const freshLink = fresh ? embedLink(fresh, origin) : "";

  return (
    <>
      <Button variant="secondary" size="sm" onClick={() => void show()}>
        Embed
      </Button>
      <Modal
        open={open}
        title="Show on another site"
        description="A link that runs out, for a page on your own site or a partner's. Turn it off at any time."
        onClose={() => {
          setOpen(false);
          setFresh(null);
          setConfirming(null);
        }}
        widthClassName="max-w-3xl"
      >
        <div className="space-y-5">
          {origins.allowed.length ? (
            <p className="text-[13px] leading-6 text-ink-2">
              Sites that may show it: {origins.allowed.map((site) => site.replace(/^https?:\/\//, "")).join(", ")}.
            </p>
          ) : (
            <div className="rounded-xl border border-warning-line bg-warning-soft px-3.5 py-3 text-[13px] leading-6 text-ink">
              No other site may show it yet. Whoever runs Pipewright lists the sites allowed in{" "}
              <code className="font-mono text-[12px]">EMBED_ALLOWED_ORIGINS</code>. Until then the link opens on its own.
            </div>
          )}
          {origins.ignored.length ? (
            <p className="text-[13px] leading-6 text-danger">
              Left out, not a site’s address: {origins.ignored.join(", ")}. Write one like https://portal.example.com.
            </p>
          ) : null}

          {fresh ? (
            <div className="space-y-3 rounded-xl border border-success-line bg-success-soft px-3.5 py-3">
              <div className="text-[13px] font-medium text-success">
                “{fresh.name}” is ready. Copy the secret now; it will not be shown again.
              </div>
              {[
                { label: "Code to paste into the page", value: frameCode(freshLink, dashboardName), note: "The code is copied." },
                { label: "Link", value: freshLink, note: "The link is copied." },
                {
                  label: "Signing secret",
                  value: fresh.signing_secret ?? "",
                  note: "Keep it with your other secrets. It will not be shown again.",
                },
              ].map((row) => (
                <div key={row.label}>
                  <div className="text-[12px] font-medium text-ink-3">{row.label}</div>
                  <div className="mt-1 flex items-center gap-2">
                    <code className="flex-1 overflow-x-auto whitespace-nowrap rounded-lg bg-surface px-2.5 py-1.5 font-mono text-[12px] text-ink">
                      {row.value}
                    </code>
                    <Button variant="secondary" size="sm" onClick={() => void copy(row.value, row.note)}>
                      Copy
                    </Button>
                  </div>
                </div>
              ))}
              <p className="text-[13px] leading-6 text-ink-2">
                Your site’s server can sign short links with the secret, and fix filters so each customer sees only their own
                rows.{" "}
                <Link href="/help/api#embedding-a-dashboard" className="underline">
                  How to sign a link
                </Link>
              </p>
              <div className="flex justify-end">
                <Button size="sm" onClick={() => setFresh(null)}>
                  Done
                </Button>
              </div>
            </div>
          ) : (
            <form onSubmit={(event) => void make(event)} className="grid gap-3 sm:grid-cols-[1fr_180px_auto] sm:items-end">
              <FormField label="Where it will be shown" htmlFor="embed-name">
                <Input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Customer portal"
                  maxLength={120}
                  required
                />
              </FormField>
              <FormField label="Lasts" htmlFor="embed-days">
                <Select value={days} onChange={(event) => setDays(Number(event.target.value) as (typeof EMBED_DAYS)[number])}>
                  {EMBED_DAYS.map((choice) => (
                    <option key={choice} value={choice}>
                      {DAYS_WORDS[choice]}
                    </option>
                  ))}
                </Select>
              </FormField>
              <Button type="submit" disabled={busy || !name.trim()} className="h-11">
                {busy ? "Making…" : "Make a link"}
              </Button>
            </form>
          )}
          {error ? <p className="text-[13px] text-danger">{error}</p> : null}

          {items === null ? (
            <p className="text-[13px] text-ink-3">Loading…</p>
          ) : items.length === 0 ? (
            <p className="text-[13px] text-ink-3">Not shown on any other site yet.</p>
          ) : (
            <Table minWidth={560}>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Where</TableHeaderCell>
                  <TableHeaderCell>State</TableHeaderCell>
                  <TableHeaderCell>Last opened</TableHeaderCell>
                  <TableHeaderCell className="text-right">Actions</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((embed) => (
                  <TableRow key={embed.id}>
                    <TableCell className="text-ink">
                      {embed.name}
                      <div className="font-mono text-[12px] text-ink-3">{embed.secret_hint}</div>
                    </TableCell>
                    <TableCell>
                      <Badge tone={embed.state === "on" ? "success" : "neutral"}>{embedState(embed)}</Badge>
                    </TableCell>
                    <TableCell className="text-ink-3">
                      {embed.last_opened_at ? formatDate(embed.last_opened_at) : "Not yet"}
                    </TableCell>
                    <TableCell className="text-right">
                      {embed.state !== "on" ? null : confirming === embed.id ? (
                        <span className="inline-flex flex-wrap items-center justify-end gap-2">
                          <span className="text-[12px] text-ink-2">Every link to it stops.</span>
                          <Button variant="danger" size="sm" disabled={busy} onClick={() => void turnOff(embed)}>
                            Turn off
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => setConfirming(null)}>
                            Keep it
                          </Button>
                        </span>
                      ) : (
                        <span className="inline-flex flex-wrap justify-end gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => void copy(frameCode(embedLink(embed, origin), dashboardName), "The code is copied.")}
                          >
                            Copy code
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => void copy(embedLink(embed, origin), "The link is copied.")}>
                            Copy link
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => setConfirming(embed.id)}>
                            Turn off
                          </Button>
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      </Modal>
    </>
  );
}
