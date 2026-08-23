"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import type {
  AuthUser,
  DatasetListResponse,
  DestinationListResponse,
  ScheduledOperationRecord,
  ScheduleCreatePayload,
  ScheduleTriggerResponse,
  ScheduleType,
  ScheduleUpdatePayload,
  TransformationPipelineListResponse,
} from "@platform/shared-types";
import { Button, FormField, Input, Modal, SectionPanel, Select, Textarea } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { OperationalEmpty, OperationalError } from "@/components/operational/operational-messages";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { formatRunStatusLabel } from "@/lib/run-labels";

type SchedulesPageViewProps = {
  currentUser: AuthUser;
  projectId: string;
  initialItems: ScheduledOperationRecord[];
  /** Open create modal on load (e.g. from entry-point links). */
  initialOpenCreate?: boolean;
  initialScheduleType?: ScheduleType | null;
  initialPipelineId?: string | null;
  initialDatasetId?: string | null;
};

function scheduleTypeLabel(t: ScheduleType): string {
  if (t === "transformation_pipeline_run") {
    return "Transformation pipeline";
  }
  return "PostgreSQL publish";
}

/** Automatic-run lease only; manual Trigger now clears these fields after completion. */
function scheduleLeaseLabel(row: ScheduledOperationRecord): string {
  const expRaw = row.claim_expires_at;
  const owner = row.claim_owner_id;
  if (!expRaw && !owner) {
    return "Idle";
  }
  const expMs = expRaw ? new Date(expRaw).getTime() : null;
  const tail = owner && owner.length > 6 ? `…${owner.slice(-6)}` : owner || "—";
  if (expMs != null && !Number.isNaN(expMs)) {
    if (expMs > Date.now()) {
      return `Claimed (${tail})`;
    }
    return "Stale";
  }
  return owner ? `Claimed (${tail})` : "Idle";
}

