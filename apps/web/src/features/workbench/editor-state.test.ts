import { describe, expect, it } from "vitest";

import {
  applyCompletion,
  caretPosition,
  currentWord,
  describeRun,
  formatDuration,
  indent,
  sqlToRun,
  statementAt,
  toggleComment,
  type Statement,
} from "./editor-state";

function statement(overrides: Partial<Statement> & Pick<Statement, "index" | "sql">): Statement {
  return {
    summary: overrides.sql,
    kind: "read",
    line: 1,
    start: 0,
    end: overrides.sql.length,
    parameters: [],
    ...overrides,
  };
}

const SCRIPT = "SELECT 1;\nSELECT 2;\nSELECT 3";
const STATEMENTS: Statement[] = [
  statement({ index: 1, sql: "SELECT 1", start: 0, end: 8 }),
  statement({ index: 2, sql: "SELECT 2", start: 10, end: 18, line: 2 }),
  statement({ index: 3, sql: "SELECT 3", start: 20, end: 28, line: 3 }),
];

describe("statementAt", () => {
  it("finds the statement containing the cursor", () => {
    expect(statementAt(STATEMENTS, 3)?.index).toBe(1);
    expect(statementAt(STATEMENTS, 12)?.index).toBe(2);
  });

  it("treats a boundary as belonging to that statement", () => {
    expect(statementAt(STATEMENTS, 0)?.index).toBe(1);
    expect(statementAt(STATEMENTS, 8)?.index).toBe(1);
  });

  it("falls back to the last statement past the end", () => {
    // Typing after the final semicolon is still writing the last statement.
    expect(statementAt(STATEMENTS, 999)?.index).toBe(3);
  });

  it("is null when there is nothing", () => {
    expect(statementAt([], 0)).toBeNull();
  });
});

describe("sqlToRun", () => {
  it("prefers a selection over everything", () => {
    // Highlight three lines, press run, get those three lines.
    expect(sqlToRun(SCRIPT, { start: 10, end: 18 }, STATEMENTS, "script")).toBe("SELECT 2");
    expect(sqlToRun(SCRIPT, { start: 10, end: 18 }, STATEMENTS, "statement")).toBe("SELECT 2");
  });

  it("sends the whole script by default", () => {
    expect(sqlToRun(SCRIPT, { start: 3, end: 3 }, STATEMENTS, "script")).toBe(SCRIPT);
  });

  it("sends only the current statement when asked", () => {
    expect(sqlToRun(SCRIPT, { start: 12, end: 12 }, STATEMENTS, "statement")).toBe("SELECT 2");
  });

  it("falls back to the script when nothing parsed", () => {
    expect(sqlToRun(SCRIPT, { start: 0, end: 0 }, [], "statement")).toBe(SCRIPT);
  });
});

describe("caretPosition", () => {
  it("counts lines and columns from one", () => {
    expect(caretPosition("abc", 0)).toEqual({ line: 1, column: 1 });
    expect(caretPosition("abc", 3)).toEqual({ line: 1, column: 4 });
    expect(caretPosition("ab\ncd", 4)).toEqual({ line: 2, column: 2 });
  });

  it("clamps an offset past the end", () => {
    expect(caretPosition("abc", 99)).toEqual({ line: 1, column: 4 });
  });
});

describe("currentWord", () => {
  it("finds the partial word before the cursor", () => {
    expect(currentWord("SELECT cus", 10)).toEqual({ text: "cus", start: 7 });
  });

  it("is empty after a space", () => {
    expect(currentWord("SELECT ", 7)).toEqual({ text: "", start: 7 });
  });

  it("stops at a dot so a qualified name replaces only the tail", () => {
    expect(currentWord("SELECT o.reg", 12)).toEqual({ text: "reg", start: 9 });
  });
});

