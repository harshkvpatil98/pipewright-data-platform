"use client";

import { useId, useRef, useState } from "react";

import { cx } from "@/lib/utils";

type TooltipProps = {
  label: string;
  shortcut?: string;
  side?: "top" | "right" | "bottom";
  children: React.ReactNode;
  className?: string;
};

const SIDE_CLASSES = {
  top: "bottom-full left-1/2 -translate-x-1/2 mb-2",
  right: "left-full top-1/2 -translate-y-1/2 ml-2",
  bottom: "top-full left-1/2 -translate-x-1/2 mt-2",
} as const;

/**
 * Hover/focus tooltip. Opens after a short delay on hover so sweeping the
 * cursor across a toolbar does not flash a trail of tooltips, but opens
 * immediately on keyboard focus where there is no sweeping.
 */
export function Tooltip({ label, shortcut, side = "top", children, className }: TooltipProps) {
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const id = useId();

  const show = (immediate = false) => {
    if (timer.current) clearTimeout(timer.current);
    if (immediate) {
      setOpen(true);
      return;
    }
    timer.current = setTimeout(() => setOpen(true), 380);
  };

  const hide = () => {
    if (timer.current) clearTimeout(timer.current);
    setOpen(false);
  };

  return (
    <span
      className={cx("relative inline-flex", className)}
      onMouseEnter={() => show()}
      onMouseLeave={hide}
      onFocus={() => show(true)}
      onBlur={hide}
    >
      <span aria-describedby={open ? id : undefined} className="inline-flex">
        {children}
      </span>
      {open ? (
        <span
          role="tooltip"
          id={id}
          className={cx(
            "pointer-events-none absolute z-[60] whitespace-nowrap rounded-lg border border-line bg-[color:var(--panel-strong)] px-2.5 py-1.5 text-xs text-ink shadow-[var(--shadow-md)]",
            "animate-fade-up",
            SIDE_CLASSES[side],
          )}
        >
          {label}
          {shortcut ? (
            <kbd className="ml-2 rounded border border-line-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-ink-2">
              {shortcut}
            </kbd>
          ) : null}
        </span>
      ) : null}
    </span>
  );
}
