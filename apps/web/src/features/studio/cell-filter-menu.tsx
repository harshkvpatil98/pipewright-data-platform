"use client";

import { useEffect, useRef } from "react";

import { Icon } from "@platform/shared-ui";

/** A cell right-clicked in the preview: its column and value. */
export type PickedCell = { column: string; value: unknown };

/**
 * The step that keeps, or drops, the rows whose value in a column is this
 * one (filter and exclude by selection). Null for a value rows cannot be
 * compared with: a list or an object.
 */
export function filterBySelection(cell: PickedCell, mode: "keep" | "exclude"): Record<string, unknown> | null {
  const { column, value } = cell;
  if (value !== null && typeof value === "object") return null;
  const empty = value === null || value === undefined || value === "";
  return {
    tool: "rows.filter",
    column,
    operator: empty ? "is empty" : "equals",
    value: empty ? "" : String(value),
    mode,
  };
}

/** How the value reads in the menu: short, and "empty" for nothing. */
export function shownValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "empty";
  const text = String(value);
  return text.length > 32 ? `${text.slice(0, 31)}…` : text;
}

export function CellFilterMenu({
  cell,
  at,
  onPick,
  onClose,
}: {
  cell: PickedCell;
  at: { x: number; y: number };
  onPick: (config: Record<string, unknown>) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const away = (event: PointerEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) onClose();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("pointerdown", away);
    window.addEventListener("keydown", escape);
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => {
      window.removeEventListener("pointerdown", away);
      window.removeEventListener("keydown", escape);
    };
  }, [onClose]);

  const keep = filterBySelection(cell, "keep");
  const drop = filterBySelection(cell, "exclude");
  const value = shownValue(cell.value);
  const is = value === "empty" ? "is empty" : `is ${value}`;
  // Kept on screen near the pointer, whatever the window's size.
  const left = typeof window === "undefined" ? at.x : Math.min(at.x, window.innerWidth - 300);
  const top = typeof window === "undefined" ? at.y : Math.min(at.y, window.innerHeight - 120);
  return (
    <div
      ref={ref}
      role="menu"
      aria-label={`Rows by ${cell.column}`}
      style={{ left, top }}
      className="fixed z-50 w-[288px] rounded-xl border border-line bg-[color:var(--panel-strong)] p-1.5 shadow-[var(--shadow-lg)]"
    >
      {keep && drop ? (
        <>
          <MenuButton icon="filter" label={`Keep only rows where ${cell.column} ${is}`} onClick={() => onPick(keep)} />
          <MenuButton icon="trash" label={`Drop rows where ${cell.column} ${is}`} onClick={() => onPick(drop)} />
        </>
      ) : (
        <p className="px-2.5 py-2 text-[13px] text-ink-3">Rows cannot be filtered by a list or an object.</p>
      )}
    </div>
  );
}

function MenuButton({ icon, label, onClick }: { icon: "filter" | "trash"; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] text-ink transition hover:bg-surface-2 focus:bg-surface-2 focus:outline-none"
    >
      <Icon name={icon} size={14} className="mt-0.5 shrink-0 text-ink-3" />
      <span className="min-w-0 break-words">{label}</span>
    </button>
  );
}