export function SchedulesPageView({
  currentUser,
  projectId,
  initialItems,
  initialOpenCreate = false,
  initialScheduleType = null,
  initialPipelineId = null,
  initialDatasetId = null,
}: SchedulesPageViewProps) {
  const router = useRouter();
  const [items, setItems] = useState(initialItems);
  const [modalOpen, setModalOpen] = useState(initialOpenCreate);
  const [editing, setEditing] = useState<ScheduledOperationRecord | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [scheduleType, setScheduleType] = useState<ScheduleType>(
    initialScheduleType ?? "transformation_pipeline_run",
  );
  const [cronExpression, setCronExpression] = useState("0 9 * * *");
  const [timezone, setTimezone] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [pipelineId, setPipelineId] = useState(initialPipelineId ?? "");
  const [datasetId, setDatasetId] = useState(initialDatasetId ?? "");
  const [destinationId, setDestinationId] = useState("");
  const [tableName, setTableName] = useState("");
  const [writeMode, setWriteMode] = useState<"replace" | "append">("append");
  const [pipelines, setPipelines] = useState<TransformationPipelineListResponse["items"]>([]);
  const [datasets, setDatasets] = useState<DatasetListResponse["items"]>([]);
  const [destinations, setDestinations] = useState<DestinationListResponse["items"]>([]);
  const [loadingRefs, setLoadingRefs] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [triggeringId, setTriggeringId] = useState<string | null>(null);
  const [triggerMessage, setTriggerMessage] = useState<string | null>(null);
  const [triggerRunId, setTriggerRunId] = useState<string | null>(null);

  useEffect(() => {
    setItems(initialItems);
  }, [initialItems]);

  useEffect(() => {
    if (!modalOpen) {
      return;
    }
    let cancelled = false;
    (async () => {
      setLoadingRefs(true);
      setFormError(null);
      try {
        const [pl, ds, dest] = await Promise.all([
          apiFetch<TransformationPipelineListResponse>(`/projects/${projectId}/pipelines`),
          apiFetch<DatasetListResponse>(`/projects/${projectId}/datasets`),
          apiFetch<DestinationListResponse>(`/projects/${projectId}/destinations`),
        ]);
        if (cancelled) {
          return;
        }
        setPipelines(pl.items);
        setDatasets(ds.items);
        const pg = dest.items.filter((d) => d.destination_type === "postgres" && d.status === "active");
        setDestinations(pg);
        if (!editing) {
          setPipelineId((prev) => prev || initialPipelineId || pl.items[0]?.id || "");
          setDatasetId((prev) => prev || initialDatasetId || ds.items[0]?.id || "");
          setDestinationId((prev) => prev || pg[0]?.id || "");
        }
      } catch (e) {
        if (!cancelled) {
          setFormError(extractErrorMessage(e));
        }
      } finally {
        if (!cancelled) {
          setLoadingRefs(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [modalOpen, projectId, editing, initialPipelineId, initialDatasetId]);

  useEffect(() => {
    if (initialOpenCreate) {
      setModalOpen(true);
    }
  }, [initialOpenCreate]);

  useEffect(() => {
    if (initialScheduleType) {
      setScheduleType(initialScheduleType);
    }
  }, [initialScheduleType]);

  function resetForm() {
    setEditing(null);
    setName("");
    setDescription("");
    setScheduleType(initialScheduleType ?? "transformation_pipeline_run");
    setCronExpression("0 9 * * *");
    setTimezone("");
    setEnabled(true);
    setPipelineId(initialPipelineId ?? "");
    setDatasetId(initialDatasetId ?? "");
    setDestinationId("");
    setTableName("");
    setWriteMode("append");
    setFormError(null);
  }

  function openCreate() {
    resetForm();
    setModalOpen(true);
  }

  function openEdit(row: ScheduledOperationRecord) {
    setEditing(row);
    setName(row.name);
    setDescription(row.description ?? "");
    setScheduleType(row.schedule_type);
    setCronExpression(row.cron_expression);
    setTimezone(row.timezone ?? "");
    setEnabled(row.enabled);
    const cfg = row.target_config_json;
    if (row.schedule_type === "transformation_pipeline_run") {
      setPipelineId(String(cfg.pipeline_id ?? ""));
    } else {
      setDatasetId(String(cfg.dataset_id ?? ""));
      setDestinationId(String(cfg.destination_id ?? ""));
      setTableName(String(cfg.table_name ?? ""));
      setWriteMode(cfg.write_mode === "replace" ? "replace" : "append");
    }
    setFormError(null);
    setModalOpen(true);
  }

  const targetConfig = useMemo(() => {
    if (scheduleType === "transformation_pipeline_run") {
      return { pipeline_id: pipelineId };
    }
    return {
      dataset_id: datasetId,
      destination_id: destinationId,
      table_name: tableName.trim(),
      write_mode: writeMode,
    };
  }, [scheduleType, pipelineId, datasetId, destinationId, tableName, writeMode]);

  async function submitForm() {
    setFormError(null);
    if (!name.trim()) {
      setFormError("Name is required.");
      return;
    }
    if (!cronExpression.trim()) {
      setFormError("Cron expression is required.");
      return;
    }
    if (scheduleType === "transformation_pipeline_run" && !pipelineId) {
      setFormError("Select a pipeline.");
      return;
    }
    if (scheduleType === "postgres_publish") {
      if (!datasetId || !destinationId || !tableName.trim()) {
        setFormError("Dataset, destination, and table name are required.");
        return;
      }
    }

    setSaving(true);
    try {
      if (editing) {
        const payload: ScheduleUpdatePayload = {
          name: name.trim(),
          description: description.trim() || null,
          cron_expression: cronExpression.trim(),
          timezone: timezone.trim() || null,
          enabled,
          target_config: targetConfig,
        };
        await apiFetch<ScheduledOperationRecord>(`/projects/${projectId}/schedules/${editing.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      } else {
        const payload: ScheduleCreatePayload = {
          name: name.trim(),
          description: description.trim() || null,
          schedule_type: scheduleType,
          cron_expression: cronExpression.trim(),
          timezone: timezone.trim() || null,
          enabled,
          target_config: targetConfig,
        };
        await apiFetch<ScheduledOperationRecord>(`/projects/${projectId}/schedules`, {
          method: "POST",
          body: JSON.stringify(payload),
        });
      }
      setModalOpen(false);
      resetForm();
      router.refresh();
    } catch (e) {
      setFormError(extractErrorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  async function onToggle(row: ScheduledOperationRecord, next: boolean) {
    setFormError(null);
    try {
      await apiFetch<ScheduledOperationRecord>(`/projects/${projectId}/schedules/${row.id}/toggle`, {
        method: "POST",
        body: JSON.stringify({ enabled: next }),
      });
      router.refresh();
    } catch (e) {
      setFormError(extractErrorMessage(e));
    }
  }

  async function onTrigger(row: ScheduledOperationRecord) {
    setTriggerMessage(null);
    setTriggerRunId(null);
    setFormError(null);
    setTriggeringId(row.id);
    try {
      const res = await apiFetch<ScheduleTriggerResponse>(
        `/projects/${projectId}/schedules/${row.id}/trigger-now`,
        { method: "POST" },
      );
      setTriggerMessage(res.message);
      setTriggerRunId(res.triggered_run?.id ?? null);
      router.refresh();
    } catch (e) {
      setFormError(extractErrorMessage(e));
    } finally {
      setTriggeringId(null);
    }
  }

  return (
    <>
      <AppShell
        currentUser={currentUser}
        eyebrow="Project workspace"
        title="Schedules"
        subtitle="Save recurrence rules for transformation runs and PostgreSQL publishes. The due-schedule executor (CLI or internal API) runs enabled schedules when next_run_at is due; use Trigger now for immediate manual runs without advancing the cron slot."
        actions={
          <>
            <Link
              href={`/projects/${projectId}`}
              className="inline-flex h-11 items-center justify-center rounded-xl border border-line bg-surface-2 px-4 text-sm font-medium text-ink transition hover:border-line-strong hover:bg-surface-2"
            >
              Back to project
            </Link>
            <Button type="button" onClick={openCreate}>
              Create schedule
            </Button>
          </>
        }
      >
        {formError && !modalOpen ? (
          <div className="mb-4">
            <OperationalError title="Schedule action failed" message={formError} />
          </div>
        ) : null}
        {triggerMessage ? (
          <div className="mb-4 rounded-2xl border border-success-line bg-success-soft px-4 py-4 text-sm text-success shadow-[var(--shadow-md)]">
            <p>{triggerMessage}</p>
            {triggerRunId ? (
              <Link
                href={`/projects/${projectId}/runs/${triggerRunId}/audit`}
                className="mt-2 inline-block text-xs font-medium text-accent underline underline-offset-4"
              >
                View run audit
              </Link>
            ) : null}
          </div>
        ) : null}

        <SectionPanel
          title="Saved schedules"
          description="Cron uses the standard five-field form. Automatic runs take a short DB lease so concurrent schedulers are less likely to double-execute the same due slot; stale leases become reclaimable when they expire. Manual Trigger now clears any lease metadata and does not advance the cron slot."
        >
          {items.length === 0 ? (
            <OperationalEmpty description="No schedules yet. Create one to run a transformation pipeline or PostgreSQL publish on a cron; ensure the due-schedule executor runs for automatic execution." />
          ) : (
            <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[1100px] border-collapse text-left text-sm text-ink">
                  <thead className="border-b border-line text-xs uppercase tracking-[0.14em] text-muted">
                    <tr>
                      <th className="py-2 pr-3 font-medium">Name</th>
                      <th className="py-2 pr-3 font-medium">Type</th>
                      <th className="py-2 pr-3 font-medium">Cron</th>
                      <th className="py-2 pr-3 font-medium">Enabled</th>
                      <th className="py-2 pr-3 font-medium">Next run</th>
                      <th className="py-2 pr-3 font-medium">Retry</th>
                      <th className="py-2 pr-3 font-medium">Next retry</th>
                      <th className="py-2 pr-3 font-medium">Auto lease</th>
                      <th className="py-2 pr-3 font-medium">Last failure</th>
                      <th className="py-2 pr-3 font-medium">Last status</th>
                      <th className="py-2 pr-3 font-medium">Last finished</th>
                      <th className="py-2 pr-3 font-medium">Last triggered</th>
                      <th className="py-2 text-right font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((row) => (
                      <tr key={row.id} className="border-b border-line transition hover:bg-surface">
                        <td className="py-2 pr-3 font-medium text-ink">{row.name}</td>
                        <td className="py-2 pr-3 text-ink-3">{scheduleTypeLabel(row.schedule_type)}</td>
                        <td className="py-2 pr-3 font-mono text-xs text-ink-2">{row.cron_expression}</td>
                        <td className="py-2 pr-3">
                          <span
                            className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] ${
                              row.enabled
                                ? "border-success-line bg-success-soft text-success"
                                : "border-line bg-surface-2 text-ink-2"
                            }`}
                          >
                            {row.enabled ? "Enabled" : "Disabled"}
                          </span>
                        </td>
                        <td className="py-2 pr-3 text-ink-3">
                          {row.next_run_at ? formatDate(row.next_run_at) : "—"}
                        </td>
                        <td className="py-2 pr-3 font-mono text-xs text-ink-3">
                          {row.retry_count_current}/{row.max_retries}
                        </td>
                        <td className="py-2 pr-3 text-ink-3">
                          {row.next_retry_at ? formatDate(row.next_retry_at) : "—"}
                        </td>
                        <td className="py-2 pr-3 text-ink-3" title={row.claim_expires_at ?? undefined}>
                          <span className="text-xs">{scheduleLeaseLabel(row)}</span>
                          {row.claim_expires_at ? (
                            <div className="mt-0.5 font-mono text-[11px] text-muted">
                              until {formatDate(row.claim_expires_at)}
                            </div>
                          ) : null}
                        </td>
                        <td className="py-2 pr-3 text-ink-3">
                          {row.last_failure_at ? formatDate(row.last_failure_at) : "—"}
                        </td>
                        <td className="py-2 pr-3 text-ink-2">{formatRunStatusLabel(row.last_run_status)}</td>
                        <td className="py-2 pr-3 text-ink-3">
                          {row.last_run_finished_at ? formatDate(row.last_run_finished_at) : "—"}
                        </td>
                        <td className="py-2 pr-3 text-ink-3">
                          {row.last_triggered_at ? formatDate(row.last_triggered_at) : "—"}
                        </td>
                        <td className="py-2 text-right">
                          <div className="flex flex-wrap justify-end gap-2">
                            <Button
                              type="button"
                              variant="secondary"
                              size="sm"
                              onClick={() => onTrigger(row)}
                              disabled={triggeringId === row.id}
                            >
                              {triggeringId === row.id ? "Running…" : "Trigger now"}
                            </Button>
                            <Button type="button" variant="secondary" size="sm" onClick={() => openEdit(row)}>
                              Edit
                            </Button>
                            <Button
                              type="button"
                              variant="secondary"
                              size="sm"
                              onClick={() => onToggle(row, !row.enabled)}
                            >
                              {row.enabled ? "Disable" : "Enable"}
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </SectionPanel>
      </AppShell>

      <Modal
        open={modalOpen}
        onClose={() => {
          setModalOpen(false);
          resetForm();
        }}
        title={editing ? "Edit schedule" : "Create schedule"}
        description="Automatic runs require the run-due-schedules job or internal API. Trigger now runs the saved operation immediately and updates last-run metadata without advancing the cron slot."
      >
        <div className="space-y-4">
          <FormField label="Schedule type" htmlFor="sched-type">
            <Select
              id="sched-type"
              value={scheduleType}
              onChange={(e) => setScheduleType(e.target.value as ScheduleType)}
              disabled={!!editing}
            >
              <option value="transformation_pipeline_run">Transformation pipeline run</option>
              <option value="postgres_publish">PostgreSQL publish</option>
            </Select>
          </FormField>

          <FormField label="Name" htmlFor="sched-name">
            <Input id="sched-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Nightly customer export" />
          </FormField>
          <FormField label="Description" htmlFor="sched-desc">
            <Textarea id="sched-desc" value={description} onChange={(e) => setDescription(e.target.value)} rows={2} />
          </FormField>
          <FormField label="Cron expression" htmlFor="sched-cron">
            <Input
              id="sched-cron"
              value={cronExpression}
              onChange={(e) => setCronExpression(e.target.value)}
              placeholder="0 9 * * *"
              className="font-mono text-xs"
            />
          </FormField>
          <FormField label="Timezone (optional)" htmlFor="sched-tz">
            <Input id="sched-tz" value={timezone} onChange={(e) => setTimezone(e.target.value)} placeholder="UTC" />
          </FormField>
          <FormField label="Enabled" htmlFor="sched-en">
            <Select id="sched-en" value={enabled ? "yes" : "no"} onChange={(e) => setEnabled(e.target.value === "yes")}>
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </Select>
          </FormField>

          {scheduleType === "transformation_pipeline_run" ? (
            <FormField label="Pipeline" htmlFor="sched-pipeline">
              <Select
                id="sched-pipeline"
                value={pipelineId}
                onChange={(e) => setPipelineId(e.target.value)}
                disabled={loadingRefs}
              >
                {pipelines.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            </FormField>
          ) : (
            <>
              <FormField label="Dataset" htmlFor="sched-ds">
                <Select
                  id="sched-ds"
                  value={datasetId}
                  onChange={(e) => setDatasetId(e.target.value)}
                  disabled={loadingRefs}
                >
                  {datasets.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField label="PostgreSQL destination" htmlFor="sched-dest">
                <Select
                  id="sched-dest"
                  value={destinationId}
                  onChange={(e) => setDestinationId(e.target.value)}
                  disabled={loadingRefs}
                >
                  {destinations.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField label="Table name" htmlFor="sched-table">
                <Input id="sched-table" value={tableName} onChange={(e) => setTableName(e.target.value)} placeholder="clean_customers" />
              </FormField>
              <FormField label="Write mode" htmlFor="sched-wm">
                <Select id="sched-wm" value={writeMode} onChange={(e) => setWriteMode(e.target.value as "replace" | "append")}>
                  <option value="append">Append (create table if missing)</option>
                  <option value="replace">Replace (overwrite table)</option>
                </Select>
              </FormField>
              {writeMode === "replace" ? (
                <p className="text-xs text-warning">Replace mode overwrites the target table when triggered.</p>
              ) : null}
            </>
          )}

          {formError ? <p className="text-sm text-danger">{formError}</p> : null}

          <div className="flex justify-end gap-2 pt-2">
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                setModalOpen(false);
                resetForm();
              }}
            >
              Cancel
            </Button>
            <Button type="button" onClick={() => void submitForm()} disabled={saving || loadingRefs}>
              {saving ? "Saving…" : editing ? "Save" : "Create"}
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
