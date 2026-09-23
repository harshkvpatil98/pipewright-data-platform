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
  /**
   * Ground truth from heartbeats, when available: is the workflow worker
   * beating? `true` = alive, `false` = confirmed down, `null`/undefined =
   * unknown, fall back to queue-age inference.
   */
  workerAlive?: boolean | null;
  /** Same, for the schedule ticker. */
  tickerAlive?: boolean | null;
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

  // Work is waiting, nothing is running. Prefer heartbeat ground truth; fall
  // back to queue-age inference only when a heartbeat is unavailable.
  //
  // Queued workflow runs: a confirmed-down worker is stalled the instant work
  // arrives (no need to wait out the threshold); a confirmed-alive worker is
  // just draining; unknown reverts to "has it waited too long?".
  const queuedStalled =
    signals.queued > 0 &&
    (signals.workerAlive === false ||
      (signals.workerAlive == null && oldestWaitMs > STALL_THRESHOLD_MS));

  // Due schedules have no queued_at, so age cannot judge them. A confirmed-alive
  // ticker is just mid-cadence; anything else (confirmed-down, or unknown —
  // which falls back to treating "due" as already-late) counts as stalled.
  const dueStalled = signals.dueNow > 0 && signals.tickerAlive !== true;

  if (!queuedStalled && !dueStalled) {
    return { level: "waiting", message: "", oldestWaitMs };
  }

  const parts: string[] = [];
  if (queuedStalled) {
    parts.push(
      `${signals.queued} workflow run${signals.queued === 1 ? "" : "s"} waiting` +
        (oldestWaitMs > 0 ? ` (oldest for ${humanDuration(oldestWaitMs)})` : ""),
    );
  }
  if (dueStalled) {
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
