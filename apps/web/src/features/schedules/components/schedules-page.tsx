"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import type {
  AuthUser,
  DatasetListResponse,
  DestinationListResponse,
  ExtractionConnection,
  ExtractionConnectionListResponse,
  ScheduledOperationRecord,
  ScheduleCreatePayload,
  ScheduleTriggerResponse,
  ScheduleType,
  ScheduleUpdatePayload,
  TransformationPipelineListResponse,
} from "@platform/shared-types";
import {
  Button,
  EmptyState,
  FormField,
  Input,
  Modal,
  SectionPanel,
  Select,
  StatusBadge,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
  Textarea,
} from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { RuntimeBanner } from "@/components/ui/runtime-banner";
import { DeleteRowButton } from "@/components/ui/delete-row-button";
import { OperationalError } from "@/components/operational/operational-messages";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { describeCron } from "@/lib/cron-words";
import { SCHEDULES_TOUR_ID, schedulesTour } from "@/components/tour/tours";
import { useTour } from "@/components/tour/tour-provider";

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
    return "Runs a recipe";
  }
  if (t === "connector_schema_watch") {
    return "Watches for schema changes";
  }
  return "Delivers to PostgreSQL";
}

/** True while a worker holds this schedule's automatic run. */
function isRunningNow(row: ScheduledOperationRecord): boolean {
  if (!row.claim_expires_at) return false;
  const expires = new Date(row.claim_expires_at).getTime();
  return !Number.isNaN(expires) && expires > Date.now();
}

/**
 * Nobody should need to know cron to say "every morning at nine". The presets
 * write the expression; Custom exposes it exactly as before.
 */
