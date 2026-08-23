import { describe, expect, it } from "vitest";

import {
  encodeField,
  fromTsv,
  pasteRepeats,
  pasteWrites,
  shapeOf,
  squareOff,
  toTsv,
} from "@/features/studio/grid/grid-clipboard";

describe("encoding fields", () => {
  it("leaves ordinary text alone", () => {
    expect(encodeField("hello")).toBe("hello");
  });

  it("renders null and undefined as empty, not as the word", () => {
    // "null" appearing in a spreadsheet cell is a bug people report.
    expect(encodeField(null)).toBe("");
    expect(encodeField(undefined)).toBe("");
  });

  it("keeps an empty string distinct from nothing at all", () => {
    expect(encodeField("")).toBe("");
  });

  it.each([
    ["a\tb", '"a\tb"'],
    ["a\nb", '"a\nb"'],
    ['say "hi"', '"say ""hi"""'],
  ])("quotes %j", (input, expected) => {
    expect(encodeField(input)).toBe(expected);
  });

  it("renders numbers and booleans plainly", () => {
    expect(encodeField(42)).toBe("42");
    expect(encodeField(true)).toBe("true");
  });
});

describe("writing TSV", () => {
  it("separates fields with tabs and rows with CRLF", () => {
    // CRLF because that is what Excel expects to read back.
    expect(toTsv([["a", "b"], ["c", "d"]])).toBe("a\tb\r\nc\td");
  });

  it("writes a single cell with no separators", () => {
    expect(toTsv([["only"]])).toBe("only");
  });
});

describe("reading TSV", () => {
  it("reads a simple rectangle", () => {
    expect(fromTsv("a\tb\r\nc\td")).toEqual([["a", "b"], ["c", "d"]]);
  });

  it("reads LF row breaks from Google Sheets", () => {
    expect(fromTsv("a\tb\nc\td")).toEqual([["a", "b"], ["c", "d"]]);
  });

  it("keeps a tab inside a quoted field", () => {
    // Splitting on tabs first would shear this row into two columns.
    expect(fromTsv('"a\tb"\tc')).toEqual([["a\tb", "c"]]);
  });

  it("keeps a newline inside a quoted field", () => {
    // And this one into two rows -- the classic address-column corruption.
    expect(fromTsv('"line one\nline two"\tnext')).toEqual([
      ["line one\nline two", "next"],
    ]);
  });

  it("unescapes doubled quotes", () => {
    expect(fromTsv('"say ""hi"""')).toEqual([['say "hi"']]);
  });

  it("keeps empty fields", () => {
    expect(fromTsv("a\t\tb")).toEqual([["a", "", "b"]]);
  });

  it("keeps a trailing empty field", () => {
    expect(fromTsv("a\tb\t")).toEqual([["a", "b", ""]]);
  });

  it("discards the phantom row a trailing newline produces", () => {
    expect(fromTsv("a\nb\n")).toEqual([["a"], ["b"]]);
  });

  it("keeps a genuinely blank row in the middle", () => {
    expect(fromTsv("a\n\nb")).toEqual([["a"], [""], ["b"]]);
  });

  it("reads empty text as a single empty cell", () => {
    expect(fromTsv("")).toEqual([[""]]);
  });

  it("treats a quote that is not at the start of a field as literal", () => {
    // Excel writes 5" as 5", unquoted, because the quote is not leading.
    expect(fromTsv('5" pipe')).toEqual([['5" pipe']]);
  });
});

describe("round trips", () => {
  const CORPUS: unknown[][][] = [
    [["a", "b"], ["c", "d"]],
    [["with\ttab", "plain"]],
    [["with\nnewline", "plain"]],
    [['quotes "inside"', "plain"]],
    [["", "", ""]],
    [["only"]],
    [[1, 2.5, -3]],
    [['"leading quote', 'trailing"']],
    [["a\r\nb", "c"]],
  ];

  it.each(CORPUS.map((rows, index) => [index, rows]))(
    "case %i survives a write and read",
    (_index, rows) => {
      const parsed = fromTsv(toTsv(rows as unknown[][]));
      const expected = (rows as unknown[][]).map((row) =>
        row.map((value) => (value === null || value === undefined ? "" : String(value)))
      );
      // \r\n inside a field normalises to \n, which is what a spreadsheet does.
      const normalise = (grid: string[][]) =>
        grid.map((row) => row.map((value) => value.replace(/\r\n/g, "\n")));
      expect(normalise(parsed)).toEqual(normalise(expected));
    }
  );
});

