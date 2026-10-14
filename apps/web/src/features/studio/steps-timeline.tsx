"use client";

import { useEffect, useRef, useState } from "react";

import { StepEditor } from "@/features/studio/step-editor";
import { STEP_BY_TYPE } from "@/features/studio/step-catalog";
import { describeStep } from "@/features/studio/step-summary";
import { describeToolStep, ToolStepEditor } from "@/features/studio/tools/tool-step-editor";
import type { Tool } from "@/features/studio/tools/tool-catalogue";
import { friendlyStepMessage } from "@/lib/labels";
import { cx } from "@/lib/utils";
import { Icon } from "@platform/shared-ui";
import { countOf, formatCount, formatSignedCount } from "@/lib/format";

export type TimelineStep = { uid: string; step_type: string; config: Record<string, unknown> };

export type StepOutcome = {
  rows_before: number;
  rows_after: number;
  columns_before: number;
  columns_after: number;
};

type StepsTimelineProps = {
  sourceName: string | null;
  source: { rows: number; columns: number } | null;
  result: { rows: number; columns: number } | null;
  steps: TimelineStep[];
  outcomes: StepOutcome[] | undefined;
  openUid: string | null;
  onOpen: (uid: string | null) => void;
  onChange: (uid: string, config: Record<string, unknown>) => void;
  onMove: (uid: string, direction: -1 | 1) => void;
  onRemove: (uid: string) => void;
  onAdd: () => void;
  onTemplates: (() => void) | null;
  /** A problem with the recipe as it stands, shown under the open step. */
  problem: { message: string; incomplete: boolean } | null;
  tools: Tool[];
  columns: { name: string; type?: string }[];
  datasets: { id: string; name: string }[];
};

/**
 * The recipe, top to bottom: where the data comes from, each step, and what
 * comes out. A step's settings open under it, so the thing being changed and
 * the place it is changed are never a screen apart.
 */