const CRON_PRESETS: { label: string; expression: string }[] = [
  { label: "Every hour, on the hour", expression: "0 * * * *" },
  { label: "Every day at 09:00", expression: "0 9 * * *" },
  { label: "Every Monday at 09:00", expression: "0 9 * * 1" },
  { label: "First of the month at 09:00", expression: "0 9 1 * *" },
];

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
  // "Something else…" chosen: show the timetable box even if it happens to
  // match a preset while being typed.
  const [customTimetable, setCustomTimetable] = useState(false);
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
  const [connectionId, setConnectionId] = useState("");
  const [connections, setConnections] = useState<ExtractionConnection[]>([]);
  const [loadingRefs, setLoadingRefs] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [triggeringId, setTriggeringId] = useState<string | null>(null);
  const [triggerMessage, setTriggerMessage] = useState<string | null>(null);
  const [triggerRunId, setTriggerRunId] = useState<string | null>(null);

  const { startIfUnseen } = useTour();
  useEffect(() => {
    const timer = setTimeout(() => startIfUnseen(schedulesTour, SCHEDULES_TOUR_ID), 900);
    return () => clearTimeout(timer);
  }, [startIfUnseen]);

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
        const [pl, ds, dest, conns] = await Promise.all([
          apiFetch<TransformationPipelineListResponse>(`/projects/${projectId}/pipelines`),
          apiFetch<DatasetListResponse>(`/projects/${projectId}/datasets`),
          apiFetch<DestinationListResponse>(`/projects/${projectId}/destinations`),
          apiFetch<ExtractionConnectionListResponse>(
            `/projects/${projectId}/extraction/connections`,
          ),
        ]);
        if (cancelled) {
          return;
        }
        setPipelines(pl.items);
        setDatasets(ds.items);
        setConnections(conns.items);
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
    setCustomTimetable(false);
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
    } else if (row.schedule_type === "connector_schema_watch") {
      setConnectionId(String(cfg.connection_id ?? ""));
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
    if (scheduleType === "connector_schema_watch") {
      // Blank means every connection in the project, which is what a nightly
      // watch should do; naming one narrows it to a single source.
      return connectionId ? { connection_id: connectionId } : {};
    }
    return {
      dataset_id: datasetId,
      destination_id: destinationId,
      table_name: tableName.trim(),
      write_mode: writeMode,
    };
  }, [scheduleType, pipelineId, connectionId, datasetId, destinationId, tableName, writeMode]);

  async function submitForm() {
    setFormError(null);
    if (!name.trim()) {
      setFormError("Give the schedule a name.");
      return;
    }
    if (!cronExpression.trim()) {
      setFormError("Choose when it runs.");
      return;
    }
    if (scheduleType === "transformation_pipeline_run" && !pipelineId) {
      setFormError("Choose a recipe to run.");
      return;
    }
    if (scheduleType === "postgres_publish") {
      if (!datasetId || !destinationId || !tableName.trim()) {
        setFormError("Choose a dataset, a destination and a table name.");
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
        title="Schedules"
        subtitle="Run recipes and deliveries by themselves, at the times you choose."
        actions={
          <Button type="button" onClick={openCreate} data-tour="schedules-create">
            New schedule
          </Button>
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
                See the run
              </Link>
            ) : null}
          </div>
        ) : null}

        <RuntimeBanner />
        <div data-tour="schedules-list">
        <SectionPanel
          title={`${items.length} schedule${items.length === 1 ? "" : "s"}`}
          description="Each runs by itself at its times. Run now tries it straight away without changing its timetable."
          contentClassName={items.length === 0 ? undefined : "px-0 py-0"}
        >
          {items.length === 0 ? (
            <EmptyState
              title="Nothing is scheduled yet"
              description="Put a recipe or a delivery on a timetable, such as every morning at nine."
              action={
                <Button size="sm" onClick={openCreate}>
                  New schedule
                </Button>
              }
            />
          ) : (
            <Table minWidth={880} edge="panel">
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Schedule</TableHeaderCell>
                  <TableHeaderCell>When</TableHeaderCell>
                  <TableHeaderCell>Next run</TableHeaderCell>
                  <TableHeaderCell>Last run</TableHeaderCell>
                  <TableHeaderCell className="text-right">
                    <span className="sr-only">Actions</span>
                  </TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>
                      <div className="font-medium text-ink">{row.name}</div>
                      <div className="text-[13px] text-ink-3">{scheduleTypeLabel(row.schedule_type)}</div>
                    </TableCell>
                    <TableCell>
                      <div className="text-ink-2">{describeCron(row.cron_expression)}</div>
                      <div className="text-[13px] text-muted" title={`Timetable: ${row.cron_expression}`}>
                        {row.timezone || "UTC"}
                        {describeCron(row.cron_expression) === "A custom timetable"
                          ? ` · ${row.cron_expression}`
                          : ""}
                      </div>
                    </TableCell>
                    <TableCell className="text-ink-2">
                      {!row.enabled ? (
                        <span className="text-muted">Paused</span>
                      ) : isRunningNow(row) ? (
                        <StatusBadge value="running" />
                      ) : row.next_run_at ? (
                        formatDate(row.next_run_at)
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell>
                      {row.last_run_status ? (
                        <div className="flex flex-wrap items-center gap-2">
                          <StatusBadge value={row.last_run_status} />
                          {row.last_run_finished_at ? (
                            <span className="text-[13px] text-muted">
                              {formatDate(row.last_run_finished_at)}
                            </span>
                          ) : null}
                        </div>
                      ) : (
                        <span className="text-muted">Not run yet</span>
                      )}
                      {row.retry_count_current > 0 ? (
                        <div className="mt-1 text-[13px] text-warning">
                          Trying again ({row.retry_count_current} of {row.max_retries})
                          {row.next_retry_at ? `, next ${formatDate(row.next_retry_at)}` : ""}
                        </div>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex flex-wrap justify-end gap-2">
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => onTrigger(row)}
                          disabled={triggeringId === row.id}
                        >
                          {triggeringId === row.id ? "Running…" : "Run now"}
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
                          {row.enabled ? "Pause" : "Resume"}
                        </Button>
                        <DeleteRowButton
                          path={`/projects/${projectId}/schedules/${row.id}`}
                          name={row.name}
                          kind="schedule"
                          consequences={["Its run history stays; the schedule itself stops existing."]}
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
        </div>
      </AppShell>

      <Modal
        open={modalOpen}
        onClose={() => {
          setModalOpen(false);
          resetForm();
        }}
        title={editing ? "Edit schedule" : "New schedule"}
        description="Choose what runs and when. It then runs by itself in the background."
      >
        <div className="space-y-4">
          <FormField label="What it does" htmlFor="sched-type">
            <Select
              id="sched-type"
              value={scheduleType}
              onChange={(e) => setScheduleType(e.target.value as ScheduleType)}
              disabled={!!editing}
            >
              <option value="transformation_pipeline_run">Run a recipe</option>
              <option value="postgres_publish">Deliver a dataset to PostgreSQL</option>
              <option value="connector_schema_watch">Watch databases for schema changes</option>
            </Select>
          </FormField>

          <FormField label="Name" htmlFor="sched-name">
            <Input id="sched-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Refresh customers every morning" />
          </FormField>
          <FormField label="Notes (optional)" htmlFor="sched-desc">
            <Textarea id="sched-desc" value={description} onChange={(e) => setDescription(e.target.value)} rows={2} />
          </FormField>
          <FormField label="When" htmlFor="sched-preset">
            <Select
              id="sched-preset"
              value={
                customTimetable
                  ? "custom"
                  : (CRON_PRESETS.find((p) => p.expression === cronExpression)?.expression ?? "custom")
              }
              onChange={(e) => {
                if (e.target.value === "custom") {
                  setCustomTimetable(true);
                } else {
                  setCustomTimetable(false);
                  setCronExpression(e.target.value);
                }
              }}
            >
              {CRON_PRESETS.map((preset) => (
                <option key={preset.expression} value={preset.expression}>
                  {preset.label}
                </option>
              ))}
              <option value="custom">Something else…</option>
            </Select>
          </FormField>
          {customTimetable || !CRON_PRESETS.some((p) => p.expression === cronExpression) ? (
            <FormField
              label="Timetable"
              htmlFor="sched-cron"
              description={`Reads as: ${describeCron(cronExpression)}. Written as minute, hour, day of month, month and day of week (cron).`}
            >
              <Input
                id="sched-cron"
                value={cronExpression}
                onChange={(e) => setCronExpression(e.target.value)}
                placeholder="0 9 * * *"
                className="font-mono text-[13px]"
              />
            </FormField>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField label="Time zone" htmlFor="sched-tz">
              <Input id="sched-tz" value={timezone} onChange={(e) => setTimezone(e.target.value)} placeholder="UTC" />
            </FormField>
            <FormField label="Status" htmlFor="sched-en">
              <Select id="sched-en" value={enabled ? "yes" : "no"} onChange={(e) => setEnabled(e.target.value === "yes")}>
                <option value="yes">On: runs at its times</option>
                <option value="no">Paused</option>
              </Select>
            </FormField>
          </div>

          {scheduleType === "connector_schema_watch" ? (
            <FormField
              label="Connection (optional)"
              htmlFor="sched-connection"
              description="Leave blank to watch every connection in this project."
            >
              <Select
                id="sched-connection"
                value={connectionId}
                onChange={(e) => setConnectionId(e.target.value)}
                disabled={loadingRefs}
              >
                <option value="">Every connection</option>
                {connections.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </FormField>
          ) : scheduleType === "transformation_pipeline_run" ? (
            <FormField label="Recipe" htmlFor="sched-pipeline">
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
              <FormField label="Destination" htmlFor="sched-dest">
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
              <FormField label="Each run" htmlFor="sched-wm">
                <Select id="sched-wm" value={writeMode} onChange={(e) => setWriteMode(e.target.value as "replace" | "append")}>
                  <option value="append">Adds its rows to the table</option>
                  <option value="replace">Replaces everything in the table</option>
                </Select>
              </FormField>
              {writeMode === "replace" ? (
                <p className="text-[13px] text-warning">Each run deletes what is in the table first.</p>
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
              {saving ? "Saving…" : editing ? "Save" : "Create schedule"}
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
