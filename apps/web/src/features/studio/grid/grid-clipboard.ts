/**
 * Clipboard interchange with real spreadsheets.
 *
 * Excel and Google Sheets put tab-separated text on the clipboard, with one
 * quoting convention: a field containing a tab, a newline or a quote is wrapped
 * in double quotes, and internal quotes are doubled. Get that wrong and pasting
 * a column of addresses silently shears rows apart.
 *
 * Excel writes CRLF between rows; Sheets writes LF. Both are read here, and
 * CRLF is written, because that is what Excel expects back.
 */

const NEEDS_QUOTING = /[\t\n\r"]/;

/** Render one field the way a spreadsheet would. */
export function encodeField(value: unknown): string {
  if (value === null || value === undefined) return "";
  const text = typeof value === "string" ? value : String(value);
  if (!NEEDS_QUOTING.test(text)) return text;
  return `"${text.replace(/"/g, '""')}"`;
}

/** Render a rectangle of values as clipboard TSV. */
export function toTsv(rows: readonly (readonly unknown[])[]): string {
  return rows.map((row) => row.map(encodeField).join("\t")).join("\r\n");
}

/**
 * Read clipboard TSV into a rectangle.
 *
 * Hand-parsed rather than split on tabs: a quoted field may contain both tabs
 * and newlines, and splitting first destroys exactly the data that needed the
 * quoting.
 */
export function fromTsv(text: string): string[][] {
  if (text === "") return [[""]];

  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  let index = 0;

  const endField = () => {
    row.push(field);
    field = "";
  };
  const endRow = () => {
    endField();
    rows.push(row);
    row = [];
  };

  while (index < text.length) {
    const char = text[index];

    if (quoted) {
      if (char === '"') {
        if (text[index + 1] === '"') {
          field += '"';
          index += 2;
          continue;
        }
        quoted = false;
        index += 1;
        continue;
      }
      field += char;
      index += 1;
      continue;
    }

    if (char === '"' && field === "") {
      quoted = true;
      index += 1;
      continue;
    }
    if (char === "\t") {
      endField();
      index += 1;
      continue;
    }
    if (char === "\r") {
      // Treat CRLF and a lone CR as one row break.
      if (text[index + 1] === "\n") index += 1;
      endRow();
      index += 1;
      continue;
    }
    if (char === "\n") {
      endRow();
      index += 1;
      continue;
    }

    field += char;
    index += 1;
  }

  endRow();

  // A trailing newline produces one empty row, which is an artefact of the
  // format rather than a row the user copied.
  if (rows.length > 1) {
    const last = rows[rows.length - 1];
    if (last.length === 1 && last[0] === "") rows.pop();
  }

  return rows;
}

/**
 * Square off a ragged paste.
 *
 * A paste from an irregular source can have rows of differing lengths; the grid
 * needs a rectangle. Short rows are padded rather than rejected, because
 * refusing the paste is worse than filling the gap with blanks.
 */
export function squareOff(rows: string[][]): string[][] {
  const width = rows.reduce((widest, row) => Math.max(widest, row.length), 0);
  return rows.map((row) =>
    row.length === width ? row : [...row, ...Array(width - row.length).fill("")]
  );
}

export type PasteShape = { rows: number; columns: number };

export function shapeOf(rows: readonly (readonly string[])[]): PasteShape {
  return { rows: rows.length, columns: rows[0]?.length ?? 0 };
}

/**
 * How a clipboard rectangle maps onto the target selection.
 *
 * Spreadsheets tile a small copy across a larger selection -- copying one cell
 * and selecting a column fills the column. Anything else pastes once from the
 * top-left, growing past the selection if the clipboard is bigger.
 */
export function pasteRepeats(
  clipboard: PasteShape,
  target: { rows: number; columns: number }
): { down: number; across: number } {
  const fitsDown = clipboard.rows > 0 && target.rows % clipboard.rows === 0;
  const fitsAcross = clipboard.columns > 0 && target.columns % clipboard.columns === 0;
  if (fitsDown && fitsAcross && (target.rows > clipboard.rows || target.columns > clipboard.columns)) {
    return { down: target.rows / clipboard.rows, across: target.columns / clipboard.columns };
  }
  return { down: 1, across: 1 };
}

export type PasteWrite = { row: number; column: number; value: string };

/**
 * Exactly which cells a paste writes, and what into each.
 *
 * Extracted from the component because this is where paste goes wrong: tiling
 * a block, clipping at the grid edge, and offsetting each repeat all interact,
 * and an off-by-one writes a column of values one row down from where the
 * person was looking. Pure, so it can be checked without a canvas.
 */
export function pasteWrites(
  block: readonly (readonly string[])[],
  origin: { row: number; column: number },
  target: { rows: number; columns: number },
  bounds: { rows: number; columns: number }
): PasteWrite[] {
  if (block.length === 0) return [];
  const repeat = pasteRepeats(shapeOf(block), target);
  const writes: PasteWrite[] = [];

  for (let down = 0; down < repeat.down; down += 1) {
    for (let across = 0; across < repeat.across; across += 1) {
      block.forEach((line, rowOffset) => {
        line.forEach((value, columnOffset) => {
          const row = origin.row + down * block.length + rowOffset;
          const column = origin.column + across * line.length + columnOffset;
          // Clipped, not wrapped: a paste that runs off the edge should stop,
          // not reappear at the start of the next row.
          if (row < bounds.rows && column < bounds.columns) {
            writes.push({ row, column, value });
          }
        });
      });
    }
  }
  return writes;
}

