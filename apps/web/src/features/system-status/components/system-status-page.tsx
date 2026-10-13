"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import type { AuthUser, HealthLiveResponse, PlatformStatusResponse } from "@platform/shared-types";
import {
  Badge,
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

/**
 * Counters rendered as sentences, not payloads. The person on this page is
 * deciding whether to trust the platform; raw JSON told them it was not for
 * them. Known keys become labelled chips, long arrays collapse to a count,
 * and the untouched payload stays one click away for operators.
 */
function ModuleDetails({ details }: { details: Record<string, unknown> }) {
  const [showRaw, setShowRaw] = useState(false);
  const entries = Object.entries(details);
  if (entries.length === 0) return <span>—</span>;

  const chips: string[] = [];
  const label = (key: string) => key.replace(/_/g, " ");
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
          {showRaw ? "hide raw" : "raw"}
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
      title="Runtime"
      description="Background workers report a heartbeat each loop. A component with no fresh beat is not running, and queued work waits until it comes back."
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
        <Table minWidth={560}>
          <TableHead>
            <TableRow>
              <TableHeaderCell>Component</TableHeaderCell>
              <TableHeaderCell>State</TableHeaderCell>
              <TableHeaderCell>Last heartbeat</TableHeaderCell>
              <TableHeaderCell>Host</TableHeaderCell>
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
                    <span
                      className={`inline-flex items-center gap-1.5 rounded-lg border px-2 py-0.5 text-[12px] font-semibold ${toneClasses(
                        component.healthy ? "success" : "danger",
                      )}`}
                    >
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${
                          component.healthy ? "bg-success" : "bg-danger"
                        }`}
                      />
                      {stateLabel}
                    </span>
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
        <button
          type="button"
          onClick={() => void load()}
          className="rounded-xl border border-line-strong bg-surface px-4 py-2 text-sm font-medium text-ink hover:bg-surface-2"
        >
          Refresh
        </button>
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
            <div className="mt-2 text-lg font-semibold capitalize">{platform.status}</div>
            <div className="mt-1 text-xs opacity-90">{platform.service}</div>
          </div>
          <div className="h-full rounded-2xl border border-line bg-surface px-4 py-4 text-sm text-ink">
            <div className="text-[12px] text-muted">Environment</div>
            <div className="mt-2 font-medium text-ink">{platform.environment}</div>
            <div className="mt-1 text-xs text-ink-3">
              API bundle <span className="font-mono text-ink-2">v{platform.version}</span>
            </div>
          </div>
          <div className="h-full rounded-2xl border border-line bg-surface px-4 py-4 text-sm text-ink">
            <div className="text-[12px] text-muted">Snapshot time</div>
            <div className="mt-2 font-mono text-xs text-ink-2">{platform.checked_at}</div>
            {live ? (
              <div className="mt-2 text-xs text-muted">Liveness probe: {live.timestamp}</div>
            ) : null}
          </div>
          <div className="h-full rounded-2xl border border-line bg-surface px-4 py-4 text-sm text-ink">
            <div className="text-[12px] text-muted">Scheduler</div>
            <div className="mt-2 text-ink">
              Due now: <span className="font-mono">{platform.scheduler.due_now_count}</span>
            </div>
            <div className="text-ink">
              Total schedules: <span className="font-mono">{platform.scheduler.total_schedules}</span>
            </div>
            <div className="mt-2 text-xs text-muted">
              Internal API token: {platform.scheduler.internal_api_configured ? "configured" : "not set"}
            </div>
            <div className="mt-2 text-xs text-muted">
              Runtime id env: {platform.scheduler.scheduler_runtime_id_configured ? "set" : "not set"}
            </div>
            <div className="mt-1 text-xs text-muted">
              Active leases: <span className="font-mono text-ink-3">{platform.scheduler.lease_active_count}</span>
              {" · "}
              Stale: <span className="font-mono text-ink-3">{platform.scheduler.stale_lease_count}</span>
            </div>
          </div>
        </div>
      ) : null}

      {platform ? <RuntimePanel platform={platform} /> : null}

      {platform ? (
        <SectionPanel
          title="Modules"
          description="Per-domain health signals and safe counters. Readiness still requires POST /health/ready for orchestrators."
        >
          <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
            <Table minWidth={640}>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Module</TableHeaderCell>
                  <TableHeaderCell>Status</TableHeaderCell>
                  <TableHeaderCell>Details</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {platform.services.map((s) => (
                  <TableRow key={s.name}>
                    <TableCell>
                      <div className="text-[13px] text-ink">{serviceLabel(s.name)}</div>
                      <div className="font-mono text-[12px] text-muted">{s.name}</div>
                    </TableCell>
                    <TableCell>
                      <span
                        className={`rounded-lg border px-2 py-0.5 text-[12px] font-semibold ${toneClasses(serviceHealthTone(s.status))}`}
                      >
                        {s.status}
                      </span>
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

      {platform ? (
        <SectionPanel title="Scheduler note" description="Operational context only.">
          <p className="text-sm leading-6 text-ink-2">{platform.scheduler.note}</p>
        </SectionPanel>
      ) : null}

      <SectionPanel title="Related" description="Handy links for operators.">
        <ul className="space-y-2 text-sm text-accent">
          <li className="text-ink-3">
            Deploy, env templates, and CI: see repository file{" "}
            <code className="rounded bg-sunken px-1 text-ink-2">docs/deployment-guide.md</code>
          </li>
          <li>
            <Link href="/notifications" className="underline">
              In-app notifications
            </Link>
          </li>
          <li>
            <a href={`${appConfig.apiBaseUrl.replace(/\/api\/v1$/, "")}/docs`} className="underline" target="_blank" rel="noreferrer">
              OpenAPI docs
            </a>
          </li>
          <li>
            <span className="text-muted">Readiness: </span>
            <code className="text-ink-2">GET /api/v1/health/ready</code>
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
