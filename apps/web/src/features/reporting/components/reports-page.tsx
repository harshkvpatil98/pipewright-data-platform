"use client";

import { useCallback, useState } from "react";

import type {
  AuthUser,
  ChartListResponse,
  DashboardListResponse,
  DatasetRecord,
  ExportFormat,
  ReportListResponse,
  ReportSource,
  ScheduledReport,
} from "@platform/shared-types";
import { Button, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
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
};

const FORMATS: { id: ExportFormat; label: string; note: string }[] = [
  { id: "excel", label: "Excel", note: "Typed columns, frozen header." },
  { id: "csv", label: "CSV", note: "Universal, loses every type." },
  { id: "html", label: "Web page", note: "Self-contained; prints to PDF." },
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
}: ReportsPageProps) {
  const [reports, setReports] = useState(initial.items);
  const [name, setName] = useState("");
  const [sourceKind, setSourceKind] = useState<ReportSource>("dataset");
  const [sourceId, setSourceId] = useState(datasets[0]?.id ?? "");
  const [format, setFormat] = useState<ExportFormat>("excel");
  const [cron, setCron] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const options =
    sourceKind === "dataset"
      ? datasets.map((item) => ({ id: item.id, name: item.name }))
      : sourceKind === "chart"
        ? charts.items.map((item) => ({ id: item.id, name: item.name }))
        : dashboards.items.map((item) => ({ id: item.id, name: item.name }));

  const reload = useCallback(async () => {
    setReports((await apiFetch<ReportListResponse>(`/projects/${projectId}/reports`)).items);
  }, [projectId]);

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
          timezone: cron ? Intl.DateTimeFormat().resolvedOptions().timeZone : null,
        }),
      });
      setName("");
      setCron("");
      await reload();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }, [projectId, name, sourceKind, sourceId, format, cron, reload]);

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Consumption"
      title="Scheduled reports"
      subtitle="The chore this removes: somebody exporting the same spreadsheet every Monday and emailing it round. Reports run on the worker, not when a page is open."
    >
      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}

      <SectionPanel title="New report" description="Pick what goes in it and when it should arrive.">
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <span className="mb-1.5 block text-[12px] font-medium text-ink">Name</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Weekly revenue"
              className={inputClass}
            />
          </div>

          <div>
            <span className="mb-1.5 block text-[12px] font-medium text-ink">What goes in it</span>
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
            <span className="mb-1.5 block text-[12px] font-medium text-ink">Format</span>
            <div className="flex rounded-lg border border-line p-0.5">
              {FORMATS.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  title={option.note}
                  onClick={() => setFormat(option.id)}
                  className={cx(
                    "flex-1 rounded-md px-2 py-1.5 text-[12px] transition",
                    format === option.id
                      ? "bg-[color:var(--accent)] text-accent-ink"
                      : "text-ink-3 hover:text-ink",
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <p className="mt-1 text-[11px] text-muted">
              {FORMATS.find((option) => option.id === format)?.note}
            </p>
          </div>

          <div>
            <span className="mb-1.5 block text-[12px] font-medium text-ink">When</span>
            <div className="flex flex-wrap gap-1">
              {CRON_PRESETS.map((preset) => (
                <button
                  key={preset.value}
                  type="button"
                  onClick={() => setCron((current) => (current === preset.value ? "" : preset.value))}
                  className={cx(
                    "rounded-md border px-2 py-1 text-[11px] transition",
                    cron === preset.value
                      ? "border-[color:var(--accent)] bg-[color:var(--accent-faint)] text-ink"
                      : "border-line text-ink-3 hover:text-ink",
                  )}
                >
                  {preset.label}
                </button>
              ))}
            </div>
            <p className="mt-1 text-[11px] text-muted">
              {cron ? `Runs on ${cron} in your timezone.` : "Leave blank to run it by hand."}
            </p>
          </div>
        </div>

        <div className="mt-3 flex justify-end">
          <Button onClick={create} disabled={busy || !sourceId}>
            {busy ? "Creating…" : "Create report"}
          </Button>
        </div>
      </SectionPanel>

      <SectionPanel title={`Reports (${reports.length})`}>
        {reports.length === 0 ? (
          <p className="rounded-xl border border-line px-4 py-8 text-center text-[12.5px] text-muted">
            Nothing scheduled yet.
          </p>
        ) : (
          <ul className="space-y-2">
            {reports.map((report) => (
              <ReportRow key={report.id} projectId={projectId} report={report} />
            ))}
          </ul>
        )}
        <p className="mt-3 flex items-start gap-1.5 text-[11.5px] text-muted">
          <Icon name="info" size={11} className="mt-0.5 shrink-0" />
          Scheduled reports fire on the worker tick, so they need
          <code className="mx-1 rounded bg-surface-2 px-1 font-mono text-[10.5px]">
            platform-workflow-worker
          </code>
          running.
        </p>
      </SectionPanel>
    </AppShell>
  );
}

function ReportRow({ projectId, report }: { projectId: string; report: ScheduledReport }) {
  return (
    <li className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface px-3.5 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[13.5px] text-ink">{report.name}</span>
          <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] uppercase text-ink-3">
            {report.file_format}
          </span>
          {!report.enabled ? (
            <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-muted">
              paused
            </span>
          ) : null}
        </div>
        <div className="mt-0.5 text-[11.5px] text-muted">
          from a {report.source_kind}
          {report.cron_expression ? ` · ${report.cron_expression}` : " · on demand"}
          {report.next_run_at ? ` · next ${formatDate(report.next_run_at)}` : ""}
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
        className="shrink-0 rounded-lg border border-line px-2.5 py-1.5 text-[12px] text-ink transition hover:bg-surface-2"
      >
        Generate now
      </button>
    </li>
  );
}

async function downloadReport(projectId: string, report: ScheduledReport): Promise<void> {
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
