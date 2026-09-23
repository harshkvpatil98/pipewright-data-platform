"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";

type ProjectChecklistProps = {
  projectId: string;
  datasetCount: number;
  onAddData: () => void;
};

type StepState = { done: boolean };

const STORAGE_PREFIX = "pipewright.checklist.dismissed.";

/**
 * The first thing a new project shows: one path, four steps, not a wall of
 * twelve chips. Each step ticks itself from real state, so it is a live map of
 * where this project actually is — and once all four are done it disappears,
 * because a checklist that never completes is nagging, not guidance.
 *
 * The three counts it does not already have (pipelines, rules, schedules) are
 * fetched once; a project page that cannot reach them still renders the steps
 * as not-yet-done rather than breaking.
 */
export function ProjectChecklist({ projectId, datasetCount, onAddData }: ProjectChecklistProps) {
  const [pipelines, setPipelines] = useState(0);
  const [rules, setRules] = useState(0);
  const [schedules, setSchedules] = useState(0);
  const [dismissed, setDismissed] = useState(true); // assume dismissed until mount decides

  useEffect(() => {
    try {
      setDismissed(window.localStorage.getItem(STORAGE_PREFIX + projectId) === "true");
    } catch {
      setDismissed(false);
    }
    const count = (path: string, set: (n: number) => void) =>
      apiFetch<{ items?: unknown[] }>(path)
        .then((r) => set(Array.isArray(r.items) ? r.items.length : 0))
        .catch(() => set(0));
    void count(`/projects/${projectId}/pipelines`, setPipelines);
    void count(`/projects/${projectId}/data-quality/rules`, setRules);
    void count(`/projects/${projectId}/schedules`, setSchedules);
  }, [projectId]);

  const steps = useMemo(
    () => [
      {
        key: "data",
        title: "Add data",
        blurb: "Upload a file or connect a source to bring data in.",
        done: datasetCount > 0,
        action: { label: "Add data", onClick: onAddData },
      },
      {
        key: "shape",
        title: "Shape it",
        blurb: "Clean and transform it in Studio — no code required.",
        done: pipelines > 0,
        action: { label: "Open Studio", href: `/projects/${projectId}/studio` },
      },
      {
        key: "guard",
        title: "Guard it",
        blurb: "Add a quality rule so bad rows cannot pass downstream.",
        done: rules > 0,
        action: { label: "Add a rule", href: `/projects/${projectId}/data-quality` },
      },
      {
        key: "schedule",
        title: "Schedule it",
        blurb: "Run it automatically and publish the result.",
        done: schedules > 0,
        action: { label: "Add a schedule", href: `/projects/${projectId}/schedules` },
      },
    ] as (StepState & {
      key: string;
      title: string;
      blurb: string;
      action: { label: string; href?: string; onClick?: () => void };
    })[],
    [projectId, datasetCount, pipelines, rules, schedules, onAddData],
  );

  const doneCount = steps.filter((s) => s.done).length;
  const allDone = doneCount === steps.length;

  // Complete or dismissed: gone. The workspace menu carries every destination
  // from here on, so nothing is lost.
  if (dismissed || allDone) return null;

  const dismiss = () => {
    try {
      window.localStorage.setItem(STORAGE_PREFIX + projectId, "true");
    } catch {
      /* ignore */
    }
    setDismissed(true);
  };

  // The first not-yet-done step is the one to nudge.
  const activeKey = steps.find((s) => !s.done)?.key;

  return (
    <section className="mb-6 rounded-2xl border border-line bg-[color:var(--panel)] p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-[15px] font-semibold text-ink">Get this project running</h2>
          <p className="mt-0.5 text-[12px] text-muted">
            {doneCount} of {steps.length} done — the usual path from raw data to a scheduled,
            validated pipeline.
          </p>
        </div>
        <button
          type="button"
          onClick={dismiss}
          className="text-[11px] text-muted underline-offset-2 transition hover:text-ink hover:underline"
        >
          Dismiss
        </button>
      </div>

      <ol className="mt-4 grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
        {steps.map((step, index) => {
          const isActive = step.key === activeKey;
          return (
            <li
              key={step.key}
              className={`flex flex-col rounded-xl border p-3.5 transition ${
                step.done
                  ? "border-success-line bg-success-soft"
                  : isActive
                    ? "border-[color:var(--accent-soft)] bg-[color:var(--accent-faint)]"
                    : "border-line bg-surface"
              }`}
            >
              <div className="flex items-center gap-2">
                <span
                  className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${
                    step.done ? "bg-success text-accent-ink" : "bg-surface-2 text-ink-3"
                  }`}
                >
                  {step.done ? <Icon name="check" size={11} /> : index + 1}
                </span>
                <span className="text-[13px] font-medium text-ink">{step.title}</span>
              </div>
              <p className="mt-1.5 flex-1 text-[11.5px] leading-4 text-ink-3">{step.blurb}</p>
              {step.done ? (
                <span className="mt-2 text-[11px] font-medium text-success">Done</span>
              ) : step.action.href ? (
                <Link
                  href={step.action.href}
                  className="mt-2 inline-flex w-fit items-center gap-1 rounded-lg bg-[color:var(--accent)] px-2.5 py-1.5 text-[11.5px] font-medium text-accent-ink transition hover:brightness-110"
                >
                  {step.action.label}
                </Link>
              ) : (
                <button
                  type="button"
                  onClick={step.action.onClick}
                  className="mt-2 inline-flex w-fit items-center gap-1 rounded-lg bg-[color:var(--accent)] px-2.5 py-1.5 text-[11.5px] font-medium text-accent-ink transition hover:brightness-110"
                >
                  {step.action.label}
                </button>
              )}
            </li>
          );
        })}
      </ol>

      <div className="mt-4 flex flex-wrap items-center gap-x-1.5 gap-y-1 border-t border-line pt-3 text-[11.5px] text-muted">
        <Icon name="bell" size={12} className="text-ink-3" />
        <span>Failures already show up in your notifications.</span>
        <Link
          href={`/projects/${projectId}/notification-targets`}
          className="font-medium text-accent underline-offset-2 hover:underline"
        >
          Also send them to Slack or email →
        </Link>
      </div>
    </section>
  );
}