describe("shaping a paste", () => {
  it("pads short rows rather than refusing the paste", () => {
    expect(squareOff([["a", "b"], ["c"]])).toEqual([["a", "b"], ["c", ""]]);
  });

  it("reports the shape", () => {
    expect(shapeOf([["a", "b"], ["c", "d"], ["e", "f"]])).toEqual({ rows: 3, columns: 2 });
  });

  it("tiles a single cell across a larger selection", () => {
    // Copying one cell and selecting a column fills the column -- what every
    // spreadsheet does, and what people expect.
    expect(pasteRepeats({ rows: 1, columns: 1 }, { rows: 10, columns: 3 })).toEqual({
      down: 10,
      across: 3,
    });
  });

  it("tiles a block that divides the selection evenly", () => {
    expect(pasteRepeats({ rows: 2, columns: 2 }, { rows: 6, columns: 4 })).toEqual({
      down: 3,
      across: 2,
    });
  });

  it("pastes once when the shapes do not divide", () => {
    expect(pasteRepeats({ rows: 3, columns: 1 }, { rows: 7, columns: 1 })).toEqual({
      down: 1,
      across: 1,
    });
  });

  it("pastes once into a selection of the same size", () => {
    expect(pasteRepeats({ rows: 2, columns: 2 }, { rows: 2, columns: 2 })).toEqual({
      down: 1,
      across: 1,
    });
  });
});

describe("what a paste actually writes", () => {
  const bounds = { rows: 10, columns: 5 };
  const at = (row: number, column: number) => ({ row, column });

  it("writes a block from the origin", () => {
    const writes = pasteWrites(
      [["a", "b"], ["c", "d"]],
      at(1, 1),
      { rows: 2, columns: 2 },
      bounds
    );
    expect(writes).toEqual([
      { row: 1, column: 1, value: "a" },
      { row: 1, column: 2, value: "b" },
      { row: 2, column: 1, value: "c" },
      { row: 2, column: 2, value: "d" },
    ]);
  });

  it("tiles a single cell down a selected column", () => {
    const writes = pasteWrites([["x"]], at(0, 2), { rows: 4, columns: 1 }, bounds);
    expect(writes).toHaveLength(4);
    expect(writes.map((w) => w.row)).toEqual([0, 1, 2, 3]);
    expect(new Set(writes.map((w) => w.column))).toEqual(new Set([2]));
  });

  it("tiles a block across AND down to fill the selection", () => {
    // A 1x2 block filling a 2x4 selection is 8 cells, not 4: it repeats on both
    // axes, which is what every spreadsheet does.
    const writes = pasteWrites([["a", "b"]], at(0, 0), { rows: 2, columns: 4 }, bounds);
    expect(writes).toHaveLength(8);
    const filled = new Set(writes.map((w) => `${w.row}:${w.column}`));
    expect(filled.size).toBe(8);
    for (let row = 0; row < 2; row += 1) {
      for (let column = 0; column < 4; column += 1) {
        expect(filled.has(`${row}:${column}`)).toBe(true);
      }
    }
    // Alternating a,b across each row.
    expect(writes.filter((w) => w.row === 0 && w.column === 0)[0].value).toBe("a");
    expect(writes.filter((w) => w.row === 0 && w.column === 1)[0].value).toBe("b");
  });

  it("tiles across only when the selection is one row tall", () => {
    const writes = pasteWrites([["a", "b"]], at(0, 0), { rows: 1, columns: 4 }, bounds);
    expect(writes.map((w) => w.value)).toEqual(["a", "b", "a", "b"]);
  });

  it("clips at the bottom edge rather than wrapping", () => {
    // Wrapping would write a column of values into a completely different row,
    // which is both wrong and very hard to notice.
    const writes = pasteWrites(
      [["a"], ["b"], ["c"]],
      at(8, 0),
      { rows: 3, columns: 1 },
      bounds
    );
    expect(writes.map((w) => w.row)).toEqual([8, 9]);
  });

  it("clips at the right edge", () => {
    const writes = pasteWrites([["a", "b", "c"]], at(0, 3), { rows: 1, columns: 3 }, bounds);
    expect(writes.map((w) => w.column)).toEqual([3, 4]);
  });

  it("writes nothing for an empty clipboard", () => {
    expect(pasteWrites([], at(0, 0), { rows: 1, columns: 1 }, bounds)).toEqual([]);
  });

  it("pastes once when the shapes do not divide", () => {
    const writes = pasteWrites([["a"], ["b"], ["c"]], at(0, 0), { rows: 7, columns: 1 }, bounds);
    expect(writes).toHaveLength(3);
  });

  it("never writes the same cell twice", () => {
    // Overlapping repeats would make the last write silently win.
    const writes = pasteWrites([["a", "b"]], at(0, 0), { rows: 1, columns: 4 }, bounds);
    const seen = new Set(writes.map((w) => `${w.row}:${w.column}`));
    expect(seen.size).toBe(writes.length);
  });
});

