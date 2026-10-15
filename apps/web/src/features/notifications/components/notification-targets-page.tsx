"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type {
  AuthUser,
  ExternalNotificationTargetCreatePayload,
  ExternalNotificationTargetRecord,
  ExternalNotificationTargetType,
  ExternalNotificationTargetUpdatePayload,
  WebhookDelivery,
  WebhookDeliveryListResponse,
} from "@platform/shared-types";
import { EXTERNAL_NOTIFICATION_EVENT_TYPES } from "@platform/shared-types";
import {
  Badge,
  Button,
  FormField,
  Input,
  Modal,
  SectionPanel,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
  useToast,
} from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { DeleteRowButton } from "@/components/ui/delete-row-button";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { channelLabel } from "@/lib/labels";

const EVENT_LABELS: Record<string, string> = {
  incident_opened: "An incident opened",
  workflow_run_failed: "A workflow failed",
  workflow_run_partial: "A workflow finished with problems",
  weekly_summary: "A weekly summary of the project",
  schedule_run_failed: "A scheduled run failed",
  schedule_run_succeeded: "A scheduled run finished",
  dataset_publish_failed: "A delivery failed",
  dataset_publish_succeeded: "A delivery finished",
  transformation_run_failed: "A recipe run failed",
  transformation_run_succeeded: "A recipe run finished",
  metric_alert: "A measure crossed its alert",
  data_contract: "A contract was broken or changed",
  test: "A test",
};

type NotificationTargetsPageViewProps = {
  currentUser: AuthUser;
  projectId: string;
  initialItems: ExternalNotificationTargetRecord[];
};

function emptyEmailConfig() {
  return { recipient_email: "", sender_email: "", subject_prefix: "" };
}

function emptySlackConfig() {
  return { webhook_url: "", channel_label: "" };
}

/** A delivery's outcome in words: "Delivered (204)", "Trying again", "Not delivered (refused)". */
export function deliveryOutcome(delivery: Pick<WebhookDelivery, "status" | "last_status_code" | "last_error">): {
  label: string;
  tone: "success" | "warning" | "danger";
} {
  if (delivery.status === "succeeded") {
    return { label: `Delivered${delivery.last_status_code ? ` (${delivery.last_status_code})` : ""}`, tone: "success" };
  }
  if (delivery.status === "pending") return { label: "Trying again", tone: "warning" };
  return { label: "Not delivered", tone: "danger" };
}

