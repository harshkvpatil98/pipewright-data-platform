import { assessRuntime, humanDuration, STALL_THRESHOLD_MS } from "@/lib/runtime-health";

const NOW = new Date("2026-09-23T12:00:00Z");
const minutesAgo = (m: number) => new Date(NOW.getTime() - m * 60000).toISOString();

describe("assessRuntime", () => {
  it("is ok when there is simply nothing to do", () => {
    const out = assessRuntime({ queued: 0, running: 0, oldestQueuedAt: null, dueNow: 0, now: NOW });
    expect(out.level).toBe("ok");
    expect(out.message).toBe("");
  });

  it("treats a freshly queued run as normal waiting, not a stall", () => {
    const out = assessRuntime({
      queued: 1, running: 0, oldestQueuedAt: minutesAgo(2), dueNow: 0, now: NOW,
    });
    expect(out.level).toBe("waiting");
  });

  it("calls it stalled once the oldest waiter passes the threshold", () => {
    const out = assessRuntime({
      queued: 1, running: 0, oldestQueuedAt: minutesAgo(16), dueNow: 0, now: NOW,
    });
    expect(out.level).toBe("stalled");
    expect(out.message).toMatch(/Nothing is picking up background work/);
    expect(out.message).toMatch(/1 workflow run waiting/);
    expect(out.oldestWaitMs).toBeGreaterThan(STALL_THRESHOLD_MS);
  });

  it("the 33-day case that motivated this module reads as days, loudly", () => {
    const out = assessRuntime({
      queued: 1, running: 0, oldestQueuedAt: minutesAgo(33 * 24 * 60), dueNow: 0, now: NOW,
    });
    expect(out.level).toBe("stalled");
    expect(out.message).toMatch(/33 days/);
  });

  it("anything running means the queue is being drained", () => {
    const out = assessRuntime({
      queued: 5, running: 1, oldestQueuedAt: minutesAgo(120), dueNow: 3, now: NOW,
    });
    expect(out.level).toBe("waiting");
    expect(out.message).toBe("");
  });

  it("due schedules with no runner at all are stalled immediately", () => {
    const out = assessRuntime({ queued: 0, running: 0, oldestQueuedAt: null, dueNow: 2, now: NOW });
    expect(out.level).toBe("stalled");
    expect(out.message).toMatch(/2 schedules due/);
  });

  it("an unparseable timestamp degrades to waiting, never a crash", () => {
    const out = assessRuntime({
      queued: 1, running: 0, oldestQueuedAt: "not-a-date", dueNow: 0, now: NOW,
    });
    expect(out.level).toBe("waiting");
    expect(out.oldestWaitMs).toBe(0);
  });

  // Heartbeat ground truth beats queue-age inference in both directions.
  it("a confirmed-down worker is stalled the instant work arrives, before the threshold", () => {
    const out = assessRuntime({
      queued: 1, running: 0, oldestQueuedAt: minutesAgo(2), dueNow: 0, workerAlive: false, now: NOW,
    });
    expect(out.level).toBe("stalled");
    expect(out.message).toMatch(/1 workflow run waiting/);
  });

  it("a confirmed-alive worker is just waiting, even past the old threshold", () => {
    const out = assessRuntime({
      queued: 1, running: 0, oldestQueuedAt: minutesAgo(120), dueNow: 0, workerAlive: true, now: NOW,
    });
    expect(out.level).toBe("waiting");
  });

  it("a confirmed-alive ticker means due schedules are just mid-cadence, not stalled", () => {
    const out = assessRuntime({
      queued: 0, running: 0, oldestQueuedAt: null, dueNow: 2, tickerAlive: true, now: NOW,
    });
    expect(out.level).toBe("waiting");
  });

  it("a confirmed-down ticker with due schedules is stalled", () => {
    const out = assessRuntime({
      queued: 0, running: 0, oldestQueuedAt: null, dueNow: 2, tickerAlive: false, now: NOW,
    });
    expect(out.level).toBe("stalled");
    expect(out.message).toMatch(/2 schedules due/);
  });

  it("reports only the dimension that is actually stalled", () => {
    // Worker alive draining the queue, ticker down: only the schedules are news.
    const out = assessRuntime({
      queued: 3, running: 0, oldestQueuedAt: minutesAgo(120), dueNow: 2,
      workerAlive: true, tickerAlive: false, now: NOW,
    });
    expect(out.level).toBe("stalled");
    expect(out.message).toMatch(/2 schedules due/);
    expect(out.message).not.toMatch(/workflow run/);
  });
});

describe("humanDuration", () => {
  it("is coarse on purpose", () => {
    expect(humanDuration(90 * 1000)).toBe("1 minute");
    expect(humanDuration(45 * 60000)).toBe("45 minutes");
    expect(humanDuration(5 * 3600000)).toBe("5 hours");
    expect(humanDuration(33 * 24 * 3600000)).toBe("33 days");
  });
});
