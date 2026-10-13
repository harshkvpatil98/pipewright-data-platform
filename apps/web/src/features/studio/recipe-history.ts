/**
 * Undo and redo for the recipe being edited.
 *
 * Each change to the steps is recorded, except that changes in quick
 * succession to the same field fold into one: typing "amount" into a box is
 * one thing to undo, not six. A change with no `group` (adding, removing or
 * moving a step, a template, a YAML edit) always starts a new entry.
 */

export type History<T> = {
  past: T[];
  present: T;
  future: T[];
  /** The field the last change was to, while it may still be folded into. */
  group: string | null;
  at: number;
};

/** How long a pause in typing ends one undo step and starts the next. */
const FOLD_WINDOW_MS = 1000;
const LIMIT = 100;

export function startHistory<T>(present: T): History<T> {
  return { past: [], present, future: [], group: null, at: 0 };
}

export function record<T>(
  history: History<T>,
  next: T,
  options: { group?: string; now?: number } = {},
): History<T> {
  if (next === history.present) return history;
  const now = options.now ?? Date.now();
  const group = options.group ?? null;
  if (group !== null && group === history.group && now - history.at < FOLD_WINDOW_MS) {
    return { ...history, present: next, future: [], at: now };
  }
  return {
    past: [...history.past, history.present].slice(-LIMIT),
    present: next,
    future: [],
    group,
    at: now,
  };
}

export function undo<T>(history: History<T>): History<T> {
  if (history.past.length === 0) return history;
  const previous = history.past[history.past.length - 1];
  return {
    past: history.past.slice(0, -1),
    present: previous,
    future: [history.present, ...history.future],
    group: null,
    at: 0,
  };
}

export function redo<T>(history: History<T>): History<T> {
  if (history.future.length === 0) return history;
  const [next, ...rest] = history.future;
  return {
    past: [...history.past, history.present],
    present: next,
    future: rest,
    group: null,
    at: 0,
  };
}
