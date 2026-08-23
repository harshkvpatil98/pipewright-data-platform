"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { cx } from "@/lib/utils";

import { exampleLine, type Tool } from "./tool-catalogue";

type Props = {
  column: string;
  columnType?: string;
  tools: Tool[];
  at: { x: number; y: number };
  onPick: (tool: Tool) => void;
  onBrowseAll: () => void;
  onClose: () => void;
};

/** How many tools to show before "browse all". A menu is a shortcut, not a list. */
const SHOWN = 10;

export function ColumnMenu({
  column,
  columnType,
  tools,
  at,
  onPick,
  onBrowseAll,
  onClose,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState(at);

  // Measure after paint and pull the menu back on screen. A context menu that
  // opens half off the bottom of the window is worse than no context menu.
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const box = element.getBoundingClientRect();
    setPosition({
      x: Math.min(at.x, window.innerWidth - box.width - 8),
      y: Math.min(at.y, window.innerHeight - box.height - 8),
    });
  }, [at]);

  useEffect(() => {
    const dismiss = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) onClose();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("mousedown", dismiss);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", dismiss);
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const shown = tools.slice(0, SHOWN);

  return (
    <div
      ref={ref}
      role="menu"
      aria-label={`Tools for ${column}`}
      style={{ left: position.x, top: position.y }}
      className="fixed z-50 w-72 overflow-hidden rounded-xl border border-line bg-surface shadow-lg"
    >
      <div className="border-b border-line px-3 py-2">
        <p className="truncate text-sm text-ink">{column}</p>
        <p className="text-xs text-muted">
          {columnType ? `${columnType} · ` : ""}
          {tools.length} tool{tools.length === 1 ? "" : "s"} suit this column
        </p>
      </div>
      <ul className="max-h-80 overflow-y-auto py-1">
        {shown.map((tool) => (
          <li key={tool.name}>
            <button
              type="button"
              role="menuitem"
              onClick={() => onPick(tool)}
              className={cx(
                "w-full px-3 py-2 text-left text-sm text-ink transition hover:bg-sunken",
              )}
            >
              <span className="block">{tool.title}</span>
              {exampleLine(tool) ? (
                <span className="block font-mono text-xs text-muted">{exampleLine(tool)}</span>
              ) : null}
            </button>
          </li>
        ))}
      </ul>
      <button
        type="button"
        role="menuitem"
        onClick={onBrowseAll}
        className="w-full border-t border-line px-3 py-2 text-left text-xs uppercase tracking-[0.14em] text-muted transition hover:bg-sunken hover:text-ink"
      >
        All tools for this column…
      </button>
    </div>
  );
}
