"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { cx } from "@/lib/utils";

import {
  applyCompletion,
  caretPosition,
  currentWord,
  indent,
  toggleComment,
} from "./editor-state";
import type { Completion } from "./types";

/**
 * A SQL editor built from a textarea.
 *
 * Deliberately not a library. The platform draws its own charts and icons for
 * the same reason: a dependency that owns the editing surface also owns the
 * theming, the accessibility and the bundle, and the genuinely hard parts here
 * are logic that lives in `editor-state.ts` and is unit tested.
 *
 * Keyboard: Tab indents (block-aware), Cmd/Ctrl+/ comments, Cmd/Ctrl+Enter
 * runs, Cmd/Ctrl+Shift+Enter runs the statement under the cursor, Ctrl+Space
 * asks for completions, Escape dismisses them.
 */
export function SqlEditor({
  value,
  onChange,
  onRun,
  onRunStatement,
  completionsFor,
  disabled = false,
  placeholder,
}: {
  value: string;
  onChange: (next: string, selection: { start: number; end: number }) => void;
  onRun: () => void;
  onRunStatement: () => void;
  completionsFor: (sql: string, offset: number) => Promise<Completion[]>;
  disabled?: boolean;
  placeholder?: string;
}) {
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const [suggestions, setSuggestions] = useState<Completion[]>([]);
  const [active, setActive] = useState(0);
  const [caret, setCaret] = useState({ line: 1, column: 1 });
  const requestRef = useRef(0);

  const selection = () => {
    const area = areaRef.current;
    return { start: area?.selectionStart ?? 0, end: area?.selectionEnd ?? 0 };
  };

  const setText = useCallback(
    (next: string, nextSelection: { start: number; end: number }) => {
      onChange(next, nextSelection);
      // Restore the caret after React has written the new value; setting it
      // before the paint puts it at the end of the text instead.
      requestAnimationFrame(() => {
        const area = areaRef.current;
        if (!area) return;
        area.selectionStart = nextSelection.start;
        area.selectionEnd = nextSelection.end;
      });
    },
    [onChange],
  );

  const dismiss = useCallback(() => {
    setSuggestions([]);
    setActive(0);
  }, []);

  const ask = useCallback(async () => {
    const area = areaRef.current;
    if (!area) return;
    const offset = area.selectionStart;
    const ticket = ++requestRef.current;
    const found = await completionsFor(area.value, offset).catch(() => []);
    // A slower earlier request must not overwrite a newer one's answers.
    if (ticket !== requestRef.current) return;
    setSuggestions(found);
    setActive(0);
  }, [completionsFor]);

  const accept = useCallback(
    (choice: Completion) => {
      const area = areaRef.current;
      if (!area) return;
      const result = applyCompletion(area.value, area.selectionStart, choice.insert || choice.label);
      setText(result.sql, { start: result.offset, end: result.offset });
      dismiss();
    },
    [setText, dismiss],
  );

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const meta = event.metaKey || event.ctrlKey;
    const area = event.currentTarget;
    // Read what is needed now: React nullifies the synthetic event before an
    // async handler or a state updater would get to it.
    const text = area.value;
    const range = { start: area.selectionStart, end: area.selectionEnd };

    if (suggestions.length > 0) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActive((current) => (current + 1) % suggestions.length);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setActive((current) => (current - 1 + suggestions.length) % suggestions.length);
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        accept(suggestions[active]);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        dismiss();
        return;
      }
    }

    if (meta && event.key === "Enter") {
      event.preventDefault();
      if (event.shiftKey) onRunStatement();
      else onRun();
      return;
    }
    if (meta && event.key === " ") {
      event.preventDefault();
      void ask();
      return;
    }
    if (meta && event.key === "/") {
      event.preventDefault();
      const result = toggleComment(text, range);
      setText(result.sql, result.selection);
      return;
    }
    if (event.key === "Tab") {
      event.preventDefault();
      const result = indent(text, range, event.shiftKey);
      setText(result.sql, result.selection);
      return;
    }
    if (event.key === "Escape") dismiss();
  };

  useEffect(() => {
    const area = areaRef.current;
    if (area) setCaret(caretPosition(area.value, area.selectionStart));
  }, [value]);

  const word = currentWord(value, areaRef.current?.selectionStart ?? value.length);

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <textarea
        ref={areaRef}
        value={value}
        disabled={disabled}
        spellCheck={false}
        aria-label="SQL editor"
        placeholder={placeholder ?? "SELECT * FROM …\n\n⌘↵ to run · ⌘⇧↵ for this statement · ⌘Space for suggestions"}
        onChange={(event) => {
          onChange(event.target.value, selection());
          if (suggestions.length > 0) void ask();
        }}
        onKeyDown={onKeyDown}
        onKeyUp={(event) => setCaret(caretPosition(event.currentTarget.value, event.currentTarget.selectionStart))}
        onClick={(event) => {
          setCaret(caretPosition(event.currentTarget.value, event.currentTarget.selectionStart));
          dismiss();
        }}
        onBlur={() => window.setTimeout(dismiss, 150)}
        className={cx(
          "min-h-0 flex-1 resize-none bg-canvas p-3 font-mono text-[13px] leading-6 text-ink outline-none",
          "placeholder:text-muted disabled:opacity-50 disabled:saturate-0",
        )}
      />

      <div className="flex items-center justify-between border-t border-line px-3 py-1 text-[11px] tabular-nums text-muted">
        <span>
          Line {caret.line}, column {caret.column}
        </span>
        <span>{value.length.toLocaleString()} characters</span>
      </div>

      {suggestions.length > 0 ? (
        <ul
          role="listbox"
          aria-label="Suggestions"
          className="absolute bottom-10 left-3 z-20 max-h-64 w-80 overflow-y-auto rounded-xl border border-line bg-surface shadow-lg"
        >
          {suggestions.map((suggestion, index) => (
            <li key={`${suggestion.kind}:${suggestion.label}`}>
              <button
                type="button"
                role="option"
                aria-selected={index === active}
                onMouseDown={(event) => {
                  // mousedown, not click: blur would dismiss the list first.
                  event.preventDefault();
                  accept(suggestion);
                }}
                className={cx(
                  "flex w-full items-baseline gap-2 px-3 py-1.5 text-left text-xs transition",
                  index === active ? "bg-[color:var(--accent-faint)] text-ink" : "text-ink-2 hover:bg-sunken",
                )}
              >
                <span className="font-mono">
                  {word.text ? (
                    <>
                      <mark className="bg-transparent text-[color:var(--accent)]">
                        {suggestion.label.slice(0, word.text.length)}
                      </mark>
                      {suggestion.label.slice(word.text.length)}
                    </>
                  ) : (
                    suggestion.label
                  )}
                </span>
                <span className="ml-auto truncate text-[10px] text-muted">{suggestion.detail || suggestion.kind}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
