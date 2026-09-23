"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { ExportFormat, ReportListResponse, ScheduledReport } from "@platform/shared-types";
import { Button } from "@platform/shared-ui";

import { Modal } from "@/components/ui/modal";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";

type DashboardSubscribeProps = {
  projectId: string;
  dashboardId: string;
  dashboardName: string;
  /** The signed-in person's address, to prefill; they can change it. */
  defaultEmail: string | null | undefined;
};

/** "Email me this every Monday": a scheduled report of the dashboard, in
 * the person's own name. Nothing new under the hood -- it IS a scheduled
 * report, so it runs on the worker, shows in Reports with its delivery
 * history, and honours the same SMTP truth-telling. */
const CADENCES = [
  { id: "weekly", label: "Every Monday, 9am", cron: "0 9 * * 1" },
  { id: "daily", label: "Every weekday, 8am", cron: "0 8 * * 1-5" },
  { id: "monthly", label: "First of the month, 9am", cron: "0 9 1 * *" },
] as const;

const FORMATS: { id: ExportFormat; label: string }[] = [
  { id: "pdf", label: "PDF" },
  { id: "excel", label: "Excel" },
  { id: "html", label: "Web page" },
];

export function DashboardSubscribe({
  projectId,
  dashboardId,
  dashboardName,
  defaultEmail,
}: DashboardSubscribeProps) {
  const [open, setOpen] = useState(false);
  const [reports, setReports] = useState<ScheduledReport[] | null>(null);
  const [email, setEmail] = useState(defaultEmail ?? "");
  const [cadence, setCadence] = useState<(typeof CADENCES)[number]["id"]>("weekly");
  const [format, setFormat] = useState<ExportFormat>("pdf");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const response = await apiFetch<ReportListResponse>(`/projects/${projectId}/reports`);
      setReports(
        response.items.filter(
          (report) => report.source_kind === "dashboard" && report.source_id === dashboardId,
        ),
      );
    } catch (caught) {
      setError(extractErrorMessage(caught));
    }
  }, [projectId, dashboardId]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const mine = useMemo(
    () =>
      (reports ?? []).filter(
        (report) => email.trim() && report.recipients.includes(email.trim().toLowerCase()),
      ),
    [reports, email],
  );

  const subscribe = async () => {
    const address = email.trim().toLowerCase();
    if (!address.includes("@")) {
      setError("Enter the address the dashboard should go to.");
      return;
    }
    setBusy(true);
    setError(null);
    const chosen = CADENCES.find((item) => item.id === cadence) ?? CADENCES[0];
    try {
      await apiFetch<ScheduledReport>(`/projects/${projectId}/reports`, {
        method: "POST",
        body: JSON.stringify({
          name: `${dashboardName} — ${chosen.label.toLowerCase()} for ${address}`,
          description: `Subscription to the ${dashboardName} dashboard.`,
          source_kind: "dashboard",
          source_id: dashboardId,
          file_format: format,
          cron_expression: chosen.cron,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          recipients: [address],
        }),
      });
      await load();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const unsubscribe = async (report: ScheduledReport) => {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/projects/${projectId}/reports/${report.id}`, { method: "DELETE" });
      await load();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
        Subscribe
      </Button>
      <Modal
        open={open}
        title="Email me this dashboard"
        description="Creates a scheduled report of this dashboard addressed to you. It runs on the worker and appears under Reports with its delivery history; if the server cannot send mail, the history says so rather than pretending."
        onClose={() => setOpen(false)}
        widthClassName="max-w-lg"
        footer={
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
              Close
            </Button>
            <Button size="sm" onClick={() => void subscribe()} disabled={busy}>
              {busy ? "Saving…" : "Subscribe"}
            </Button>
          </div>
        }
      >
        <div className="space-y-4">
          <label className="block space-y-1">
            <span className="text-[11px] text-muted">Send to</span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@acme.com"
              className="h-9 w-full rounded-lg border border-line bg-sunken px-3 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)]"
            />
          </label>
          <div className="space-y-1">
            <span className="text-[11px] text-muted">How often</span>
            <div className="flex flex-wrap gap-1">
              {CADENCES.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setCadence(item.id)}
                  className={cx(
                    "rounded-md border px-2 py-1 text-[11.5px] transition",
                    cadence === item.id
                      ? "border-[color:var(--accent)] bg-[color:var(--accent-faint)] text-ink"
                      : "border-line text-ink-3 hover:text-ink",
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <p className="text-[10.5px] text-muted">In your timezone ({Intl.DateTimeFormat().resolvedOptions().timeZone}).</p>
          </div>
          <div className="space-y-1">
            <span className="text-[11px] text-muted">As</span>
            <div className="flex rounded-lg border border-line p-0.5">
              {FORMATS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setFormat(item.id)}
                  className={cx(
                    "flex-1 rounded-md px-2 py-1 text-[12px] transition",
                    format === item.id
                      ? "bg-[color:var(--accent)] text-accent-ink"
                      : "text-ink-3 hover:text-ink",
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}
          <div className="border-t border-line pt-3">
            <span className="text-[11px] uppercase tracking-[0.14em] text-muted">
              Your subscriptions to this dashboard
            </span>
            {reports === null ? (
              <p className="mt-1 text-[12px] text-muted">Loading…</p>
            ) : mine.length === 0 ? (
              <p className="mt-1 text-[12px] text-muted">None yet for {email.trim() || "that address"}.</p>
            ) : (
              <ul className="mt-1 space-y-1">
                {mine.map((report) => (
                  <li key={report.id} className="flex items-center justify-between gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-[12px]">
                    <span className="min-w-0 truncate text-ink">
                      {report.name}
                      <span className="text-muted"> · {report.file_format}</span>
                      {report.last_status ? (
                        <span className={report.last_status === "failed" ? " text-danger" : " text-muted"}>
                          {" "}· last run {report.last_status}
                        </span>
                      ) : null}
                    </span>
                    <button
                      type="button"
                      onClick={() => void unsubscribe(report)}
                      disabled={busy}
                      className="shrink-0 text-[11.5px] text-danger hover:underline"
                    >
                      Unsubscribe
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </Modal>
    </>
  );
}
