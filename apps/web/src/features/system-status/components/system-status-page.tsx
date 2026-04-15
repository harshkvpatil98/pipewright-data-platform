"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import type { HealthLiveResponse, PlatformStatusResponse } from "@platform/shared-types";
import { SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { ReleaseBuildMeta } from "@/components/release/release-build-meta";
import { OperationalError, OperationalLoading } from "@/components/operational/operational-messages";
import { appConfig } from "@/lib/config";
import { parseApiResponse } from "@/lib/api/errors";
import { serviceHealthTone, toneClasses } from "@/features/system-status/system-status-helpers";

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${appConfig.apiBaseUrl}${path}`, { cache: "no-store" });
  return parseApiResponse<T>(response);
}

export function SystemStatusPage() {
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
      title="System status"
      subtitle="Operational snapshot from the API gateway. No secrets or credentials are shown here."
      actions={
        <button
          type="button"
          onClick={() => void load()}
          className="rounded-xl border border-white/15 bg-white/5 px-4 py-2 text-sm font-medium text-slate-100 hover:bg-white/10"
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
              Confirm the gateway is running and <code className="rounded bg-black/20 px-1">NEXT_PUBLIC_API_BASE_URL</code> points at{" "}
              <code className="rounded bg-black/20 px-1">{appConfig.apiBaseUrl}</code>.
            </>
          }
        />
      ) : null}

      {loading && !platform ? <OperationalLoading message="Loading status…" /> : null}

      {platform ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className={`h-full rounded-2xl border px-4 py-4 ${toneClasses(overallTone)}`}>
            <div className="text-[11px] uppercase tracking-[0.2em] opacity-80">Overall</div>
            <div className="mt-2 text-lg font-semibold capitalize">{platform.status}</div>
            <div className="mt-1 text-xs opacity-90">{platform.service}</div>
          </div>
          <div className="h-full rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-4 text-sm text-slate-200">
            <div className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Environment</div>
            <div className="mt-2 font-medium text-white">{platform.environment}</div>
            <div className="mt-1 text-xs text-slate-400">
              API bundle <span className="font-mono text-slate-300">v{platform.version}</span>
            </div>
          </div>
          <div className="h-full rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-4 text-sm text-slate-200">
            <div className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Snapshot time</div>
            <div className="mt-2 font-mono text-xs text-slate-300">{platform.checked_at}</div>
            {live ? (
              <div className="mt-2 text-xs text-slate-500">Liveness probe: {live.timestamp}</div>
            ) : null}
          </div>
          <div className="h-full rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-4 text-sm text-slate-200">
            <div className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Scheduler</div>
            <div className="mt-2 text-slate-100">
              Due now: <span className="font-mono">{platform.scheduler.due_now_count}</span>
            </div>
            <div className="text-slate-100">
              Total schedules: <span className="font-mono">{platform.scheduler.total_schedules}</span>
            </div>
            <div className="mt-2 text-xs text-slate-500">
              Internal API token: {platform.scheduler.internal_api_configured ? "configured" : "not set"}
            </div>
            <div className="mt-2 text-xs text-slate-500">
              Runtime id env: {platform.scheduler.scheduler_runtime_id_configured ? "set" : "not set"}
            </div>
            <div className="mt-1 text-xs text-slate-500">
              Active leases: <span className="font-mono text-slate-400">{platform.scheduler.lease_active_count}</span>
              {" · "}
              Stale: <span className="font-mono text-slate-400">{platform.scheduler.stale_lease_count}</span>
            </div>
          </div>
        </div>
      ) : null}

      {platform ? (
        <SectionPanel
          title="Modules"
          description="Per-domain health signals and safe counters. Readiness still requires POST /health/ready for orchestrators."
        >
          <div className="overflow-hidden rounded-[24px] border border-white/8 bg-black/10">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse text-left text-sm text-slate-200">
                <thead className="border-b border-white/10 text-xs uppercase tracking-[0.14em] text-slate-500">
                  <tr>
                    <th className="py-2 pr-3 font-medium">Module</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                    <th className="py-2 font-medium">Details</th>
                  </tr>
                </thead>
                <tbody>
                  {platform.services.map((s) => (
                    <tr key={s.name} className="border-b border-white/[0.06]">
                      <td className="py-2 pr-3 font-mono text-xs text-slate-300">{s.name}</td>
                      <td className="py-2 pr-3">
                        <span
                          className={`rounded-lg border px-2 py-0.5 text-[11px] font-semibold uppercase ${toneClasses(serviceHealthTone(s.status))}`}
                        >
                          {s.status}
                        </span>
                      </td>
                      <td className="py-2 font-mono text-xs text-slate-400">
                        {Object.keys(s.details).length === 0 ? "—" : JSON.stringify(s.details)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </SectionPanel>
      ) : null}

      {platform ? (
        <SectionPanel title="Scheduler note" description="Operational context only.">
          <p className="text-sm leading-6 text-slate-300">{platform.scheduler.note}</p>
        </SectionPanel>
      ) : null}

      <SectionPanel title="Related" description="Handy links for operators.">
        <ul className="space-y-2 text-sm text-indigo-200">
          <li className="text-slate-400">
            Deploy, env templates, and CI: see repository file{" "}
            <code className="rounded bg-black/20 px-1 text-slate-300">docs/deployment-guide.md</code>
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
            <span className="text-slate-500">Readiness: </span>
            <code className="text-slate-300">GET /api/v1/health/ready</code>
          </li>
          <li className="text-slate-400">
            Release checklist: <code className="rounded bg-black/20 px-1 text-slate-300">docs/release-checklist.md</code> · Acceptance:{" "}
            <code className="rounded bg-black/20 px-1 text-slate-300">make smoke</code>
          </li>
        </ul>
        <div className="mt-4">
          <ReleaseBuildMeta />
        </div>
      </SectionPanel>
    </AppShell>
  );
}
