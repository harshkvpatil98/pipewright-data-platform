"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useId, useState } from "react";

import type {
  AuthUser,
  WorkflowDetail,
  WorkflowSummary,
} from "@platform/shared-types";
import { Button, EmptyState, Modal, StatusBadge } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { useToast } from "@/components/providers/toast-provider";
import { RuntimeBanner } from "@/components/ui/runtime-banner";
import { describeCron } from "@/lib/cron-words";
import { humanDuration } from "@/lib/runtime-health";
import { Icon } from "@/components/ui/icon";
import { DeleteRowButton } from "@/components/ui/delete-row-button";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { cx } from "@/lib/utils";

type WorkflowListPageProps = {
  currentUser: AuthUser;
  projectId: string;
  initialWorkflows: WorkflowSummary[];
};

const inputClass =
  "h-9 w-full rounded-lg border border-line bg-sunken px-2.5 text-[13px] text-ink outline-none transition placeholder:text-faint focus:border-[color:var(--accent)] focus:ring-2 focus:ring-[color:var(--accent-soft)]";

const CRON_PRESETS = [
  { label: "Every 15 minutes", value: "*/15 * * * *" },
  { label: "Hourly", value: "0 * * * *" },
  { label: "Daily at 06:00", value: "0 6 * * *" },
  { label: "Weekdays at 07:00", value: "0 7 * * 1-5" },
  { label: "Weekly on Monday", value: "0 6 * * 1" },
];

