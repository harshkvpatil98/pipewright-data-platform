"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Icon } from "@platform/shared-ui";

import { componentAlive, type StatusPayload } from "@/components/ui/runtime-banner";
import { apiFetch } from "@/lib/api/client";

/**
 * Live feeds are read by the live feed runner, a background process of its
 * own. When its heartbeat says it is not running, nothing is read or saved,
 * and the pages that promise "read every 5 seconds" say so.
 */
export function LiveRunnerBanner() {
  const [down, setDown] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiFetch<StatusPayload>("/status")
      .then((status) => {
        if (!cancelled) setDown(componentAlive(status, "live-runner") === false);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  if (!down) return null;
  return (
    <div
      role="alert"
      className="flex items-start gap-2.5 rounded-xl border border-warning-line bg-warning-soft px-3.5 py-2.5 text-[13px] text-warning"
    >
      <Icon name="warning" size={15} className="mt-0.5 shrink-0" />
      <div>
        The live feed runner is not running, so nothing is read or saved until it starts. &ldquo;Read now&rdquo; still
        works.{" "}
        <Link href="/system-status" className="font-medium underline underline-offset-2">
          See what is running
        </Link>
      </div>
    </div>
  );
}
