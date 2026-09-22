"use client";

import Link from "next/link";

import { Icon } from "@/components/ui/icon";
import { cx } from "@/lib/utils";

export type StatusItem = {
  id: string;
  label: string;
  value: string;
  tone?: "neutral" | "good" | "warn" | "bad";
};

type StatusBarProps = {
  items: StatusItem[];
  /** Right-aligned live indicator, e.g. platform health. */
  health?: { label: string; healthy: boolean; href?: string };
};

const TONE_TEXT = {
  neutral: "text-ink-2",
  good: "text-success",
  warn: "text-warning",
  bad: "text-danger",
} as const;

/**
 * Persistent bottom strip, in the spirit of a spreadsheet status bar: cheap
 * glanceable facts that stay true while you work, never actions.
 */
export function StatusBar({ items, health }: StatusBarProps) {
  return (
    <footer
      data-tour="status-bar"
      className="flex h-7 shrink-0 items-center gap-4 border-t border-line bg-[color:var(--panel-strong)] px-4 text-[11px]"
    >
      {items.map((item) => (
        <span key={item.id} className="flex items-center gap-1.5 whitespace-nowrap">
          <span className="text-muted">{item.label}</span>
          <span className={cx("tabular font-medium", TONE_TEXT[item.tone ?? "neutral"])}>
            {item.value}
          </span>
        </span>
      ))}

      {health ? (
        (() => {
          const body = (
            <>
              <span
                className={cx(
                  "h-1.5 w-1.5 rounded-full",
                  health.healthy ? "animate-live bg-success" : "bg-danger",
                )}
                aria-hidden="true"
              />
              <span className={health.healthy ? "text-success" : "text-danger"}>
                {health.label}
              </span>
            </>
          );
          // A red light that cannot be clicked is an accusation without a
          // case file; the chip always leads to the page that explains it.
          return health.href ? (
            <Link
              href={health.href}
              className="ml-auto flex items-center gap-1.5 whitespace-nowrap hover:underline"
            >
              {body}
            </Link>
          ) : (
            <span className="ml-auto flex items-center gap-1.5 whitespace-nowrap">{body}</span>
          );
        })()
      ) : null}
    </footer>
  );
}

type InspectorProps = {
  open: boolean;
  onToggle: () => void;
  title: string;
  children: React.ReactNode;
};

/** Right-hand properties pane, the Power BI "Visualizations/Fields" position. */
export function Inspector({ open, onToggle, title, children }: InspectorProps) {
  return (
    <aside
      className={cx(
        "relative flex shrink-0 flex-col border-l border-line bg-[color:var(--panel)] transition-[width] duration-[var(--duration-base)] ease-[var(--ease-out)]",
        open ? "w-[300px]" : "w-[38px]",
      )}
      aria-label={title}
    >
      <div
        className={cx(
          "flex h-10 shrink-0 items-center border-b border-line",
          open ? "justify-between px-3" : "justify-center",
        )}
      >
        {open ? (
          <span className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted">
            {title}
          </span>
        ) : null}
        <button
          type="button"
          data-tour="inspector-toggle"
          onClick={onToggle}
          aria-label={open ? "Collapse inspector" : "Expand inspector"}
          aria-expanded={open}
          className="flex h-7 w-7 items-center justify-center rounded-lg text-muted transition hover:bg-surface-2 hover:text-ink"
        >
          <Icon name="panelRight" size={15} />
        </button>
      </div>
      {open ? (
        <div className="flex-1 overflow-y-auto p-3">{children}</div>
      ) : (
        <div className="flex flex-1 items-start justify-center pt-4">
          <span
            className="whitespace-nowrap text-[10px] uppercase tracking-[0.18em] text-muted"
            style={{ writingMode: "vertical-rl" }}
          >
            {title}
          </span>
        </div>
      )}
    </aside>
  );
}