export function NotificationTargetsPageView({
  currentUser,
  projectId,
  initialItems,
}: NotificationTargetsPageViewProps) {
  const router = useRouter();
  const toast = useToast();
  const [items, setItems] = useState(initialItems);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ExternalNotificationTargetRecord | null>(null);
  const [name, setName] = useState("");
  const [targetType, setTargetType] = useState<ExternalNotificationTargetType>("email");
  const [enabled, setEnabled] = useState(true);
  const [emailCfg, setEmailCfg] = useState(emptyEmailConfig);
  const [slackCfg, setSlackCfg] = useState(emptySlackConfig);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [selectedEvents, setSelectedEvents] = useState<Set<string>>(
    () => new Set([...EXTERNAL_NOTIFICATION_EVENT_TYPES]),
  );
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  // "New secret" stops the old one at once, so it asks first.
  const [replacingId, setReplacingId] = useState<string | null>(null);
  const [testMessage, setTestMessage] = useState<string | null>(null);
  // A webhook's signing secret, shown once after it is made or replaced.
  const [freshSecret, setFreshSecret] = useState<{ name: string; secret: string } | null>(null);
  const [deliveriesFor, setDeliveriesFor] = useState<ExternalNotificationTargetRecord | null>(null);
  const [deliveries, setDeliveries] = useState<WebhookDelivery[] | null>(null);

  const openCreate = () => {
    setEditing(null);
    setName("");
    setTargetType("email");
    setEnabled(true);
    setEmailCfg(emptyEmailConfig());
    setSlackCfg(emptySlackConfig());
    setWebhookUrl("");
    setSelectedEvents(new Set([...EXTERNAL_NOTIFICATION_EVENT_TYPES]));
    setFormError(null);
    setModalOpen(true);
  };

  const openEdit = (row: ExternalNotificationTargetRecord) => {
    setEditing(row);
    setName(row.name);
    setTargetType(row.target_type);
    setEnabled(row.enabled);
    const cfg = row.config_json as Record<string, string>;
    setEmailCfg(
      row.target_type === "email"
        ? {
            recipient_email: String(cfg.recipient_email ?? ""),
            sender_email: String(cfg.sender_email ?? ""),
            subject_prefix: String(cfg.subject_prefix ?? ""),
          }
        : emptyEmailConfig(),
    );
    setSlackCfg(
      row.target_type === "slack_webhook"
        ? { webhook_url: "", channel_label: String(cfg.channel_label ?? "") }
        : emptySlackConfig(),
    );
    setWebhookUrl(row.target_type === "webhook" ? String(cfg.url ?? "") : "");
    setSelectedEvents(new Set(row.subscribed_event_types));
    setFormError(null);
    setModalOpen(true);
  };

  const toggleEvent = (key: string) => {
    setSelectedEvents((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const buildConfigPayload = (): Record<string, unknown> => {
    if (targetType === "email") {
      const o: Record<string, unknown> = {
        recipient_email: emailCfg.recipient_email.trim(),
      };
      if (emailCfg.sender_email.trim()) {
        o.sender_email = emailCfg.sender_email.trim();
      }
      if (emailCfg.subject_prefix.trim()) {
        o.subject_prefix = emailCfg.subject_prefix.trim();
      }
      return o;
    }
    if (targetType === "webhook") {
      return { url: webhookUrl.trim() };
    }
    const o: Record<string, unknown> = { webhook_url: slackCfg.webhook_url.trim() };
    if (slackCfg.channel_label.trim()) {
      o.channel_label = slackCfg.channel_label.trim();
    }
    return o;
  };

  const save = async () => {
    setFormError(null);
    const subs = [...selectedEvents];
    if (subs.length === 0) {
      setFormError("Choose at least one event.");
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        const patch: ExternalNotificationTargetUpdatePayload = {
          name: name.trim(),
          enabled,
          subscribed_event_types: subs,
        };
        const skipSlackUrl = editing.target_type === "slack_webhook" && !slackCfg.webhook_url.trim();
        if (!skipSlackUrl) {
          patch.config_json = buildConfigPayload();
        }
        await apiFetch<ExternalNotificationTargetRecord>(
          `/projects/${projectId}/notification-targets/${editing.id}`,
          { method: "PATCH", body: JSON.stringify(patch) },
        );
      } else {
        const body: ExternalNotificationTargetCreatePayload = {
          name: name.trim(),
          target_type: targetType,
          enabled,
          config_json: buildConfigPayload(),
          subscribed_event_types: subs,
        };
        const made = await apiFetch<ExternalNotificationTargetRecord>(`/projects/${projectId}/notification-targets`, {
          method: "POST",
          body: JSON.stringify(body),
        });
        // In the list at once, not after the refresh, beside its secret.
        setItems((current) => [{ ...made, signing_secret: null }, ...current.filter((item) => item.id !== made.id)]);
        if (made.signing_secret) setFreshSecret({ name: made.name, secret: made.signing_secret });
      }
      setModalOpen(false);
      router.refresh();
    } catch (e) {
      setFormError(extractErrorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const onTest = async (id: string) => {
    setTestingId(id);
    setTestMessage(null);
    try {
      const res = await apiFetch<{ success: boolean; message: string }>(
        `/projects/${projectId}/notification-targets/${id}/test`,
        { method: "POST" },
      );
      setTestMessage(`${res.success ? "Sent" : "Not sent"}: ${res.message}`);
    } catch (e) {
      setTestMessage(extractErrorMessage(e));
    } finally {
      setTestingId(null);
    }
  };

  const newSecret = async (row: ExternalNotificationTargetRecord) => {
    try {
      const rotated = await apiFetch<ExternalNotificationTargetRecord>(
        `/projects/${projectId}/notification-targets/${row.id}/rotate-secret`,
        { method: "POST" },
      );
      if (rotated.signing_secret) setFreshSecret({ name: rotated.name, secret: rotated.signing_secret });
      router.refresh();
    } catch (e) {
      toast.error("Could not make a new secret", extractErrorMessage(e));
    } finally {
      setReplacingId(null);
    }
  };

  const copySecret = async () => {
    if (!freshSecret) return;
    try {
      await navigator.clipboard.writeText(freshSecret.secret);
      toast.success("Copied", "Keep it with your other secrets. It will not be shown again.");
    } catch {
      toast.info("Copy it now", "It will not be shown again.");
    }
  };

  const showDeliveries = async (row: ExternalNotificationTargetRecord) => {
    setDeliveriesFor(row);
    setDeliveries(null);
    try {
      const listed = await apiFetch<WebhookDeliveryListResponse>(
        `/projects/${projectId}/notification-targets/${row.id}/deliveries?limit=25`,
      );
      setDeliveries(listed.items);
    } catch (e) {
      toast.error("Could not load the deliveries", extractErrorMessage(e));
      setDeliveries([]);
    }
  };

  useEffect(() => {
    setItems(initialItems);
  }, [initialItems]);

  return (
    <>
      <AppShell
        currentUser={currentUser}
        title="Alerts"
        subtitle="Send failures and reports to email, Slack or your own systems."
        actions={
          <>
            <Button type="button" onClick={openCreate}>
              Add a channel
            </Button>
          </>
        }
      >
        {freshSecret ? (
          <div className="mb-4 rounded-xl border border-success-line bg-success-soft px-3.5 py-3">
            <div className="text-[13px] font-medium text-success">
              The signing secret for “{freshSecret.name}”. Copy it now; it will not be shown again.
            </div>
            <p className="mt-1 text-[13px] text-ink-2">
              Your system uses it to check each event came from Pipewright.{" "}
              <Link href="/help/api#webhooks" className="underline">
                How to check a signature
              </Link>
            </p>
            <div className="mt-2 flex items-center gap-2">
              <code className="flex-1 overflow-x-auto whitespace-nowrap rounded-lg bg-surface px-2.5 py-1.5 font-mono text-[12px] text-ink">
                {freshSecret.secret}
              </code>
              <Button variant="secondary" size="sm" onClick={() => void copySecret()}>
                Copy
              </Button>
              <Button size="sm" onClick={() => setFreshSecret(null)}>
                Done
              </Button>
            </div>
          </div>
        ) : null}

        {testMessage ? (
          <div className="mb-4 rounded-2xl border border-line bg-surface px-4 py-3 text-sm text-ink">
            {testMessage}
          </div>
        ) : null}

        <SectionPanel
          title="Where alerts go"
          description="Each one receives the kinds of event you choose. If sending fails, the run itself is not affected."
        >
          {items.length === 0 ? (
            <p className="text-sm text-ink-3">
              Nothing set up yet. Everything already appears in your notifications; add an email address, a Slack
              channel or a webhook to get it there too.
            </p>
          ) : (
            <Table minWidth={720}>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Name</TableHeaderCell>
                  <TableHeaderCell>Goes to</TableHeaderCell>
                  <TableHeaderCell>On</TableHeaderCell>
                  <TableHeaderCell>Events</TableHeaderCell>
                  <TableHeaderCell>Changed</TableHeaderCell>
                  <TableHeaderCell>Actions</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="font-medium text-ink">{row.name}</TableCell>
                    <TableCell className="text-ink-3">{channelLabel(row.target_type)}</TableCell>
                    <TableCell className="text-ink-3">{row.enabled ? "Yes" : "No"}</TableCell>
                    <TableCell className="text-ink-3">{row.subscribed_event_types.length}</TableCell>
                    <TableCell className="text-xs text-muted">{formatDate(row.updated_at)}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-2">
                        <Button variant="secondary" size="sm" type="button" onClick={() => openEdit(row)}>
                          Edit
                        </Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          type="button"
                          disabled={testingId === row.id}
                          onClick={() => void onTest(row.id)}
                        >
                          {testingId === row.id ? "Sending…" : "Send a test"}
                        </Button>
                        {row.target_type === "webhook" ? (
                          <>
                            <Button variant="secondary" size="sm" type="button" onClick={() => void showDeliveries(row)}>
                              Deliveries
                            </Button>
                            {replacingId === row.id ? (
                              <span className="inline-flex flex-wrap items-center gap-2">
                                <span className="text-[12px] text-ink-2">The old secret stops at once.</span>
                                <Button variant="danger" size="sm" type="button" onClick={() => void newSecret(row)}>
                                  Replace it
                                </Button>
                                <Button variant="ghost" size="sm" type="button" onClick={() => setReplacingId(null)}>
                                  Keep it
                                </Button>
                              </span>
                            ) : (
                              <Button variant="secondary" size="sm" type="button" onClick={() => setReplacingId(row.id)}>
                                New secret
                              </Button>
                            )}
                          </>
                        ) : null}
                        <DeleteRowButton
                          path={`/projects/${projectId}/notification-targets/${row.id}`}
                          name={row.name}
                          kind="alert channel"
                          consequences={[
                            "Any scheduled report still delivering here must be pointed elsewhere first.",
                          ]}
                          onDeleted={() =>
                            setItems((current) => current.filter((item) => item.id !== row.id))
                          }
                        />
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </SectionPanel>
      </AppShell>

      <Modal
        open={modalOpen}
        title={editing ? "Change this channel" : "Add a channel"}
        description="Choose where it goes and which events it hears about."
        onClose={() => setModalOpen(false)}
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" type="button" onClick={() => setModalOpen(false)}>
              Cancel
            </Button>
            <Button type="button" disabled={saving} onClick={() => void save()}>
              {saving ? "Saving…" : "Save"}
            </Button>
          </div>
        }
      >
        <div className="flex flex-col gap-4">
          {formError ? <p className="text-sm text-danger">{formError}</p> : null}
          <FormField label="Name" htmlFor="nt-name">
            <Input id="nt-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="For example, Operations email" />
          </FormField>
          <FormField label="Send to" htmlFor="nt-type">
            <Select
              id="nt-type"
              value={targetType}
              disabled={Boolean(editing)}
              onChange={(e) => setTargetType(e.target.value as ExternalNotificationTargetType)}
            >
              <option value="email">Email</option>
              <option value="slack_webhook">A Slack channel</option>
              <option value="webhook">A webhook (signed JSON for your own systems)</option>
            </Select>
          </FormField>
          <label className="flex items-center gap-2 text-sm text-ink-2">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            On
          </label>

          {targetType === "email" ? (
            <>
              <FormField label="Send to this address" htmlFor="nt-recipient">
                <Input
                  id="nt-recipient"
                  value={emailCfg.recipient_email}
                  onChange={(e) => setEmailCfg((c) => ({ ...c, recipient_email: e.target.value }))}
                />
              </FormField>
              <FormField
                label="Send from (optional)"
                htmlFor="nt-sender"
                description="Leave empty to send from the platform's own address."
              >
                <Input
                  id="nt-sender"
                  value={emailCfg.sender_email}
                  onChange={(e) => setEmailCfg((c) => ({ ...c, sender_email: e.target.value }))}
                />
              </FormField>
              <FormField label="Start each subject with (optional)" htmlFor="nt-subject">
                <Input
                  id="nt-subject"
                  value={emailCfg.subject_prefix}
                  onChange={(e) => setEmailCfg((c) => ({ ...c, subject_prefix: e.target.value }))}
                  placeholder="[MyOrg]"
                />
              </FormField>
            </>
          ) : targetType === "webhook" ? (
            <FormField
              label="Address that receives the events"
              htmlFor="nt-url"
              description="Each event is sent as signed JSON. After you save, a secret to check signatures with is shown once."
            >
              <Input
                id="nt-url"
                autoComplete="off"
                value={webhookUrl}
                onChange={(e) => setWebhookUrl(e.target.value)}
                placeholder="https://example.com/hooks/pipewright"
              />
            </FormField>
          ) : (
            <>
              <FormField
                label="Slack's webhook address"
                htmlFor="nt-webhook"
                description={
                  editing
                    ? "The saved address is hidden. Leave this empty to keep it, or paste a new one to replace it."
                    : "Make one in Slack under Incoming webhooks; it starts with https://hooks.slack.com/."
                }
              >
                <Input
                  id="nt-webhook"
                  type="password"
                  autoComplete="off"
                  value={slackCfg.webhook_url}
                  onChange={(e) => setSlackCfg((c) => ({ ...c, webhook_url: e.target.value }))}
                  placeholder="https://hooks.slack.com/services/…"
                />
              </FormField>
              <FormField label="Channel name (optional, shown in each message)" htmlFor="nt-channel">
                <Input
                  id="nt-channel"
                  value={slackCfg.channel_label}
                  onChange={(e) => setSlackCfg((c) => ({ ...c, channel_label: e.target.value }))}
                />
              </FormField>
            </>
          )}

          <fieldset>
            <legend className="text-xs text-muted">Send when</legend>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {EXTERNAL_NOTIFICATION_EVENT_TYPES.map((ev) => (
                <label key={ev} className="flex items-center gap-2 text-sm text-ink-2">
                  <input type="checkbox" checked={selectedEvents.has(ev)} onChange={() => toggleEvent(ev)} />
                  {EVENT_LABELS[ev] ?? ev}
                </label>
              ))}
            </div>
          </fieldset>
        </div>
      </Modal>

      <Modal
        open={deliveriesFor !== null}
        title={deliveriesFor ? `Deliveries to “${deliveriesFor.name}”` : "Deliveries"}
        description="The latest events sent, newest first. One that fails is tried twice more, a minute and then five minutes later."
        onClose={() => setDeliveriesFor(null)}
        widthClassName="max-w-3xl"
      >
        {deliveries === null ? (
          <p className="text-sm text-ink-3">Loading…</p>
        ) : deliveries.length === 0 ? (
          <p className="text-sm text-ink-3">Nothing sent yet. Use Send a test to try it.</p>
        ) : (
          <Table minWidth={600}>
            <TableHead>
              <TableRow>
                <TableHeaderCell>When</TableHeaderCell>
                <TableHeaderCell>Event</TableHeaderCell>
                <TableHeaderCell>Result</TableHeaderCell>
                <TableHeaderCell>Tries</TableHeaderCell>
                <TableHeaderCell>Why</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {deliveries.map((delivery) => {
                const outcome = deliveryOutcome(delivery);
                return (
                  <TableRow key={delivery.id}>
                    <TableCell className="text-xs text-muted">{formatDate(delivery.created_at)}</TableCell>
                    <TableCell className="text-ink-2">{EVENT_LABELS[delivery.event_type] ?? delivery.event_type}</TableCell>
                    <TableCell>
                      <Badge tone={outcome.tone}>{outcome.label}</Badge>
                    </TableCell>
                    <TableCell className="text-ink-3">{delivery.attempts}</TableCell>
                    <TableCell className="text-[13px] text-ink-3">{delivery.last_error ?? ""}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Modal>
    </>
  );
}
