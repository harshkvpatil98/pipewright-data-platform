"use client";

import { useRef } from "react";

import { cx } from "./internal/cx";

export type TabItem<T extends string> = {
  id: T;
  label: string;
  /** A count shown after the label, such as the number of open items. */
  count?: number;
  disabled?: boolean;
  /** A tab whose content failed reads in the danger colour. */
  tone?: "danger";
  /** The longer explanation, on hover. */
  title?: string;
};

type TabsProps<T extends string> = {
  items: TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  /** What the tabs switch between, for screen readers. */
  label: string;
  className?: string;
};

/**
 * Views of one thing, one at a time. Arrow keys move between tabs, as people
 * who use a keyboard expect from a tab list.
 */
export function Tabs<T extends string>({ items, value, onChange, label, className }: TabsProps<T>) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const enabled = items.filter((item) => !item.disabled);

  const move = (offset: number) => {
    const index = enabled.findIndex((item) => item.id === value);
    const next = enabled[(index + offset + enabled.length) % enabled.length];
    if (!next) return;
    onChange(next.id);
    refs.current[items.indexOf(next)]?.focus();
  };

  return (
    <div role="tablist" aria-label={label} className={cx("flex gap-1 overflow-x-auto border-b border-line", className)}>
      {items.map((item, index) => {
        const selected = item.id === value;
        return (
          <button
            key={item.id}
            ref={(node) => {
              refs.current[index] = node;
            }}
            type="button"
            role="tab"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            disabled={item.disabled}
            title={item.title}
            onClick={() => onChange(item.id)}
            onKeyDown={(event) => {
              if (event.key === "ArrowRight") {
                event.preventDefault();
                move(1);
              } else if (event.key === "ArrowLeft") {
                event.preventDefault();
                move(-1);
              }
            }}
            className={cx(
              "-mb-px inline-flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-[13px] font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
              selected ? "border-[color:var(--accent)] text-ink" : "border-transparent text-ink-3 hover:text-ink",
              item.tone === "danger" && "text-danger",
            )}
          >
            {item.label}
            {item.count !== undefined ? (
              <span className="rounded-full bg-surface-2 px-1.5 text-[12px] text-ink-3">{item.count}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