describe("applyCompletion", () => {
  it("replaces the partial word and moves the cursor", () => {
    const result = applyCompletion("SELECT cus", 10, "customers");
    expect(result.sql).toBe("SELECT customers");
    expect(result.offset).toBe(16);
  });

  it("inserts where there is no partial word", () => {
    expect(applyCompletion("SELECT ", 7, "id").sql).toBe("SELECT id");
  });

  it("keeps text after the cursor", () => {
    expect(applyCompletion("SELECT cus FROM t", 10, "customers").sql).toBe(
      "SELECT customers FROM t",
    );
  });

  it("replaces only the tail of a qualified name", () => {
    expect(applyCompletion("SELECT o.reg", 12, "region").sql).toBe("SELECT o.region");
  });
});

describe("indent", () => {
  it("inserts at the caret when there is no selection", () => {
    const result = indent("SELECT 1", { start: 0, end: 0 }, false);
    expect(result.sql).toBe("  SELECT 1");
    expect(result.selection).toEqual({ start: 2, end: 2 });
  });

  it("indents every line a selection touches", () => {
    // A Tab that replaced a multi-line selection with a tab character would
    // destroy the work.
    const result = indent("a\nb\nc", { start: 0, end: 3 }, false);
    expect(result.sql).toBe("  a\n  b\nc");
  });

  it("outdents only what is there", () => {
    const result = indent("  a\n b\nc", { start: 0, end: 8 }, true);
    expect(result.sql).toBe("a\nb\nc");
  });

  it("outdenting a line with no indentation leaves it alone", () => {
    expect(indent("a", { start: 0, end: 1 }, true).sql).toBe("a");
  });
});

describe("toggleComment", () => {
  it("comments a single line", () => {
    expect(toggleComment("SELECT 1", { start: 0, end: 0 }).sql).toBe("-- SELECT 1");
  });

  it("uncomments when every line is already commented", () => {
    expect(toggleComment("-- a\n-- b", { start: 0, end: 9 }).sql).toBe("a\nb");
  });

  it("comments the lot when only some are commented", () => {
    expect(toggleComment("-- a\nb", { start: 0, end: 6 }).sql).toBe("-- -- a\n-- b");
  });

  it("keeps indentation in front of the marker", () => {
    expect(toggleComment("  SELECT 1", { start: 0, end: 0 }).sql).toBe("  -- SELECT 1");
  });

  it("leaves blank lines alone", () => {
    expect(toggleComment("a\n\nb", { start: 0, end: 4 }).sql).toBe("-- a\n\n-- b");
  });
});

describe("formatDuration", () => {
  it("reads the way a person would say it", () => {
    expect(formatDuration(0.4)).toBe("<1 ms");
    expect(formatDuration(12)).toBe("12 ms");
    expect(formatDuration(1500)).toBe("1.50 s");
    expect(formatDuration(65_000)).toBe("1m 5s");
  });
});

describe("describeRun", () => {
  const run = (statements: unknown[], extra = {}) =>
    describeRun({
      statements: statements as never,
      duration_ms: 12,
      committed: true,
      ...extra,
    });

  it("summarises a read", () => {
    expect(run([{ row_count: 3, rows_affected: null, error: null, skipped: false }])).toBe(
      "1 statement · 3 rows · 12 ms",
    );
  });

  it("summarises a write", () => {
    expect(run([{ row_count: 0, rows_affected: 5, error: null, skipped: false }])).toBe(
      "1 statement · 5 changed · 12 ms",
    );
  });

  it("says when nothing was committed", () => {
    expect(
      run(
        [
          { row_count: 0, rows_affected: 1, error: null, skipped: false },
          { row_count: 0, rows_affected: null, error: "boom", skipped: false },
        ],
        { committed: false },
      ),
    ).toContain("rolled back");
  });

  it("does not count skipped statements as having run", () => {
    expect(
      run([
        { row_count: 1, rows_affected: null, error: null, skipped: false },
        { row_count: 0, rows_affected: null, error: null, skipped: true },
      ]),
    ).toContain("1 statement");
  });
});
