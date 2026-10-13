"use client";

import { useEffect, useState } from "react";

import type { SessionPolicy } from "@platform/shared-types";

import { apiFetch } from "@/lib/api/client";

/** How long a session lasts here, said plainly, with the address the platform sees. */
export function SessionPolicyNote() {
  const [policy, setPolicy] = useState<SessionPolicy | null>(null);

  useEffect(() => {
    apiFetch<SessionPolicy>("/auth/session-policy")
      .then(setPolicy)
      .catch(() => setPolicy(null));
  }, []);

  if (!policy) return null;
  return (
    <div className="mb-5 rounded-xl border border-line bg-surface px-4 py-3 text-[14px] text-ink-2">
      <p>
        You are signed out after {policy.idle_timeout_minutes} minutes without activity, and{" "}
        {policy.session_limit_hours} hours after signing in however busy you are.
      </p>
      {policy.address ? (
        <p className="mt-1 text-[13px] text-ink-3">You are connecting from {policy.address}.</p>
      ) : null}
    </div>
  );
}
