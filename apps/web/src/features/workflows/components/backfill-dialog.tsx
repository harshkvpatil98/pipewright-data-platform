"use client";

import { useCallback, useEffect, useId, useState } from "react";

import { useToast } from "@/components/providers/toast-provider";
import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";

type BackfillPreview = {
  interval: string;
  slot_count: number;
  first_slot: string | null;
  last_slot: string | null;
  sample_slots: string[];
};

type BackfillResult = {
  interval: string;
  runs_queued: number;
  run_ids: string[];
};

type BackfillDialogProps = {
  projectId: string;
  workflowId: string;
  onClose: () => void;
  onQueued: () => void;
};

const INTERVALS = ["hourly", "daily", "weekly", "monthly"] as const;

const inputClass =
  "h-9 w-full rounded-lg border border-line bg-sunken px-2.5 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)] focus:ring-2 focus:ring-[color:var(--accent-soft)]";

function isoDay(offsetDays: number): string {
  const date = new Date();
  date.setDate(date.getDate() + offsetDays);
  return date.toISOString().slice(0, 10);
}

/**
 * Replay a workflow across past dates.
 *
 * The preview is deliberately mandatory-feeling: a backfill queues real runs
 * that write real data, so the count and range are shown before anything is
 * committed.
 */
export function BackfillDialog({
  projectId,
  workflowId,
  onClose,
  onQueued,
}: BackfillDialogProps) {
  const toast = useToast();
  const fieldId = useId();

  const [start, setStart] = useState(isoDay(-7));
  const [end, setEnd] = useState(isoDay(0));
  const [interval, setInterval] = useState<(typeof INTERVALS)[number]>("daily");
  const [preview, setPreview] = useState<BackfillPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [queueing, setQueueing] = useState(false);

  const loadPreview = useCallback(async () => {
    setError(null);
    setPreview(null);
    try {
      const response = await apiFetch<BackfillPreview>(
        `/projects/${projectId}/workflows/${workflowId}/backfill/preview`,
        {
          method: "POST",
          body: JSON.stringify({
            start: `${start}T00:00:00Z`,
            end: `${end}T00:00:00Z`,
            interval,
          }),
        },
      );
      setPreview(response);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    }
  }, [projectId, workflowId, start, end, interval]);

  // Re-preview whenever the range changes, debounced so typing a date is smooth.
  useEffect(() => {
    const timer = setTimeout(() => void loadPreview(), 300);
    return () => clearTimeout(timer);
  }, [loadPreview]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const queue = async () => {
    setQueueing(true);
    try {
      const result = await apiFetch<BackfillResult>(
        `/projects/${projectId}/workflows/${workflowId}/backfill`,
        {
          method: "POST",
          body: JSON.stringify({
            start: `${start}T00:00:00Z`,
            end: `${end}T00:00:00Z`,
            interval,
          }),
        },
      );
      toast.success(
        `Queued ${result.runs_queued} run${result.runs_queued === 1 ? "" : "s"}`,
        "They run oldest slot first as workers pick them up.",
      );
      onQueued();
      onClose();
    } catch (caught) {
      toast.error("Could not start the backfill", extractErrorMessage(caught));
      setQueueing(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center px-4">
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-scrim backdrop-blur-sm"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Backfill"
        className="animate-fade-up relative w-full max-w-lg overflow-hidden rounded-2xl border border-line bg-[color:var(--panel-strong)] shadow-[var(--shadow-lg)]"
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <div>
            <h2 className="text-[14px] font-semibold text-ink">Backfill</h2>
            <p className="mt-0.5 text-[12px] text-muted">
              Replay this workflow across past dates, one run per slot.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close backfill"
            className="rounded p-1 text-muted transition hover:bg-surface-2 hover:text-ink"
          >
            <Icon name="close" size={14} />
          </button>
        </div>

        <div className="space-y-3.5 px-5 py-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label
                htmlFor={`${fieldId}-start`}
                className="mb-1.5 block text-[12px] font-medium text-ink"
              >
                From
              </label>
              <input
                id={`${fieldId}-start`}
                type="date"
                className={inputClass}
                value={start}
                onChange={(event) => setStart(event.target.value)}
              />
            </div>
            <div>
              <label
                htmlFor={`${fieldId}-end`}
                className="mb-1.5 block text-[12px] font-medium text-ink"
              >
                Until (exclusive)
              </label>
              <input
                id={`${fieldId}-end`}
                type="date"
                className={inputClass}
                value={end}
                onChange={(event) => setEnd(event.target.value)}
              />
            </div>
          </div>

          <div>
            <span className="mb-1.5 block text-[12px] font-medium text-ink">Interval</span>
            <div className="flex rounded-lg border border-line p-0.5">
              {INTERVALS.map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setInterval(value)}
                  className={cx(
                    "flex-1 rounded-md px-2 py-1.5 text-[12px] capitalize transition",
                    interval === value
                      ? "bg-[color:var(--accent)] text-accent-ink"
                      : "text-ink-3 hover:text-ink",
                  )}
                >
                  {value}
                </button>
              ))}
            </div>
          </div>

          {error ? (
            <div className="flex items-start gap-2 rounded-lg border border-danger-line bg-danger-soft px-3 py-2.5 text-[12px] text-danger">
              <Icon name="warning" size={13} className="mt-0.5 shrink-0" />
              {error}
            </div>
          ) : preview ? (
            <div className="rounded-lg border border-line bg-surface px-3 py-2.5">
              <div className="text-[13px] text-ink">
                {preview.slot_count} run{preview.slot_count === 1 ? "" : "s"} will be queued
              </div>
              <div className="mt-1 text-[11.5px] text-muted">
                {preview.first_slot?.slice(0, 10)} through {preview.last_slot?.slice(0, 10)}
              </div>
              {preview.sample_slots.length > 0 ? (
                <div className="mt-2 flex flex-wrap gap-1">
                  {preview.sample_slots.map((slot) => (
                    <span
                      key={slot}
                      className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-ink-3"
                    >
                      {slot.slice(0, 10)}
                    </span>
                  ))}
                  {preview.slot_count > preview.sample_slots.length ? (
                    <span className="px-1 py-0.5 text-[10px] text-muted">
                      +{preview.slot_count - preview.sample_slots.length} more
                    </span>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="rounded-lg border border-line px-3 py-2.5 text-[12px] text-muted">
              Checking the range…
            </div>
          )}

          <p className="text-[11px] leading-5 text-muted">
            Each run resolves date macros to its own slot, so{" "}
            <code className="rounded bg-surface-2 px-1 font-mono text-[10px]">
              {"{{ ds }}"}
            </code>{" "}
            is the date being reprocessed, not today.
          </p>
        </div>

        <div className="flex justify-end gap-2 border-t border-line px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-line px-3.5 py-2 text-[12.5px] text-ink transition hover:bg-surface-2"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={queue}
            disabled={queueing || !preview || preview.slot_count === 0}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[color:var(--accent)] px-3.5 py-2 text-[12.5px] font-medium text-accent-ink transition hover:brightness-110 disabled:opacity-40"
          >
            <Icon name="play" size={12} />
            {queueing
              ? "Queueing…"
              : preview
                ? `Queue ${preview.slot_count} run${preview.slot_count === 1 ? "" : "s"}`
                : "Queue"}
          </button>
        </div>
      </div>
    </div>
  );
}
