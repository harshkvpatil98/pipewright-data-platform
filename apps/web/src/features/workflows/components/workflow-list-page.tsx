"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useId, useState } from "react";

import type { AuthUser, WorkflowDetail, WorkflowSummary } from "@platform/shared-types";

import { useToast } from "@/components/providers/toast-provider";
import { AppFrame } from "@/components/shell/app-frame";
import type { RibbonGroup } from "@/components/shell/ribbon";
import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { cx } from "@/lib/utils";

type WorkflowListPageProps = {
  currentUser: AuthUser;
  projectId: string;
  projectName: string;
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
  projectName,
  initialWorkflows,
}: WorkflowListPageProps) {
  const router = useRouter();
  const toast = useToast();
  const fieldId = useId();

  const [workflows, setWorkflows] = useState(initialWorkflows);
  const [creating, setCreating] = useState(false);
  const [showForm, setShowForm] = useState(initialWorkflows.length === 0);
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
      const created = await apiFetch<WorkflowDetail>(`/projects/${projectId}/workflows`, {
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
      });
      toast.success("Workflow created", "Add steps on the canvas.");
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
          { method: "PATCH", body: JSON.stringify({ enabled: !workflow.enabled }) },
        );
        setWorkflows((current) =>
          current.map((item) => (item.id === workflow.id ? { ...item, ...updated } : item)),
        );
        toast.success(updated.enabled ? "Schedule resumed" : "Schedule paused");
      } catch (caught) {
        toast.error("Could not update", extractErrorMessage(caught));
      }
    },
    [projectId, toast],
  );

  const ribbon: RibbonGroup[] = [
    {
      id: "workflows",
      label: "Workflows",
      actions: [
        {
          id: "new",
          label: "New",
          icon: "plus",
          prominent: true,
          onClick: () => setShowForm(true),
        },
      ],
    },
  ];

  const scheduled = workflows.filter((item) => item.trigger_type === "cron" && item.enabled);

  return (
    <AppFrame
      currentUser={currentUser}
      crumbs={[
        { label: "Projects", href: "/projects" },
        { label: projectName, href: `/projects/${projectId}` },
        { label: "Workflows" },
      ]}
      ribbon={ribbon}
      statusItems={[
        { id: "total", label: "Workflows", value: String(workflows.length) },
        { id: "scheduled", label: "Scheduled", value: String(scheduled.length) },
      ]}
    >
      <div className="px-6 py-6 lg:px-8">
        <header className="mb-6 max-w-3xl">
          <div className="mb-2 text-[11px] font-medium uppercase tracking-[0.2em] text-[color:var(--accent-muted)]">
            Automate
          </div>
          <h1 className="text-[26px] font-semibold tracking-tight text-ink">Workflows</h1>
          <p className="mt-2 text-[13px] leading-6 text-ink-3">
            Chain extraction, transformation, quality gates, and publishing into one run. A gate
            that fails stops the steps after it, so bad data never reaches a destination.
          </p>
        </header>

        {showForm ? (
          <section className="mb-6 max-w-2xl rounded-2xl border border-line bg-[color:var(--panel)] p-5">
            <h2 className="text-[14px] font-semibold text-ink">New workflow</h2>
            <div className="mt-4 space-y-3">
              <div>
                <label
                  htmlFor={`${fieldId}-name`}
                  className="mb-1.5 block text-[12px] font-medium text-ink"
                >
                  Name
                </label>
                <input
                  id={`${fieldId}-name`}
                  className={inputClass}
                  value={form.name}
                  placeholder="Nightly invoice load"
                  onChange={(event) => setForm((f) => ({ ...f, name: event.target.value }))}
                />
              </div>

              <div>
                <label
                  htmlFor={`${fieldId}-desc`}
                  className="mb-1.5 block text-[12px] font-medium text-ink"
                >
                  Description
                </label>
                <input
                  id={`${fieldId}-desc`}
                  className={inputClass}
                  value={form.description}
                  placeholder="What this workflow is for"
                  onChange={(event) => setForm((f) => ({ ...f, description: event.target.value }))}
                />
              </div>

              <div>
                <span className="mb-1.5 block text-[12px] font-medium text-ink">Trigger</span>
                <div className="flex rounded-lg border border-line p-0.5">
                  {(["manual", "cron"] as const).map((value) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setForm((f) => ({ ...f, trigger: value }))}
                      className={cx(
                        "flex-1 rounded-md px-3 py-1.5 text-[12px] transition",
                        form.trigger === value
                          ? "bg-[color:var(--accent)] text-accent-ink"
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
                      className="mb-1.5 block text-[12px] font-medium text-ink"
                    >
                      Schedule
                    </label>
                    <input
                      id={`${fieldId}-cron`}
                      className={cx(inputClass, "font-mono")}
                      value={form.cron}
                      onChange={(event) => setForm((f) => ({ ...f, cron: event.target.value }))}
                    />
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {CRON_PRESETS.map((preset) => (
                        <button
                          key={preset.value}
                          type="button"
                          onClick={() => setForm((f) => ({ ...f, cron: preset.value }))}
                          className={cx(
                            "rounded-md px-2 py-1 text-[11px] transition",
                            form.cron === preset.value
                              ? "bg-[color:var(--accent)] text-accent-ink"
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
                      className="mb-1.5 block text-[12px] font-medium text-ink"
                    >
                      Timezone
                    </label>
                    <input
                      id={`${fieldId}-tz`}
                      className={inputClass}
                      value={form.timezone}
                      onChange={(event) => setForm((f) => ({ ...f, timezone: event.target.value }))}
                    />
                    <p className="mt-1.5 text-[11px] text-muted">
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
                  className="inline-flex items-center gap-1.5 rounded-lg bg-[color:var(--accent)] px-3.5 py-2 text-[12.5px] font-medium text-accent-ink transition hover:brightness-110 disabled:opacity-40"
                >
                  {creating ? "Creating…" : "Create workflow"}
                </button>
                {workflows.length > 0 ? (
                  <button
                    type="button"
                    onClick={() => setShowForm(false)}
                    className="rounded-lg border border-line px-3.5 py-2 text-[12.5px] text-ink transition hover:bg-surface-2"
                  >
                    Cancel
                  </button>
                ) : null}
              </div>
            </div>
          </section>
        ) : null}

        <div className="space-y-2">
          {workflows.length === 0 && !showForm ? (
            <p className="rounded-2xl border border-dashed border-line px-4 py-10 text-center text-[13px] text-muted">
              No workflows yet.
            </p>
          ) : (
            workflows.map((workflow) => (
              <article
                key={workflow.id}
                className="group relative flex items-center gap-4 rounded-xl border border-line bg-[color:var(--panel)] px-4 py-3.5 transition hover:border-line-strong"
              >
                <Link
                  href={`/projects/${projectId}/workflows/${workflow.id}`}
                  className="absolute inset-0 z-0 rounded-xl"
                  aria-label={`Open ${workflow.name}`}
                />
                <span className="pointer-events-none flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-line bg-surface text-ink-3">
                  <Icon name="transform" size={16} />
                </span>

                <div className="pointer-events-none min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-[13.5px] font-medium text-ink">
                      {workflow.name}
                    </span>
                    {workflow.trigger_type === "cron" ? (
                      <span className="rounded-full border border-line px-2 py-0.5 font-mono text-[10px] text-ink-3">
                        {workflow.cron_expression}
                      </span>
                    ) : null}
                    {workflow.last_run_status ? (
                      <span
                        className={cx(
                          "rounded-full px-2 py-0.5 text-[10px] uppercase tracking-[0.14em]",
                          workflow.last_run_status === "succeeded"
                            ? "bg-success-soft text-success"
                            : workflow.last_run_status === "failed"
                              ? "bg-danger-soft text-danger"
                              : "bg-warning-soft text-warning",
                        )}
                      >
                        {workflow.last_run_status}
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-0.5 truncate text-[11.5px] text-muted">
                    {workflow.trigger_type === "cron" && workflow.next_run_at
                      ? `Next run ${formatDate(workflow.next_run_at)}`
                      : workflow.last_run_at
                        ? `Last run ${formatDate(workflow.last_run_at)}`
                        : "Never run"}
                    {workflow.execution_count > 0 ? ` · ${workflow.execution_count} run(s)` : ""}
                  </div>
                </div>

                {workflow.trigger_type === "cron" ? (
                  <button
                    type="button"
                    onClick={() => toggleEnabled(workflow)}
                    className="relative z-10 shrink-0 rounded-lg border border-line px-2.5 py-1.5 text-[11.5px] text-ink transition hover:bg-surface-2"
                  >
                    {workflow.enabled ? "Pause" : "Resume"}
                  </button>
                ) : null}

                <Icon
                  name="chevronRight"
                  size={14}
                  className="pointer-events-none shrink-0 text-muted"
                />
              </article>
            ))
          )}
        </div>
      </div>
    </AppFrame>
  );
}