export function WorkflowListPage({
  currentUser,
  projectId,
  initialWorkflows,
}: WorkflowListPageProps) {
  const router = useRouter();
  const toast = useToast();
  const fieldId = useId();

  const [workflows, setWorkflows] = useState(initialWorkflows);
  const [creating, setCreating] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: "",
    description: "",
    trigger: "manual" as "manual" | "cron",
    cron: "0 6 * * *",
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  });

  const create = useCallback(async () => {
    setCreating(true);
    try {
      const created = await apiFetch<WorkflowDetail>(
        `/projects/${projectId}/workflows`,
        {
          method: "POST",
          body: JSON.stringify({
            name: form.name,
            description: form.description || null,
            trigger_type: form.trigger,
            cron_expression: form.trigger === "cron" ? form.cron : null,
            timezone: form.trigger === "cron" ? form.timezone : null,
            nodes: [],
            edges: [],
          }),
        },
      );
      toast.success("Workflow created", "Add its tasks on the canvas.");
      router.push(`/projects/${projectId}/workflows/${created.id}`);
    } catch (caught) {
      toast.error("Could not create the workflow", extractErrorMessage(caught));
      setCreating(false);
    }
  }, [projectId, form, toast, router]);

  const toggleEnabled = useCallback(
    async (workflow: WorkflowSummary) => {
      try {
        const updated = await apiFetch<WorkflowDetail>(
          `/projects/${projectId}/workflows/${workflow.id}`,
          {
            method: "PATCH",
            body: JSON.stringify({ enabled: !workflow.enabled }),
          },
        );
        setWorkflows((current) =>
          current.map((item) =>
            item.id === workflow.id ? { ...item, ...updated } : item,
          ),
        );
        toast.success(updated.enabled ? "Schedule resumed" : "Schedule paused");
      } catch (caught) {
        toast.error("Could not update", extractErrorMessage(caught));
      }
    },
    [projectId, toast],
  );

  return (
    <AppShell
      currentUser={currentUser}
      title="Workflows"
      subtitle="Tasks that run in order, by hand or on a schedule."
      actions={
        workflows.length > 0 ? (
          <Button onClick={() => setShowForm(true)}>New workflow</Button>
        ) : undefined
      }
    >
      <RuntimeBanner />
      <Modal
        open={showForm}
        title="New workflow"
        description="Name it and say when it runs. You add its tasks on the next screen."
        onClose={() => setShowForm(false)}
        widthClassName="max-w-lg"
      >
        <div className="space-y-4">
          <div>
            <label
              htmlFor={`${fieldId}-name`}
              className="text-ink mb-1.5 block text-[12px] font-medium"
            >
              Name
            </label>
            <input
              id={`${fieldId}-name`}
              className={inputClass}
              value={form.name}
              placeholder="Nightly invoice load"
              onChange={(event) =>
                setForm((f) => ({ ...f, name: event.target.value }))
              }
            />
          </div>

          <div>
            <label
              htmlFor={`${fieldId}-desc`}
              className="text-ink mb-1.5 block text-[12px] font-medium"
            >
              Description
            </label>
            <input
              id={`${fieldId}-desc`}
              className={inputClass}
              value={form.description}
              placeholder="What this workflow is for"
              onChange={(event) =>
                setForm((f) => ({ ...f, description: event.target.value }))
              }
            />
          </div>

          <div>
            <span className="text-ink mb-1.5 block text-[12px] font-medium">
              Trigger
            </span>
            <div className="border-line flex rounded-lg border p-0.5">
              {(["manual", "cron"] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setForm((f) => ({ ...f, trigger: value }))}
                  className={cx(
                    "flex-1 rounded-md px-3 py-1.5 text-[12px] transition",
                    form.trigger === value
                      ? "text-accent-ink bg-[color:var(--accent)]"
                      : "text-ink-3 hover:text-ink",
                  )}
                >
                  {value === "manual" ? "Run by hand" : "On a schedule"}
                </button>
              ))}
            </div>
          </div>

          {form.trigger === "cron" ? (
            <>
              <div>
                <label
                  htmlFor={`${fieldId}-cron`}
                  className="text-ink mb-1.5 block text-[12px] font-medium"
                >
                  Schedule
                </label>
                <input
                  id={`${fieldId}-cron`}
                  className={cx(inputClass, "font-mono")}
                  value={form.cron}
                  onChange={(event) =>
                    setForm((f) => ({ ...f, cron: event.target.value }))
                  }
                />
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {CRON_PRESETS.map((preset) => (
                    <button
                      key={preset.value}
                      type="button"
                      onClick={() =>
                        setForm((f) => ({ ...f, cron: preset.value }))
                      }
                      className={cx(
                        "rounded-md px-2 py-1 text-[12px] transition",
                        form.cron === preset.value
                          ? "text-accent-ink bg-[color:var(--accent)]"
                          : "bg-surface-2 text-ink-2 hover:bg-surface-2",
                      )}
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label
                  htmlFor={`${fieldId}-tz`}
                  className="text-ink mb-1.5 block text-[12px] font-medium"
                >
                  Timezone
                </label>
                <input
                  id={`${fieldId}-tz`}
                  className={inputClass}
                  value={form.timezone}
                  onChange={(event) =>
                    setForm((f) => ({ ...f, timezone: event.target.value }))
                  }
                />
                <p className="text-muted mt-1.5 text-[12px]">
                  The schedule follows this zone, including daylight saving.
                </p>
              </div>
            </>
          ) : null}

          <div className="flex gap-2 pt-1">
            <button
              type="button"
              onClick={create}
              disabled={creating || form.name.trim().length < 2}
              className="text-accent-ink inline-flex items-center gap-1.5 rounded-lg bg-[color:var(--accent)] px-3.5 py-2 text-[12.5px] font-medium transition hover:brightness-110 disabled:opacity-40"
            >
              {creating ? "Creating…" : "Create workflow"}
            </button>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="border-line text-ink hover:bg-surface-2 rounded-lg border px-3.5 py-2 text-[13px] transition"
            >
              Cancel
            </button>
          </div>
        </div>
      </Modal>

      <div className="space-y-2">
        {workflows.length === 0 ? (
          <EmptyState
            title="No workflows yet"
            description="A workflow runs several things in order: import a table, clean it, check it, then deliver it. If a check fails, the steps after it stop."
            action={
              <Button onClick={() => setShowForm(true)}>New workflow</Button>
            }
          />
        ) : (
          workflows.map((workflow) => (
            <article
              key={workflow.id}
              className="group border-line hover:border-line-strong relative flex items-center gap-4 rounded-xl border bg-[color:var(--panel)] px-4 py-3.5 transition"
            >
              <Link
                href={`/projects/${projectId}/workflows/${workflow.id}`}
                className="absolute inset-0 z-0 rounded-xl"
                aria-label={`Open ${workflow.name}`}
              />
              <span className="border-line bg-surface text-ink-3 pointer-events-none flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border">
                <Icon name="transform" size={16} />
              </span>

              <div className="pointer-events-none min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-ink truncate text-[14px] font-medium">
                    {workflow.name}
                  </span>
                  {workflow.trigger_type === "cron" &&
                  workflow.cron_expression ? (
                    <span
                      className="border-line text-ink-3 rounded-full border px-2 py-0.5 text-[12px]"
                      title={workflow.cron_expression}
                    >
                      {describeCron(workflow.cron_expression)}
                      {workflow.enabled ? "" : " · paused"}
                    </span>
                  ) : null}
                  {workflow.last_run_status ? (
                    <StatusBadge value={workflow.last_run_status} />
                  ) : null}
                  {workflow.last_run_status === "queued" &&
                  workflow.last_run_at ? (
                    <span className="text-warning text-[12px]">
                      waiting{" "}
                      {humanDuration(
                        Date.now() - Date.parse(workflow.last_run_at),
                      )}
                    </span>
                  ) : null}
                </div>
                <div className="text-muted mt-0.5 truncate text-[13px]">
                  {workflow.trigger_type === "cron" && workflow.next_run_at
                    ? `Next run ${formatDate(workflow.next_run_at)}`
                    : workflow.last_run_at
                      ? `Last run ${formatDate(workflow.last_run_at)}`
                      : "Never run"}
                  {workflow.execution_count > 0
                    ? ` · run ${workflow.execution_count} time${workflow.execution_count === 1 ? "" : "s"}`
                    : ""}
                </div>
              </div>

              {workflow.trigger_type === "cron" ? (
                <button
                  type="button"
                  onClick={() => toggleEnabled(workflow)}
                  className="border-line text-ink hover:bg-surface-2 relative z-10 shrink-0 rounded-lg border px-2.5 py-1.5 text-[13px] transition"
                >
                  {workflow.enabled ? "Pause" : "Resume"}
                </button>
              ) : null}

              <DeleteRowButton
                path={`/projects/${projectId}/workflows/${workflow.id}`}
                name={workflow.name}
                kind="workflow"
                consequences={[
                  "Its run history stays; the workflow definition stops existing.",
                ]}
                onDeleted={() =>
                  setWorkflows((current) =>
                    current.filter((item) => item.id !== workflow.id),
                  )
                }
                className="border-line text-muted hover:border-danger-line hover:text-danger relative z-10 shrink-0 rounded-lg border p-1.5 transition"
              />

              <Icon
                name="chevronRight"
                size={14}
                className="text-muted pointer-events-none shrink-0"
              />
            </article>
          ))
        )}
      </div>
    </AppShell>
  );
}
