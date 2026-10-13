"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import type { AuthUser, HealthLiveResponse, PlatformStatusResponse } from "@platform/shared-types";
import {
  Badge,
  Button,
  SectionPanel,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { serviceLabel } from "@/lib/service-labels";
import { ReleaseBuildMeta } from "@/components/release/release-build-meta";
import { OperationalError, OperationalLoading } from "@/components/operational/operational-messages";
import { appConfig } from "@/lib/config";
import { parseApiResponse } from "@/lib/api/errors";
import { serviceHealthTone, toneClasses } from "@/features/system-status/system-status-helpers";
import { countOf, formatDateTime } from "@/lib/format";
import { sentenceLabel } from "@/lib/labels";

/**
 * Counters rendered as sentences, not payloads. The person on this page is
 * deciding whether to trust the platform; raw JSON told them it was not for
 * them. Known keys become labelled chips, long arrays collapse to a count,
 * and the untouched payload stays one click away for operators.
 */
const TONE_TO_BADGE = { success: "success", warning: "warning", danger: "danger", neutral: "neutral" } as const;

/** The counters each part reports, in the product's words. */
const DETAIL_LABELS: Record<string, string> = {
  user_count: "accounts",
  project_count: "projects",
  memberships: "memberships",
  shared_projects: "shared projects",
  enforcement: "enforcement",
  organisations: "organisations",
  security_policies: "access policies",
  retention_policies: "retention rules",
  retention_in_report_only_mode: "retention rules only reporting",
  erasure_requests: "erasure requests",
  versions_recorded: "versions kept",
  changes_awaiting_review: "changes waiting for approval",
  audit_entries: "audit entries",
  comments: "comments",
  source_count: "registered sources",
  connectors: "connectors",
  available: "ready to use",
  writable: "can write back",
  drivers_not_installed: "need a driver installed",
  dataset_count: "datasets",
  destination_count: "destinations",
  supported_extensions: "file types read",
  connection_count: "source connections",
  job_count: "imports",
  rule_count: "checks",
  rules_currently_failing: "checks failing",
  unacknowledged_drift_events: "schema changes not yet seen",
  breaking_drift_events: "schema changes that break things",
  pipeline_run_count: "runs",
  pipeline_count: "recipes",
  supported_step_types: "step types",
  workflow_count: "workflows",
  runs_queued: "runs waiting",
  runs_running: "runs running",
  oldest_queued_at: "oldest waiting",
  schedules_due_now: "schedules due",
  change_set_count: "sets of table edits",
  draft_count: "unsaved table edits",
  committed_count: "saved table edits",
  rows_written: "rows written back",
  saved_query_count: "saved queries",
  notebook_count: "notebooks",
  queries_run: "queries run",
  python_cells: "Python cells",
  python_cells_reason: "why",
  derived_datasets: "datasets made by recipes",
  pipelines_traceable: "recipes traced",
  storage: "kept as",
  pii_detectors: "personal data detectors",
  phrases_understood: "phrases understood",
  datasets_analysable: "datasets it can analyse",
  method: "method",
  metrics_recorded: "health records",
  freshness_policies: "freshness rules",
  incidents_open: "open incidents",
  incidents_critical: "critical incidents",
  charts: "charts",
  dashboards: "dashboards",
  scheduled_reports: "scheduled reports",
  reports_due_now: "reports due",
  shared_dashboards: "shared dashboards",
  saved_statistical_test_count: "saved comparisons",
  scheduled_operation_count: "schedules",
  notification_row_count: "notifications",
  external_notification_target_count: "alert channels",
};

function ModuleDetails({ details }: { details: Record<string, unknown> }) {
  const [showRaw, setShowRaw] = useState(false);
  const entries = Object.entries(details);
  if (entries.length === 0) return <span>—</span>;

  const chips: string[] = [];
  const label = (key: string) => DETAIL_LABELS[key] ?? key.replace(/_/g, " ");
  for (const [key, value] of entries) {
    if (Array.isArray(value)) {
      chips.push(`${value.length} ${label(key)}`);
    } else if (typeof value === "number" || typeof value === "boolean") {
      chips.push(`${value} ${label(key)}`);
    } else if (typeof value === "string" && value.length <= 60) {
      chips.push(`${label(key)}: ${value}`);
    } else if (value === null) {
      chips.push(`${label(key)}: none`);
    } else {
      chips.push(label(key));
    }
  }

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-1.5">
        {chips.map((chip) => (
          <Badge
            key={chip}
            className="font-sans"
          >
            {chip}
          </Badge>
        ))}
        <button
          type="button"
          onClick={() => setShowRaw((v) => !v)}
          className="rounded-md px-1.5 py-0.5 font-sans text-[12px] text-muted underline-offset-2 hover:underline"
        >
          {showRaw ? "Hide the details" : "Details"}
        </button>
      </div>
      {showRaw ? (
        <pre className="max-w-full overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-surface-2 p-2 text-[12px] leading-4">
          {JSON.stringify(details, null, 1)}
        </pre>
      ) : null}
    </div>
  );
}

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${appConfig.apiBaseUrl}${path}`, { cache: "no-store" });
  return parseApiResponse<T>(response);
}

/** "just now", "8s ago", "4m ago", "2h ago" — seconds matter for a heartbeat. */
function formatAge(seconds: number | null): string {
  if (seconds == null) return "never";
  if (seconds < 5) return "just now";
  if (seconds < 90) return `${Math.round(seconds)}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes}m ago`;
  return `${Math.round(minutes / 60)}h ago`;
}

const COMPONENT_LABELS: Record<string, string> = {
  "workflow-worker": "Workflow worker",
  "schedule-ticker": "Schedule ticker",
};

/**
 * The one panel that answers "is anything actually running?" — the leading
 * signal P0 could only infer. Each background component's last heartbeat sits
 * next to the work waiting for it, so a stalled queue and its cause are read
 * together, not on two different screens.
 */
function RuntimePanel({ platform }: { platform: PlatformStatusResponse }) {
  const runtime = platform.runtime;
  const workflows = platform.services.find((s) => s.name === "service-workflows");
  const details = (workflows?.details ?? {}) as Record<string, unknown>;
  const queued = Number(details.runs_queued ?? 0);
  const running = Number(details.runs_running ?? 0);
  const dueNow = Number(platform.scheduler.due_now_count ?? 0);

  return (
    <SectionPanel
      title="Background work"
      description="The parts that run schedules and workflows check in every few seconds. Silence means they have stopped."
    >
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-line bg-surface px-3 py-2.5 text-sm">
          <div className="text-[12px] text-muted">Runs queued</div>
          <div className="mt-1 font-mono text-lg text-ink">{queued}</div>
        </div>
        <div className="rounded-xl border border-line bg-surface px-3 py-2.5 text-sm">
          <div className="text-[12px] text-muted">Runs running</div>
          <div className="mt-1 font-mono text-lg text-ink">{running}</div>
        </div>
        <div className="rounded-xl border border-line bg-surface px-3 py-2.5 text-sm">
          <div className="text-[12px] text-muted">Schedules due</div>
          <div className="mt-1 font-mono text-lg text-ink">{dueNow}</div>
        </div>
      </div>

      <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
        <Table edge="panel" minWidth={560}>
          <TableHead>
            <TableRow>
              <TableHeaderCell>Component</TableHeaderCell>
              <TableHeaderCell>State</TableHeaderCell>
              <TableHeaderCell>Last checked in</TableHeaderCell>
              <TableHeaderCell>Server</TableHeaderCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {runtime.components.map((component) => {
              const key = `${component.component}:${component.host ?? "—"}`;
              const stateLabel =
                component.status === "absent"
                  ? "not running"
                  : component.healthy
                    ? "running"
                    : component.status === "stopping"
                      ? "stopping"
                      : "no recent beat";
              return (
                <TableRow key={key}>
                  <TableCell className="text-ink-2">
                    {COMPONENT_LABELS[component.component] ?? component.component}
                  </TableCell>
                  <TableCell>
                    <Badge tone={component.healthy ? "success" : "danger"}>{sentenceLabel(stateLabel)}</Badge>
                  </TableCell>
                  <TableCell className="text-xs text-ink-3">
                    {formatAge(component.age_seconds)}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-ink-3">{component.host ?? "—"}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </SectionPanel>
  );
}

/** The controls a security review asks about, as this server is set up (A6, W5). */
function SecurityPanel({ security }: { security: NonNullable<PlatformStatusResponse["security"]> }) {
  const rows: { label: string; value: string; ok: boolean; how?: string }[] = [
    {
      label: "Stored files encrypted at rest",
      value: security.files_encrypted_at_rest ? "Yes" : "No",
      ok: security.files_encrypted_at_rest,
      how: security.files_encrypted_at_rest
        ? undefined
        : "Set STORAGE_ENCRYPTION_KEY, restart, then run platform-encrypt-storage for files stored before.",
    },
    {
      label: "Sessions",
      value: `End after ${security.idle_timeout_minutes} minutes idle, ${security.session_limit_hours} hours at most`,
      ok: true,
    },
    {
      label: "Organisations limited to their own network",
      value: String(security.organisations_with_network_lists),
      ok: true,
      how: "Set on the Organisations page.",
    },
    {
      label: "Single sign-on",
      value: security.sso_configured ? "Configured" : "Not configured",
      ok: security.sso_configured,
      how: security.sso_configured ? undefined : "See the admin guide for connecting an identity provider.",
    },
    {
      label: "Addresses read from a proxy",
      value: security.trusted_proxy_hops > 0 ? `Yes, ${countOf(security.trusted_proxy_hops, "proxy", "proxies")} in front` : "No, the connecting address",
      ok: true,
      how: security.trusted_proxy_hops > 0 ? undefined : "Set TRUSTED_PROXY_HOPS when a load balancer sits in front.",
    },
  ];
  return (
    <SectionPanel title="Security" description="How this server protects data and sessions, as it is set up now.">
      <dl className="divide-y divide-line">
        {rows.map((row) => (
          <div key={row.label} className="flex flex-wrap items-start justify-between gap-3 py-2.5">
            <dt className="text-[14px] text-ink-2">{row.label}</dt>
            <dd className="text-right">
              <Badge tone={row.ok ? "success" : "warning"}>{row.value}</Badge>
              {row.how ? <div className="mt-1 max-w-sm text-[13px] text-ink-3">{row.how}</div> : null}
            </dd>
          </div>
        ))}
      </dl>
    </SectionPanel>
  );
}

export function SystemStatusPage({ currentUser }: { currentUser?: AuthUser | null }) {
  const [platform, setPlatform] = useState<PlatformStatusResponse | null>(null);
  const [live, setLive] = useState<HealthLiveResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [p, l] = await Promise.all([fetchJson<PlatformStatusResponse>("/status"), fetchJson<HealthLiveResponse>("/health/live")]);
      setPlatform(p);
      setLive(l);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load status.");
      setPlatform(null);
      setLive(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const overallTone = platform ? serviceHealthTone(platform.status) : "neutral";

  return (
    <AppShell
      currentUser={currentUser}
      title="System status"
      subtitle="Whether the platform and its background work are healthy."
      actions={
        <Button variant="secondary" onClick={() => void load()}>
          Refresh
        </Button>
      }
    >
      {error ? (
        <OperationalError
          title="Could not reach the API"
          message={error}
          hint={
            <>
              Confirm the gateway is running and <code className="rounded bg-sunken px-1">NEXT_PUBLIC_API_BASE_URL</code> points at{" "}
              <code className="rounded bg-sunken px-1">{appConfig.apiBaseUrl}</code>.
            </>
          }
        />
      ) : null}

      {loading && !platform ? <OperationalLoading message="Loading status…" /> : null}

      {platform ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className={`h-full rounded-2xl border px-4 py-4 ${toneClasses(overallTone)}`}>
            <div className="text-[12px] opacity-80">Overall</div>
            <div className="mt-2 text-lg font-semibold">{sentenceLabel(platform.status)}</div>
            <div className="mt-1 text-[13px] opacity-90">Checked {formatDateTime(platform.checked_at)}</div>
          </div>
          <div className="h-full rounded-2xl border border-line bg-surface px-4 py-4 text-sm text-ink">
            <div className="text-[12px] text-muted">Running as</div>
            <div className="mt-2 font-medium text-ink">{sentenceLabel(platform.environment)}</div>
            <div className="mt-1 text-[13px] text-ink-3">Version {platform.version}</div>
            {live ? <div className="mt-1 text-[13px] text-ink-3">Answering requests</div> : null}
          </div>
          <div className="h-full rounded-2xl border border-line bg-surface px-4 py-4 text-sm text-ink">
            <div className="text-[12px] text-muted">Schedules</div>
            <div className="mt-2 text-ink">
              {platform.scheduler.due_now_count} due now, {platform.scheduler.total_schedules} in all
            </div>
            <div className="mt-1 text-[13px] text-ink-3">
              {platform.scheduler.lease_active_count} running, {platform.scheduler.stale_lease_count} stuck
            </div>
          </div>
          <div className="h-full rounded-2xl border border-line bg-surface px-4 py-4 text-sm text-ink">
            <div className="text-[12px] text-muted">Set up</div>
            <div className="mt-2 text-[13px] text-ink">
              Schedules can start runs: {platform.scheduler.internal_api_configured ? "yes" : "no, the scheduler key is missing"}
            </div>
            <div className="mt-1 text-[13px] text-ink-3">
              Scheduler named: {platform.scheduler.scheduler_runtime_id_configured ? "yes" : "no (needed only when running more than one)"}
            </div>
          </div>
        </div>
      ) : null}

      {platform?.security ? <SecurityPanel security={platform.security} /> : null}

      {platform ? <RuntimePanel platform={platform} /> : null}

      {platform ? (
        <SectionPanel
          title="Parts of the platform"
          description="Each part and how it is doing, with the counts it reports."
        >
          <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
            <Table edge="panel" minWidth={640}>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Part</TableHeaderCell>
                  <TableHeaderCell>Status</TableHeaderCell>
                  <TableHeaderCell>Details</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {platform.services.map((s) => (
                  <TableRow key={s.name}>
                    <TableCell>
                      <div className="text-[13px] text-ink" title={s.name}>
                        {serviceLabel(s.name)}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge tone={TONE_TO_BADGE[serviceHealthTone(s.status)]}>{sentenceLabel(s.status)}</Badge>
                    </TableCell>
                    <TableCell className="text-xs text-ink-3">
                      <ModuleDetails details={s.details} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </SectionPanel>
      ) : null}

      <SectionPanel title="For whoever runs the server">
        <ul className="space-y-2 text-sm text-accent">
          <li className="text-ink-3">
            Installing, settings and running more than one scheduler:{" "}
            <code className="rounded bg-sunken px-1 text-ink-2">docs/deployment-guide.md</code>
          </li>
          <li>
            <Link href="/notifications" className="underline">
              In-app notifications
            </Link>
          </li>
          <li>
            <a href={`${appConfig.apiBaseUrl.replace(/\/api\/v1$/, "")}/docs`} className="underline" target="_blank" rel="noreferrer">
              API reference
            </a>
          </li>
          <li>
            <span className="text-muted">Readiness check for a load balancer: </span>
            <code className="text-ink-2">/api/v1/health/ready</code>
          </li>
          <li className="text-ink-3">
            Release checklist: <code className="rounded bg-sunken px-1 text-ink-2">docs/release-checklist.md</code> · Acceptance:{" "}
            <code className="rounded bg-sunken px-1 text-ink-2">make smoke</code>
          </li>
        </ul>
        <div className="mt-4">
          <ReleaseBuildMeta />
        </div>
      </SectionPanel>
    </AppShell>
  );
}
