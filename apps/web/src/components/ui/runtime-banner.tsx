"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { assessRuntime, type RuntimeAssessment } from "@/lib/runtime-health";

type RuntimeComponent = { component: string; healthy?: boolean; status?: string };

type StatusPayload = {
  services: { name: string; details?: Record<string, unknown> }[];
  scheduler?: { due_now_count?: number };
  runtime?: { components?: RuntimeComponent[] };
};

/**
 * Ground truth from heartbeats: `true` = a fresh beat, `false` = confirmed
 * down (a beat exists but is stale, or the component is expected and absent),
 * `null` = no runtime data at all, so the caller falls back to inference.
 */
function componentAlive(status: StatusPayload, name: string): boolean | null {
  const components = status.runtime?.components;
  if (!Array.isArray(components) || components.length === 0) return null;
  const matches = components.filter((c) => c.component === name);
  if (matches.length === 0) return false;
  return matches.some((c) => c.healthy === true);
}

/** Pull the runtime signals out of the platform status payload. */
export function runtimeSignalsFromStatus(status: StatusPayload) {
  const workflows = status.services.find((s) => s.name === "service-workflows");
  const details = (workflows?.details ?? {}) as Record<string, unknown>;
  return {
    queued: Number(details.runs_queued ?? 0),
    running: Number(details.runs_running ?? 0),
    oldestQueuedAt:
      typeof details.oldest_queued_at === "string" ? details.oldest_queued_at : null,
    dueNow: Number(status.scheduler?.due_now_count ?? details.schedules_due_now ?? 0),
    workerAlive: componentAlive(status, "workflow-worker"),
    tickerAlive: componentAlive(status, "schedule-ticker"),
  };
}

/**
 * "Nothing is picking up background work" — shown on the pages where a user
 * is about to hand work to the runtime (Workflows, Schedules), so the promise
 * and the warning live on the same screen.
 */
export function RuntimeBanner() {
  const [assessment, setAssessment] = useState<RuntimeAssessment | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch<StatusPayload>("/status")
      .then((status) => {
        if (!cancelled) setAssessment(assessRuntime(runtimeSignalsFromStatus(status)));
      })
      .catch(() => {
        // Status being unreachable is its own problem; this banner only
        // reports a healthy-looking queue that nobody is draining.
        if (!cancelled) setAssessment(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!assessment || assessment.level !== "stalled") return null;

  return (
    <div
      role="alert"
      className="mb-4 flex items-start gap-2.5 rounded-xl border border-warning-line bg-warning-soft px-3.5 py-2.5 text-[13px] text-warning"
    >
      <Icon name="warning" size={15} className="mt-0.5 shrink-0" />
      <div>
        {assessment.message}{" "}
        <Link href="/system-status" className="underline underline-offset-2">
          System status
        </Link>
      </div>
    </div>
  );
}
