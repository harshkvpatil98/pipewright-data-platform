"use client";

import { useCallback, useState } from "react";

import type {
  AuthUser,
  ChartListResponse,
  DashboardListResponse,
  DatasetRecord,
  DeliveryListResponse,
  ExportFormat,
  ExternalNotificationTargetRecord,
  ReportDelivery,
  ReportListResponse,
  ReportSource,
  ScheduledReport,
} from "@platform/shared-types";
import { Button, Modal, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { DeleteRowButton } from "@/components/ui/delete-row-button";
import { Icon } from "@/components/ui/icon";
import { apiDownload, apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { cx } from "@/lib/utils";

type ReportsPageProps = {
  currentUser: AuthUser;
  projectId: string;
  initial: ReportListResponse;
  datasets: DatasetRecord[];
  charts: ChartListResponse;
  dashboards: DashboardListResponse;
  targets: ExternalNotificationTargetRecord[];
};

const FORMATS: { id: ExportFormat; label: string; note: string }[] = [
  { id: "excel", label: "Excel", note: "Typed columns, frozen header." },
  { id: "csv", label: "CSV", note: "Universal, loses every type." },
  {
    id: "html",
    label: "Web page",
    note: "Self-contained; prints from any browser.",
  },
  {
    id: "pdf",
    label: "PDF",
    note: "Paginated, repeating header; up to 5,000 rows and 14 columns.",
  },
];

const CRON_PRESETS = [
  { label: "Every weekday, 7am", value: "0 7 * * 1-5" },
  { label: "Mondays, 7am", value: "0 7 * * 1" },
  { label: "First of the month", value: "0 7 1 * *" },
  { label: "Daily, 6am", value: "0 6 * * *" },
];

const inputClass =
  "h-9 w-full rounded-lg border border-line bg-sunken px-2.5 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)]";

export function ReportsPageView({
  currentUser,
  projectId,
  initial,
  datasets,
  charts,
  dashboards,
  targets,
}: ReportsPageProps) {
  const [reports, setReports] = useState(initial.items);
  const [name, setName] = useState("");
  const [sourceKind, setSourceKind] = useState<ReportSource>("dataset");
  const [sourceId, setSourceId] = useState(datasets[0]?.id ?? "");
  const [format, setFormat] = useState<ExportFormat>("excel");
  const [cron, setCron] = useState("");
  const [targetId, setTargetId] = useState("");
  const [recipients, setRecipients] = useState("");
  const usableTargets = targets.filter((target) => target.enabled);
  const targetById = new Map(targets.map((target) => [target.id, target]));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const options =
    sourceKind === "dataset"
      ? datasets.map((item) => ({ id: item.id, name: item.name }))
      : sourceKind === "chart"
        ? charts.items.map((item) => ({ id: item.id, name: item.name }))
        : dashboards.items.map((item) => ({ id: item.id, name: item.name }));

  const reload = useCallback(async () => {
    setReports(
      (await apiFetch<ReportListResponse>(`/projects/${projectId}/reports`))
        .items,
    );
  }, [projectId]);

  const [creating, setCreating] = useState(false);

  const create = useCallback(async () => {
    if (!sourceId) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/projects/${projectId}/reports`, {
        method: "POST",
        body: JSON.stringify({
          name: name.trim() || "Untitled report",
          source_kind: sourceKind,
          source_id: sourceId,
          file_format: format,
          cron_expression: cron || null,
          timezone: cron
            ? Intl.DateTimeFormat().resolvedOptions().timeZone
            : null,
          notification_target_id: targetId || null,
          recipients: recipients
            .split(/[,\s;]+/)
            .map((address) => address.trim())
            .filter(Boolean),
        }),
      });
      setName("");
      setCron("");
      setRecipients("");
      setCreating(false);
      await reload();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }, [
    projectId,
    name,
    sourceKind,
    sourceId,
    format,
    cron,
    targetId,
    recipients,
    reload,
  ]);

  return (
    <AppShell
      currentUser={currentUser}
      title="Reports"
      subtitle="Files sent by email or Slack on a schedule."
      actions={<Button onClick={() => setCreating(true)}>New report</Button>}
    >
      {error ? (
        <div className="border-danger-line bg-danger-soft text-danger rounded-2xl border px-4 py-3 text-sm">
          {error}
        </div>
      ) : null}

      <SectionPanel title={`Reports (${reports.length})`}>
        {reports.length === 0 ? (
          <div className="border-line flex flex-wrap items-center justify-between gap-3 rounded-xl border border-dashed px-4 py-6">
            <p className="text-ink-3 text-[14px]">
              No reports yet. A report sends a dataset, chart or dashboard as a
              file, for example every Monday morning.
            </p>
            <Button size="sm" onClick={() => setCreating(true)}>
              New report
            </Button>
          </div>
        ) : (
          <ul className="space-y-2">
            {reports.map((report) => (
              <ReportRow
                key={report.id}
                projectId={projectId}
                report={report}
                targetName={
                  report.notification_target_id
                    ? (targetById.get(report.notification_target_id)?.name ??
                      "a removed target")
                    : null
                }
                onDeleted={() =>
                  setReports((current) =>
                    current.filter((item) => item.id !== report.id),
                  )
                }
              />
            ))}
          </ul>
        )}
        <p className="text-muted mt-3 flex items-start gap-1.5 text-[11.5px]">
          <Icon name="info" size={11} className="mt-0.5 shrink-0" />
          Scheduled reports fire on the worker tick, so they need
          <code className="bg-surface-2 mx-1 rounded px-1 font-mono text-[10.5px]">
            platform-workflow-worker
          </code>
          running.
        </p>
      </SectionPanel>
      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title="New report"
        description="Pick what goes in it, how often it is sent and who gets it."
        widthClassName="max-w-2xl"
        footer={
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setCreating(false)}
            >
              Cancel
            </Button>
            <Button size="sm" onClick={create} disabled={busy || !sourceId}>
              {busy ? "Creating…" : "Create report"}
            </Button>
          </div>
        }
      >
        {error && creating ? (
          <p role="alert" className="text-danger mb-3 text-[13px]">
            {error}
          </p>
        ) : null}
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <span className="text-ink mb-1.5 block text-[13px] font-medium">
              Name
            </span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Weekly revenue"
              className={inputClass}
            />
          </div>

          <div>
            <span className="text-ink mb-1.5 block text-[13px] font-medium">
              What goes in it
            </span>
            <div className="flex gap-1.5">
              <select
                value={sourceKind}
                onChange={(event) => {
                  const next = event.target.value as ReportSource;
                  setSourceKind(next);
                  setSourceId("");
                }}
                className={cx(inputClass, "w-[130px] shrink-0")}
              >
                <option value="dataset">Dataset</option>
                <option value="chart">Chart</option>
                <option value="dashboard">Dashboard</option>
              </select>
              <select
                value={sourceId}
                onChange={(event) => setSourceId(event.target.value)}
                className={inputClass}
              >
                <option value="">Choose…</option>
                {options.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <span className="text-ink mb-1.5 block text-[13px] font-medium">
              Format
            </span>
            <div className="border-line flex rounded-lg border p-0.5">
              {FORMATS.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  title={option.note}
                  onClick={() => setFormat(option.id)}
                  className={cx(
                    "flex-1 rounded-md px-2 py-1.5 text-[12px] transition",
                    format === option.id
                      ? "text-accent-ink bg-[color:var(--accent)]"
                      : "text-ink-3 hover:text-ink",
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <p className="text-muted mt-1 text-[12px]">
              {FORMATS.find((option) => option.id === format)?.note}
            </p>
          </div>

          <div>
            <span className="text-ink mb-1.5 block text-[13px] font-medium">
              When
            </span>
            <div className="flex flex-wrap gap-1">
              {CRON_PRESETS.map((preset) => (
                <button
                  key={preset.value}
                  type="button"
                  onClick={() =>
                    setCron((current) =>
                      current === preset.value ? "" : preset.value,
                    )
                  }
                  className={cx(
                    "rounded-md border px-2 py-1 text-[12px] transition",
                    cron === preset.value
                      ? "text-ink border-[color:var(--accent)] bg-[color:var(--accent-faint)]"
                      : "border-line text-ink-3 hover:text-ink",
                  )}
                >
                  {preset.label}
                </button>
              ))}
            </div>
            <p className="text-muted mt-1 text-[12px]">
              {cron
                ? `Runs on ${cron} in your timezone.`
                : "Leave blank to run it by hand."}
            </p>
          </div>
        </div>

        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <div>
            <span className="text-ink mb-1.5 block text-[13px] font-medium">
              Deliver to
            </span>
            <select
              value={targetId}
              onChange={(event) => setTargetId(event.target.value)}
              className={inputClass}
            >
              <option value="">Only the in-app bell</option>
              {usableTargets.map((target) => (
                <option key={target.id} value={target.id}>
                  {target.name} (
                  {target.target_type === "slack_webhook" ? "Slack" : "email"})
                </option>
              ))}
            </select>
            <p className="text-muted mt-1 text-[12px]">
              {usableTargets.length === 0
                ? "No Slack channel or email address is set up yet. Add one under Overview, then Alerts."
                : "A Slack target gets a message with a link; an email target gets the file attached."}
            </p>
          </div>
          <div>
            <span className="text-ink mb-1.5 block text-[13px] font-medium">
              Email to
            </span>
            <input
              value={recipients}
              onChange={(event) => setRecipients(event.target.value)}
              placeholder="ada@acme.com, ops@acme.com"
              className={inputClass}
            />
            <p className="text-muted mt-1 text-[12px]">
              Each address gets the file attached. The report's history says
              whether each one was sent.
            </p>
          </div>
        </div>
      </Modal>
    </AppShell>
  );
}

function ReportRow({
  projectId,
  report,
  targetName,
  onDeleted,
}: {
  projectId: string;
  report: ScheduledReport;
  targetName: string | null;
  onDeleted: () => void;
}) {
  // Deliveries are fetched only when asked for. A report can have a long
  // history and most of the time nobody is looking at it; loading every row's
  // history to render a list would be a request per report on every visit.
  const [deliveries, setDeliveries] = useState<ReportDelivery[] | null>(null);
  const [loadingDeliveries, setLoadingDeliveries] = useState(false);
  const [deliveryError, setDeliveryError] = useState<string | null>(null);

  const toggleDeliveries = async () => {
    if (deliveries !== null) {
      setDeliveries(null);
      return;
    }
    setLoadingDeliveries(true);
    setDeliveryError(null);
    try {
      const response = await apiFetch<DeliveryListResponse>(
        `/projects/${projectId}/reports/${report.id}/deliveries`,
      );
      setDeliveries(response.items);
    } catch (caught) {
      setDeliveryError(extractErrorMessage(caught));
    } finally {
      setLoadingDeliveries(false);
    }
  };

  return (
    <li className="border-line bg-surface flex flex-wrap items-center gap-3 rounded-xl border px-3.5 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-ink text-[13.5px]">{report.name}</span>
          <span className="bg-surface-2 text-ink-3 rounded px-1.5 py-0.5 text-[10px] uppercase">
            {report.file_format}
          </span>
          {!report.enabled ? (
            <span className="bg-surface-2 text-muted rounded px-1.5 py-0.5 text-[10px]">
              paused
            </span>
          ) : null}
        </div>
        <div className="text-muted mt-0.5 text-[11.5px]">
          from a {report.source_kind}
          {report.cron_expression
            ? ` · ${report.cron_expression}`
            : " · on demand"}
          {report.next_run_at
            ? ` · next ${formatDate(report.next_run_at)}`
            : ""}
          {targetName ? ` · to ${targetName}` : ""}
          {report.recipients.length > 0
            ? ` · emails ${report.recipients.length} recipient${report.recipients.length === 1 ? "" : "s"}`
            : ""}
        </div>
        {report.last_status ? (
          <div
            className={cx(
              "mt-0.5 text-[11px]",
              report.last_status === "failed" ? "text-danger" : "text-muted",
            )}
          >
            last run {report.last_status}
            {report.last_error ? ` — ${report.last_error}` : ""}
            {report.run_count > 0 ? ` · ${report.run_count} run(s)` : ""}
          </div>
        ) : null}
      </div>
      <button
        type="button"
        onClick={() => void downloadReport(projectId, report)}
        className="border-line text-ink hover:bg-surface-2 shrink-0 rounded-lg border px-2.5 py-1.5 text-[12px] transition"
      >
        Generate now
      </button>
      <button
        type="button"
        onClick={() => void toggleDeliveries()}
        disabled={loadingDeliveries}
        className="border-line text-ink hover:bg-surface-2 shrink-0 rounded-lg border px-2.5 py-1.5 text-[12px] transition disabled:opacity-50"
      >
        {loadingDeliveries
          ? "Loading…"
          : deliveries !== null
            ? "Hide history"
            : "History"}
      </button>
      <DeleteRowButton
        path={`/projects/${projectId}/reports/${report.id}`}
        name={report.name}
        kind="scheduled report"
        consequences={[
          "Its delivery history stays; the schedule stops existing.",
        ]}
        onDeleted={onDeleted}
      />

      {deliveryError ? (
        <p role="alert" className="text-danger w-full text-[11.5px]">
          {deliveryError}
        </p>
      ) : null}

      {deliveries !== null ? (
        <div className="border-line w-full border-t pt-2">
          {deliveries.length === 0 ? (
            <p className="text-muted text-[11.5px]">
              This report has not been generated yet.
            </p>
          ) : (
            <ul className="space-y-1">
              {deliveries.map((delivery) => (
                <li
                  key={delivery.id}
                  className="text-ink-3 flex flex-wrap items-center gap-2 text-[11.5px]"
                >
                  <span
                    className={
                      delivery.status === "succeeded"
                        ? "text-success"
                        : "text-danger"
                    }
                  >
                    {delivery.status}
                  </span>
                  <span className="text-muted">
                    {formatDate(delivery.created_at)}
                  </span>
                  {delivery.row_count !== null ? (
                    <span>{delivery.row_count} row(s)</span>
                  ) : null}
                  {delivery.generated_ms !== null ? (
                    <span>{Math.round(delivery.generated_ms)} ms</span>
                  ) : null}
                  {delivery.message ? (
                    <span
                      className={
                        delivery.status === "succeeded"
                          ? "text-ink-3"
                          : "text-danger"
                      }
                    >
                      {delivery.message}
                    </span>
                  ) : null}
                  {delivery.channels.filter(
                    (channel) => channel.channel !== "in_app",
                  ).length > 0 ? (
                    <ul className="flex w-full flex-wrap gap-1.5 pl-3">
                      {delivery.channels
                        .filter((channel) => channel.channel !== "in_app")
                        .map((channel, index) => (
                          <li
                            key={index}
                            title={channel.detail}
                            className={cx(
                              "rounded-full border px-2 py-0.5 text-[10.5px]",
                              channel.ok
                                ? "border-success-line bg-success-soft text-success"
                                : "border-danger-line bg-danger-soft text-danger",
                            )}
                          >
                            {channel.channel === "slack"
                              ? "Slack"
                              : channel.channel === "email"
                                ? "Email"
                                : channel.channel}
                            {channel.recipient
                              ? ` ${channel.recipient}`
                              : channel.target
                                ? ` ${channel.target}`
                                : ""}
                            {channel.ok ? " ✓" : " ✗"}
                          </li>
                        ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </li>
  );
}

async function downloadReport(
  projectId: string,
  report: ScheduledReport,
): Promise<void> {
  const { blob, filename } = await apiDownload(
    `/projects/${projectId}/reports/${report.id}/run`,
    { method: "POST" },
  );

  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename ?? `${report.name}.${report.file_format}`;
  anchor.click();
  URL.revokeObjectURL(url);
}
