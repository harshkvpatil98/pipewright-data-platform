/**
 * The parts of a SQL editor that are worth testing without a DOM.
 *
 * A code editor is mostly geometry and event handling, and the temptation is to
 * pull in a library for it. This one is deliberately a `<textarea>` with logic
 * around it: the platform already refuses chart and icon libraries, and a SQL
 * editor's genuinely hard parts — knowing which statement the cursor is in,
 * ranking completions, deciding what "run" means — are logic, not rendering.
 * Keeping them here means they are unit tested rather than clicked through.
 */

export type Statement = {
  index: number;
  sql: string;
  summary: string;
  kind: "read" | "write" | "ddl" | "session" | "unknown";
  line: number;
  start: number;
  end: number;
  parameters: string[];
};

/** The statement the cursor sits in, for "run this one". */
export function statementAt(statements: Statement[], offset: number): Statement | null {
  for (const statement of statements) {
    if (offset >= statement.start && offset <= statement.end) return statement;
  }
  // Past the last semicolon with only whitespace after it: the last statement
  // is still the one being written.
  return statements.length > 0 ? statements[statements.length - 1] : null;
}

/**
 * What "Run" should send.
 *
 * A selection wins over everything: highlighting three lines and pressing run
 * means those three lines, in every SQL tool anybody has used. Otherwise the
 * whole script, unless the caller asked for just the current statement.
 */
export function sqlToRun(
  sql: string,
  selection: { start: number; end: number },
  statements: Statement[],
  mode: "script" | "statement",
): string {
  if (selection.end > selection.start) {
    return sql.slice(selection.start, selection.end);
  }
  if (mode === "statement") {
    const current = statementAt(statements, selection.start);
    if (current) return current.sql;
  }
  return sql;
}

/** 1-based line and column, for the status bar. */
export function caretPosition(sql: string, offset: number): { line: number; column: number } {
  const head = sql.slice(0, Math.max(0, Math.min(offset, sql.length)));
  const lines = head.split("\n");
  return { line: lines.length, column: lines[lines.length - 1].length + 1 };
}

/** The word being typed, which is what a completion replaces. */
export function currentWord(sql: string, offset: number): { text: string; start: number } {
  const head = sql.slice(0, Math.max(0, Math.min(offset, sql.length)));
  const match = /[\w$]*$/.exec(head);
  const text = match ? match[0] : "";
  return { text, start: head.length - text.length };
}

/** Put a completion into the text, replacing the partial word. */
export function applyCompletion(
  sql: string,
  offset: number,
  insert: string,
): { sql: string; offset: number } {
  const word = currentWord(sql, offset);
  const next = sql.slice(0, word.start) + insert + sql.slice(offset);
  return { sql: next, offset: word.start + insert.length };
}

/**
 * Indent or outdent the lines a selection touches.
 *
 * Tab inside a textarea moves focus, which is correct for a form and wrong for
 * a code editor. Intercepting it means handling the block case too, because a
 * Tab that replaces a multi-line selection with a tab character destroys work.
 */
export function indent(
  sql: string,
  selection: { start: number; end: number },
  outdent: boolean,
  unit = "  ",
): { sql: string; selection: { start: number; end: number } } {
  const firstLineStart = sql.lastIndexOf("\n", Math.max(0, selection.start - 1)) + 1;
  const endOfSelection = sql.indexOf("\n", selection.end);
  const lastLineEnd = endOfSelection === -1 ? sql.length : endOfSelection;

  const block = sql.slice(firstLineStart, lastLineEnd);
  const singleLine = !block.includes("\n");

  if (singleLine && selection.start === selection.end && !outdent) {
    // A plain caret: insert the unit where it is.
    return {
      sql: sql.slice(0, selection.start) + unit + sql.slice(selection.start),
      selection: { start: selection.start + unit.length, end: selection.start + unit.length },
    };
  }

  const lines = block.split("\n");
  let removedFromFirst = 0;
  let removedTotal = 0;
  const shifted = lines.map((line, index) => {
    if (outdent) {
      const take = line.startsWith(unit) ? unit.length : line.startsWith(" ") ? 1 : 0;
      if (index === 0) removedFromFirst = take;
      removedTotal += take;
      return line.slice(take);
    }
    if (index === 0) removedFromFirst = -unit.length;
    removedTotal -= unit.length;
    return unit + line;
  });

  return {
    sql: sql.slice(0, firstLineStart) + shifted.join("\n") + sql.slice(lastLineEnd),
    selection: {
      start: Math.max(firstLineStart, selection.start - removedFromFirst),
      end: Math.max(firstLineStart, selection.end - removedTotal),
    },
  };
}

/** Comment or uncomment the selected lines, the way every editor's Cmd+/ does. */
export function toggleComment(
  sql: string,
  selection: { start: number; end: number },
): { sql: string; selection: { start: number; end: number } } {
  const firstLineStart = sql.lastIndexOf("\n", Math.max(0, selection.start - 1)) + 1;
  const endOfSelection = sql.indexOf("\n", selection.end);
  const lastLineEnd = endOfSelection === -1 ? sql.length : endOfSelection;
  const lines = sql.slice(firstLineStart, lastLineEnd).split("\n");

  const meaningful = lines.filter((line) => line.trim().length > 0);
  const allCommented =
    meaningful.length > 0 && meaningful.every((line) => line.trimStart().startsWith("-- "));

  const changed = lines.map((line) => {
    if (line.trim().length === 0) return line;
    if (allCommented) return line.replace(/^(\s*)-- /, "$1");
    return line.replace(/^(\s*)/, "$1-- ");
  });

  const next = sql.slice(0, firstLineStart) + changed.join("\n") + sql.slice(lastLineEnd);
  const delta = next.length - sql.length;
  return {
    sql: next,
    selection: { start: selection.start, end: Math.max(selection.start, selection.end + delta) },
  };
}

/** How a duration reads in a status bar. */
export function formatDuration(ms: number): string {
  if (ms < 1) return "<1 ms";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`;
  const minutes = Math.floor(ms / 60_000);
  return `${minutes}m ${Math.round((ms % 60_000) / 1000)}s`;
}

/** One line summarising a run, for the status bar. */
export function describeRun(result: {
  statements: { row_count: number; rows_affected: number | null; error: string | null; skipped: boolean }[];
  duration_ms: number;
  committed: boolean;
}): string {
  const ran = result.statements.filter((s) => !s.skipped);
  const failed = ran.filter((s) => s.error).length;
  const rows = ran.reduce((total, s) => total + s.row_count, 0);
  const affected = ran.reduce((total, s) => total + (s.rows_affected ?? 0), 0);

  const parts: string[] = [`${ran.length} statement${ran.length === 1 ? "" : "s"}`];
  if (rows) parts.push(`${rows.toLocaleString()} row${rows === 1 ? "" : "s"}`);
  if (affected) parts.push(`${affected.toLocaleString()} changed`);
  if (failed) parts.push(`${failed} failed`);
  if (failed && !result.committed) parts.push("rolled back");
  parts.push(formatDuration(result.duration_ms));
  return parts.join(" · ");
}
