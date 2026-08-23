"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { Icon, type IconName } from "@/components/ui/icon";
import { cx } from "@/lib/utils";

export type Command = {
  id: string;
  label: string;
  group: string;
  icon: IconName;
  hint?: string;
  href?: string;
  run?: () => void;
  /**
   * Other words that should find this command, space separated.
   *
   * Nobody searches for "Title Case" by typing "initcap", and with a library of
   * hundreds the palette is only as good as the words people actually reach for.
   */
  keywords?: string;
};

type CommandPaletteProps = {
  open: boolean;
  onClose: () => void;
  commands: Command[];
};

/**
 * Subsequence match: "dq" matches "Data quality". Scores earlier and more
 * contiguous matches higher so the obvious result lands first.
 */
function score(query: string, text: string): number {
  if (!query) return 1;
  const haystack = text.toLowerCase();
  const needle = query.toLowerCase();

  const direct = haystack.indexOf(needle);
  if (direct === 0) return 1000;
  if (direct > 0) return 500 - direct;

  let cursor = 0;
  let points = 0;
  let previous = -1;
  for (const character of needle) {
    const found = haystack.indexOf(character, cursor);
    if (found === -1) return 0;
    points += found === previous + 1 ? 6 : 2;
    if (found === 0 || haystack[found - 1] === " ") points += 4;
    previous = found;
    cursor = found + 1;
  }
  return points;
}

/** How well one command matches a query. Exported so the ranking is testable. */
export function scoreCommand(query: string, command: Command): number {
  return Math.max(
    score(query, command.label),
    score(query, command.group) * 0.4,
    // Weighted below the label so an exact title still wins, but above the
    // group so a synonym beats a category that merely contains the query.
    command.keywords ? score(query, command.keywords) * 0.7 : 0,
  );
}


export function CommandPalette({ open, onClose, commands }: CommandPaletteProps) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const results = useMemo(() => {
    const scored = commands
      .map((command) => ({ command, value: scoreCommand(query, command) }))
      .filter((entry) => entry.value > 0)
      .sort((a, b) => b.value - a.value);
    return scored.slice(0, 12).map((entry) => entry.command);
  }, [commands, query]);

  useEffect(() => {
    setActive(0);
  }, [query]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      // Focus after paint so the caret lands reliably.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  // Keep the highlighted row in view while arrowing through results.
  useEffect(() => {
    const container = listRef.current;
    const item = container?.querySelector<HTMLElement>(`[data-index="${active}"]`);
    item?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!open) return null;

  const choose = (command: Command) => {
    onClose();
    if (command.run) command.run();
    else if (command.href) router.push(command.href);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((current) => (current + 1) % Math.max(1, results.length));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((current) => (current - 1 + results.length) % Math.max(1, results.length));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const command = results[active];
      if (command) choose(command);
    } else if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    }
  };

  return (
    <div className="fixed inset-0 z-[85] flex items-start justify-center px-4 pt-[12vh]">
      <button
        type="button"
        aria-label="Close command palette"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-scrim backdrop-blur-sm"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="animate-fade-up relative w-full max-w-xl overflow-hidden rounded-2xl border border-line bg-[color:var(--panel-strong)] shadow-[var(--shadow-lg)] backdrop-blur-xl"
        onKeyDown={onKeyDown}
      >
        <div className="flex items-center gap-3 border-b border-line px-4">
          <Icon name="search" size={17} className="shrink-0 text-muted" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search pages and actions…"
            className="h-14 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-muted"
            aria-label="Search pages and actions"
          />
          <kbd className="shrink-0 rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[10px] text-ink-3">
            esc
          </kbd>
        </div>

        <div ref={listRef} className="max-h-[52vh] overflow-y-auto p-2">
          {results.length === 0 ? (
            <p className="px-3 py-8 text-center text-sm text-muted">
              Nothing matches “{query}”.
            </p>
          ) : (
            results.map((command, index) => (
              <button
                key={command.id}
                type="button"
                data-index={index}
                onMouseEnter={() => setActive(index)}
                onClick={() => choose(command)}
                className={cx(
                  "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition duration-[var(--duration-fast)]",
                  index === active ? "bg-[color:var(--accent-faint)] text-ink" : "text-ink-2",
                )}
              >
                <span
                  className={cx(
                    "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border",
                    index === active
                      ? "border-[color:var(--accent-soft)] bg-[color:var(--accent-soft)] text-ink"
                      : "border-line bg-surface text-ink-3",
                  )}
                >
                  <Icon name={command.icon} size={15} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm">{command.label}</span>
                  <span className="block truncate text-[11px] uppercase tracking-[0.14em] text-muted">
                    {command.group}
                  </span>
                </span>
                {command.hint ? (
                  <kbd className="shrink-0 rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[10px] text-ink-3">
                    {command.hint}
                  </kbd>
                ) : (
                  <Icon name="arrowRight" size={14} className="shrink-0 text-muted" />
                )}
              </button>
            ))
          )}
        </div>

        <div className="flex items-center gap-4 border-t border-line px-4 py-2.5 text-[11px] text-muted">
          <span className="flex items-center gap-1.5">
            <kbd className="rounded border border-line px-1 font-mono">↑↓</kbd> navigate
          </span>
          <span className="flex items-center gap-1.5">
            <kbd className="rounded border border-line px-1 font-mono">↵</kbd> open
          </span>
        </div>
      </div>
    </div>
  );
}
