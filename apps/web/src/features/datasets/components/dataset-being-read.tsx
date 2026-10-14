"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type { PipelineRunRecord } from "@platform/shared-types";
import { Icon } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";

type RunEvent = { message?: string };

/**
 * A large upload is read by the background worker (A7, X3). This follows its
 * run, says the latest step in words, and refreshes the page once the file is
 * ready or has failed, so nobody has to reload to find out.
 */
export function DatasetBeingRead({ projectId, runId }: { projectId: string; runId: string }) {
  const router = useRouter();
  const [run, setRun] = useState<PipelineRunRecord | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const latest = await apiFetch<PipelineRunRecord>(`/projects/${projectId}/runs/${runId}`);
        if (cancelled) return;
        setRun(latest);
        if (latest.status === "succeeded" || latest.status === "failed") {
          router.refresh();
          return;
        }
      } catch {
        // A missed poll is not news; the next one tries again.
      }
      if (!cancelled) timer = window.setTimeout(poll, 2000);
    };
    timer = window.setTimeout(poll, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [projectId, runId, router]);

  const events = ((run?.logs_json?.events as RunEvent[] | undefined) ?? []).filter((event) => event.message);
  const latest = events.at(-1)?.message ?? "Waiting for the background worker.";

  if (run?.status === "failed") {
    // Shown until the refreshed page arrives with the reason, and in its place
    // if the dataset was not told: never a spinner over a run that has ended.
    return (
      <div role="alert" className="rounded-xl border border-danger-line bg-danger-soft px-4 py-3">
        <div className="text-[15px] font-medium text-danger">This file could not be read</div>
        <p className="mt-1 text-[14px] text-ink-2">{latest}</p>
      </div>
    );
  }

  return (
    <div
      role="status"
      className="rounded-xl border border-[color:var(--accent-line)] bg-[color:var(--accent-faint)] px-4 py-3"
    >
      <div className="flex items-center gap-2 text-[15px] font-medium text-ink">
        <Icon name="refresh" size={15} className="animate-spin text-[color:var(--accent-muted)]" />
        Reading this file
      </div>
      <p className="mt-1 text-[14px] text-ink-2">{latest}</p>
      <p className="mt-1 text-[13px] text-ink-3">
        Large files are read in the background. This page updates by itself, and you can leave it and come back.
      </p>
    </div>
  );
}