export function StepsTimeline({
  sourceName,
  source,
  result,
  steps,
  outcomes,
  openUid,
  onOpen,
  onChange,
  onMove,
  onRemove,
  onAdd,
  onTemplates,
  problem,
  tools,
  columns,
  datasets,
}: StepsTimelineProps) {
  const datasetNames = new Map(datasets.map((item) => [item.id, item.name]));
  const openRef = useRef<HTMLLIElement>(null);

  // Bring a newly opened step's settings into view.
  useEffect(() => {
    openRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [openUid]);

  return (
    <div data-tour="applied-steps" className="flex-1 overflow-y-auto px-3 py-3">
      <ol className="relative">
        <Endpoint
          label={sourceName ?? "No data chosen"}
          detail={source ? `${countOf(source.rows, "row")} · ${countOf(source.columns, "column")}` : null}
          kind="source"
        />

        {steps.map((step, index) => {
          const definition = STEP_BY_TYPE.get(step.step_type);
          const asTool = step.step_type === "tool" ? describeToolStep(step.config, tools) : null;
          const label = asTool?.label ?? definition?.label ?? humanise(step.step_type);
          const detail = asTool?.detail ?? (definition ? describeStep(step.step_type, step.config, datasetNames) : "");
          const open = step.uid === openUid;
          return (
            <li key={step.uid} ref={open ? openRef : undefined} className="relative pl-8">
              <Rail />
              <span
                className={cx(
                  "tabular absolute left-0 top-2.5 z-10 flex h-6 w-6 items-center justify-center rounded-full border text-[12px] font-medium",
                  open
                    ? "border-[color:var(--accent)] bg-[color:var(--accent)] text-accent-ink"
                    : "border-line-strong bg-surface text-ink-3",
                )}
              >
                {index + 1}
              </span>
              <div
                className={cx(
                  "mb-2 rounded-xl border transition",
                  open
                    ? "border-[color:var(--accent-soft)] bg-[color:var(--panel-strong)] shadow-[var(--shadow-sm)]"
                    : "border-transparent hover:border-line hover:bg-surface",
                )}
              >
                <button
                  type="button"
                  onClick={() => onOpen(open ? null : step.uid)}
                  aria-expanded={open}
                  className="flex min-h-11 w-full items-center gap-2.5 px-3 py-2 text-left"
                >
                  <Icon
                    name={definition?.icon ?? (asTool ? "sparkles" : "transform")}
                    size={15}
                    className={open ? "shrink-0 text-[color:var(--accent-muted)]" : "shrink-0 text-ink-3"}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] font-medium text-ink">{label}</span>
                    <span className={cx("block truncate text-[13px]", detail ? "text-ink-3" : "italic text-muted")}>
                      {detail || "Not set up yet"}
                    </span>
                  </span>
                  <Delta outcome={outcomes?.[index]} />
                </button>

                {open ? (
                  <div className="border-t border-line px-3 pb-3 pt-3">
                    {problem ? (
                      <p
                        role="status"
                        className={cx(
                          "mb-3 flex items-start gap-2 rounded-lg px-2.5 py-2 text-[13px]",
                          problem.incomplete ? "bg-info-soft text-info" : "bg-danger-soft text-danger",
                        )}
                      >
                        <Icon name={problem.incomplete ? "info" : "warning"} size={14} className="mt-0.5 shrink-0" />
                        <span>
                          <span className="font-medium">
                            {problem.incomplete ? "Finish setting up this step. " : "This step cannot run. "}
                          </span>
                          {friendlyStepMessage(problem.message)}
                        </span>
                      </p>
                    ) : null}

                    {step.step_type === "tool" ? (
                      <ToolStepEditor
                        compact
                        config={step.config}
                        tools={tools}
                        columns={columns}
                        onChange={(config) => onChange(step.uid, config)}
                      />
                    ) : definition ? (
                      <StepEditor
                        definition={definition}
                        config={step.config}
                        columns={columns.map((column) => column.name)}
                        datasets={datasets}
                        onChange={(config) => onChange(step.uid, config)}
                      />
                    ) : (
                      <UnknownStepEditor config={step.config} onChange={(config) => onChange(step.uid, config)} />
                    )}

                    <div className="mt-4 flex items-center gap-1 border-t border-line pt-3">
                      <StepButton
                        icon="chevronDown"
                        iconClassName="rotate-180"
                        label="Move this step up"
                        iconOnly
                        disabled={index === 0}
                        onClick={() => onMove(step.uid, -1)}
                      />
                      <StepButton
                        icon="chevronDown"
                        label="Move this step down"
                        iconOnly
                        disabled={index === steps.length - 1}
                        onClick={() => onMove(step.uid, 1)}
                      />
                      <StepButton
                        icon="trash"
                        label="Remove"
                        ariaLabel="Remove this step"
                        tone="danger"
                        onClick={() => onRemove(step.uid)}
                      />
                      <button
                        type="button"
                        onClick={() => onOpen(null)}
                        className="ml-auto rounded-lg px-3 py-1.5 text-[13px] font-medium text-ink transition hover:bg-surface-2"
                      >
                        Done
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}

        <li className="relative pl-8">
          <Rail />
          <span className="absolute left-0 top-2 z-10 flex h-6 w-6 items-center justify-center rounded-full border border-dashed border-line-strong bg-surface text-muted">
            <Icon name="plus" size={12} />
          </span>
          <div className="mb-2 space-y-2">
            <button
              type="button"
              data-tour="add-step"
              onClick={onAdd}
              className="flex h-10 w-full items-center justify-between gap-2 rounded-xl border border-dashed border-[color:var(--accent-soft)] bg-[color:var(--accent-faint)] px-3 text-[14px] font-medium text-ink transition hover:brightness-105"
            >
              <span className="flex items-center gap-2">
                <Icon name="plus" size={15} />
                Add a step
              </span>
              <kbd className="rounded border border-line bg-surface px-1.5 font-mono text-[12px] text-ink-3">/</kbd>
            </button>
            {steps.length === 0 ? (
              <div className="rounded-xl border border-line bg-surface px-3 py-3">
                <p className="text-[13px] leading-5 text-ink-3">
                  Each step changes the data a little: trim spaces, remove empty rows, rename a
                  column. Your original data is never changed.
                </p>
                {onTemplates ? (
                  <button
                    type="button"
                    onClick={onTemplates}
                    className="mt-2.5 inline-flex items-center gap-1.5 text-[13px] font-medium text-[color:var(--accent-muted)] hover:underline"
                  >
                    <Icon name="sparkles" size={14} />
                    Or start from a template
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        </li>

        <Endpoint
          label="Result"
          detail={result ? `${countOf(result.rows, "row")} · ${countOf(result.columns, "column")}` : null}
          kind="result"
        />
      </ol>
    </div>
  );
}

function Rail() {
  return <span className="absolute bottom-0 left-[11px] top-0 w-px bg-line" aria-hidden="true" />;
}

function Endpoint({ label, detail, kind }: { label: string; detail: string | null; kind: "source" | "result" }) {
  return (
    <li className="relative pl-8">
      {kind === "source" ? (
        <span className="absolute bottom-0 left-[11px] top-4 w-px bg-line" aria-hidden="true" />
      ) : (
        <span className="absolute left-[11px] top-0 h-4 w-px bg-line" aria-hidden="true" />
      )}
      <span
        className={cx(
          "absolute left-0 top-2 z-10 flex h-6 w-6 items-center justify-center rounded-full",
          kind === "source" ? "bg-surface-2 text-ink-2" : "bg-success-soft text-success",
        )}
      >
        <Icon name={kind === "source" ? "database" : "check"} size={13} />
      </span>
      <div className={cx("px-3 py-1.5", kind === "source" ? "mb-2" : "")}>
        <div className="truncate text-[14px] font-medium text-ink">{label}</div>
        {detail ? <div className="tabular text-[13px] text-ink-3">{detail}</div> : null}
      </div>
    </li>
  );
}

function StepButton({
  icon,
  label,
  onClick,
  disabled = false,
  tone = "neutral",
  iconClassName,
  ariaLabel,
  iconOnly = false,
}: {
  icon: "chevronDown" | "trash";
  label: string;
  ariaLabel?: string;
  /** Show only the icon; the label becomes its name and tooltip. */
  iconOnly?: boolean;
  onClick: () => void;
  disabled?: boolean;
  tone?: "neutral" | "danger";
  iconClassName?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={iconOnly ? label : ariaLabel}
      title={iconOnly ? label : undefined}
      className={cx(
        "flex h-8 items-center gap-1.5 rounded-lg text-[13px] transition disabled:opacity-30",
        iconOnly ? "w-8 justify-center" : "px-2",
        tone === "danger" ? "text-ink-3 hover:bg-danger-soft hover:text-danger" : "text-ink-3 hover:bg-surface-2 hover:text-ink",
      )}
    >
      <Icon name={icon} size={iconOnly ? 15 : 13} className={iconClassName} />
      {iconOnly ? null : label}
    </button>
  );
}

/** Rows and columns a step removed or added; silent when it changed neither. */
function Delta({ outcome }: { outcome?: StepOutcome }) {
  if (!outcome) return null;
  const rows = outcome.rows_after - outcome.rows_before;
  const columns = outcome.columns_after - outcome.columns_before;
  if (rows === 0 && columns === 0) return null;
  const parts: string[] = [];
  if (rows !== 0) parts.push(`${formatSignedCount(rows)} ${Math.abs(rows) === 1 ? "row" : "rows"}`);
  if (columns !== 0) parts.push(`${formatSignedCount(columns)} ${Math.abs(columns) === 1 ? "col" : "cols"}`);
  return (
    <span
      className={cx("tabular shrink-0 text-[12px]", rows < 0 || columns < 0 ? "text-warning" : "text-ink-3")}
      title={`${formatCount(outcome.rows_before)} → ${countOf(outcome.rows_after, "row")}`}
    >
      {parts.join(", ")}
    </span>
  );
}

/** A step this version of the Studio has no settings for: shown as text, never dropped. */
function UnknownStepEditor({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
}) {
  const [text, setText] = useState(() => JSON.stringify(config, null, 2));
  const [invalid, setInvalid] = useState(false);
  return (
    <div>
      <p className="mb-2 text-[13px] text-ink-3">
        The Studio has no settings form for this kind of step. Its settings are shown as text and
        are kept as they are when you save.
      </p>
      <textarea
        value={text}
        spellCheck={false}
        onChange={(event) => {
          const next = event.target.value;
          setText(next);
          try {
            const parsed = JSON.parse(next);
            if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
              setInvalid(false);
              onChange(parsed as Record<string, unknown>);
            } else setInvalid(true);
          } catch {
            setInvalid(true);
          }
        }}
        rows={6}
        className="w-full rounded-lg border border-line bg-sunken p-2 font-mono text-[12px] text-ink outline-none focus:border-[color:var(--accent)]"
      />
      {invalid ? <p className="mt-1 text-[12px] text-danger">That is not valid JSON yet; the last valid settings are kept.</p> : null}
    </div>
  );
}

function humanise(stepType: string): string {
  const words = stepType.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}
