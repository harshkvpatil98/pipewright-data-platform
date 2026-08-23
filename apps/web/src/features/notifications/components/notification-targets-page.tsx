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
} from "@platform/shared-types";
import { EXTERNAL_NOTIFICATION_EVENT_TYPES } from "@platform/shared-types";
import { Button, FormField, Input, Modal, SectionPanel, Select } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate, titleCase } from "@/lib/format";

const EVENT_LABELS: Record<string, string> = {
  schedule_run_failed: "Scheduled run failed",
  schedule_run_succeeded: "Scheduled run succeeded",
  dataset_publish_failed: "Dataset publish failed",
  dataset_publish_succeeded: "Dataset publish succeeded",
  transformation_run_failed: "Transformation failed",
  transformation_run_succeeded: "Transformation succeeded",
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

export function NotificationTargetsPageView({
  currentUser,
  projectId,
  initialItems,
}: NotificationTargetsPageViewProps) {
  const router = useRouter();
  const [items, setItems] = useState(initialItems);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ExternalNotificationTargetRecord | null>(null);
  const [name, setName] = useState("");
  const [targetType, setTargetType] = useState<ExternalNotificationTargetType>("email");
  const [enabled, setEnabled] = useState(true);
  const [emailCfg, setEmailCfg] = useState(emptyEmailConfig);
  const [slackCfg, setSlackCfg] = useState(emptySlackConfig);
  const [selectedEvents, setSelectedEvents] = useState<Set<string>>(
    () => new Set([...EXTERNAL_NOTIFICATION_EVENT_TYPES]),
  );
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testMessage, setTestMessage] = useState<string | null>(null);

  const openCreate = () => {
    setEditing(null);
    setName("");
    setTargetType("email");
    setEnabled(true);
    setEmailCfg(emptyEmailConfig());
    setSlackCfg(emptySlackConfig());
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
    if (row.target_type === "email") {
      setEmailCfg({
        recipient_email: String(cfg.recipient_email ?? ""),
        sender_email: String(cfg.sender_email ?? ""),
        subject_prefix: String(cfg.subject_prefix ?? ""),
      });
      setSlackCfg(emptySlackConfig());
    } else {
      setSlackCfg({
        webhook_url: "",
        channel_label: String(cfg.channel_label ?? ""),
      });
      setEmailCfg(emptyEmailConfig());
    }
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
      setFormError("Select at least one event type.");
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
        const skipSlackUrl =
          editing.target_type === "slack_webhook" && !slackCfg.webhook_url.trim();
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
        await apiFetch<ExternalNotificationTargetRecord>(`/projects/${projectId}/notification-targets`, {
          method: "POST",
          body: JSON.stringify(body),
        });
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
      setTestMessage(`${res.success ? "Success" : "Failed"}: ${res.message}`);
    } catch (e) {
      setTestMessage(extractErrorMessage(e));
    } finally {
      setTestingId(null);
    }
  };

  useEffect(() => {
    setItems(initialItems);
  }, [initialItems]);

  return (
    <>
      <AppShell
        currentUser={currentUser}
        eyebrow="Project workspace"
        title="External notification targets"
        subtitle="Optional email and Slack webhook delivery for run outcomes. In-app notifications remain the primary channel; external delivery is best-effort and requires server SMTP env vars for email."
        actions={
          <>
            <Link
              href={`/projects/${projectId}`}
              className="inline-flex items-center rounded-full border border-line bg-surface px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-ink hover:border-line-strong"
            >
              Back to project
            </Link>
            <Button type="button" onClick={openCreate}>
              Create target
            </Button>
          </>
        }
      >
        {testMessage ? (
          <div className="mb-4 rounded-2xl border border-line bg-surface px-4 py-3 text-sm text-ink">
            {testMessage}
          </div>
        ) : null}

        <SectionPanel
          title="Targets"
          description="Each target subscribes to event types. When a matching in-app notification is created, the gateway attempts delivery (failures are logged; they do not fail the pipeline run)."
        >
          {items.length === 0 ? (
            <p className="text-sm text-ink-3">No external targets yet. Create one to forward alerts outside the app.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] border-collapse text-left text-sm text-ink">
                <thead className="border-b border-line text-xs uppercase tracking-[0.14em] text-muted">
                  <tr>
                    <th className="py-2 pr-4 font-medium">Name</th>
                    <th className="py-2 pr-4 font-medium">Type</th>
                    <th className="py-2 pr-4 font-medium">Enabled</th>
                    <th className="py-2 pr-4 font-medium">Events</th>
                    <th className="py-2 pr-4 font-medium">Updated</th>
                    <th className="py-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((row) => (
                    <tr key={row.id} className="border-b border-line">
                      <td className="py-3 pr-4 font-medium text-ink">{row.name}</td>
                      <td className="py-3 pr-4 text-ink-3">{titleCase(row.target_type.replace(/_/g, " "))}</td>
                      <td className="py-3 pr-4 text-ink-3">{row.enabled ? "Yes" : "No"}</td>
                      <td className="py-3 pr-4 text-ink-3">{row.subscribed_event_types.length}</td>
                      <td className="py-3 pr-4 text-xs text-muted">{formatDate(row.updated_at)}</td>
                      <td className="py-3">
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
                            {testingId === row.id ? "Testing…" : "Test"}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </SectionPanel>
      </AppShell>

      <Modal
        open={modalOpen}
        title={editing ? "Edit notification target" : "Create notification target"}
        description="Sensitive fields are masked after save. For Slack, paste a full https webhook URL (stored server-side)."
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
            <Input id="nt-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Ops email" />
          </FormField>
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Target type
            <Select
              value={targetType}
              disabled={Boolean(editing)}
              onChange={(e) => setTargetType(e.target.value as ExternalNotificationTargetType)}
            >
              <option value="email">Email</option>
              <option value="slack_webhook">Slack webhook</option>
            </Select>
          </label>
          <label className="flex items-center gap-2 text-sm text-ink-2">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            Enabled
          </label>

          {targetType === "email" ? (
            <>
              <FormField label="Recipient email" htmlFor="nt-recipient">
                <Input
                  id="nt-recipient"
                  value={emailCfg.recipient_email}
                  onChange={(e) => setEmailCfg((c) => ({ ...c, recipient_email: e.target.value }))}
                />
              </FormField>
              <FormField
                label="Sender email (optional)"
                htmlFor="nt-sender"
                description="Overrides EXTERNAL_NOTIFICATION_SMTP_FROM when set."
              >
                <Input
                  id="nt-sender"
                  value={emailCfg.sender_email}
                  onChange={(e) => setEmailCfg((c) => ({ ...c, sender_email: e.target.value }))}
                />
              </FormField>
              <FormField label="Subject prefix (optional)" htmlFor="nt-subject">
                <Input
                  id="nt-subject"
                  value={emailCfg.subject_prefix}
                  onChange={(e) => setEmailCfg((c) => ({ ...c, subject_prefix: e.target.value }))}
                  placeholder="[MyOrg]"
                />
              </FormField>
            </>
          ) : (
            <>
              <FormField
                label="Webhook URL (https)"
                htmlFor="nt-webhook"
                description={
                  editing
                    ? "Saved URL is redacted. Leave blank to keep the existing webhook; enter a full URL to replace it."
                    : undefined
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
              <FormField label="Channel label (optional, display only)" htmlFor="nt-channel">
                <Input
                  id="nt-channel"
                  value={slackCfg.channel_label}
                  onChange={(e) => setSlackCfg((c) => ({ ...c, channel_label: e.target.value }))}
                />
              </FormField>
            </>
          )}

          <div>
            <div className="text-xs uppercase tracking-[0.16em] text-muted">Subscribed events</div>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {EXTERNAL_NOTIFICATION_EVENT_TYPES.map((ev) => (
                <label key={ev} className="flex items-center gap-2 text-sm text-ink-2">
                  <input type="checkbox" checked={selectedEvents.has(ev)} onChange={() => toggleEvent(ev)} />
                  {EVENT_LABELS[ev] ?? ev}
                </label>
              ))}
            </div>
          </div>
        </div>
      </Modal>
    </>
  );
}
