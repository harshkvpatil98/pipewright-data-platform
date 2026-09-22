/**
 * Is anything actually picking up background work?
 *
 * The single worst thing a data product can do is accept work it will never
 * run. A workflow run sat queued for 33 days on this very instance while
 * every dashboard read "healthy" — because health meant "the modules answer",
 * not "the work moves". This module is the one place that judgement lives:
 * pure, testable, and consumed by the Home card and the banners on the
 * Workflows and Schedules pages.
 */

export type RuntimeSignals = {
  /** Workflow runs waiting for a worker. */
  queued: number;
  /** Workflow runs currently executing. */
  running: number;
  /** ISO timestamp of the oldest queued run, if any. */
  oldestQueuedAt: string | null;
  /** Schedules whose cron slot has come due. */
  dueNow: number;
  /** Injected for tests; defaults to now. */
  now?: Date;
};

export type RuntimeAssessment = {
  level: "ok" | "waiting" | "stalled";
  /** One sentence for a banner; empty when ok. */
  message: string;
  /** Milliseconds the oldest queued run has waited (0 when none). */
  oldestWaitMs: number;
};

/** Queued work older than this with nothing running means nobody is polling. */
export const STALL_THRESHOLD_MS = 15 * 60 * 1000;

export function assessRuntime(signals: RuntimeSignals): RuntimeAssessment {
  const now = signals.now ?? new Date();
  const oldest = signals.oldestQueuedAt ? Date.parse(signals.oldestQueuedAt) : NaN;
  const oldestWaitMs =
    Number.isFinite(oldest) && oldest < now.getTime() ? now.getTime() - oldest : 0;

  const hasWaitingWork = signals.queued > 0 || signals.dueNow > 0;

  if (!hasWaitingWork) {
    return { level: "ok", message: "", oldestWaitMs };
  }

  // Something is executing, so the queue is being drained — waiting is normal.
  if (signals.running > 0) {
    return { level: "waiting", message: "", oldestWaitMs };
  }

  // Work is waiting, nothing is running. Only call it stalled once the oldest
  // waiter is past the threshold; a run queued two seconds ago is not news.
  const stalled =
    (signals.queued > 0 && oldestWaitMs > STALL_THRESHOLD_MS) ||
    // Due schedules have no queued_at; with no runner at all they count as
    // stalled immediately, because "due" already encodes lateness.
    (signals.queued === 0 && signals.dueNow > 0);

  if (!stalled) {
    return { level: "waiting", message: "", oldestWaitMs };
  }

  const parts: string[] = [];
  if (signals.queued > 0) {
    parts.push(
      `${signals.queued} workflow run${signals.queued === 1 ? "" : "s"} waiting` +
        (oldestWaitMs > 0 ? ` (oldest for ${humanDuration(oldestWaitMs)})` : ""),
    );
  }
  if (signals.dueNow > 0) {
    parts.push(`${signals.dueNow} schedule${signals.dueNow === 1 ? "" : "s"} due`);
  }

  return {
    level: "stalled",
    message:
      `Nothing is picking up background work — ${parts.join(" and ")}. ` +
      `Start the worker, or see System status.`,
    oldestWaitMs,
  };
}

/** "4 minutes", "3 hours", "33 days" — coarse on purpose; this is a banner. */
export function humanDuration(ms: number): string {
  const minutes = Math.floor(ms / 60000);
  if (minutes < 60) return `${Math.max(minutes, 1)} minute${minutes === 1 ? "" : "s"}`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} hour${hours === 1 ? "" : "s"}`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"}`;
}
