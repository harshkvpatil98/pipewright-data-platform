import { describe, expect, it } from "vitest";

import {
  addInsert,
  coerceValue,
  describe as describeTray,
  discardCell,
  discardRow,
  emptyTray,
  isEmpty,
  keyOf,
  overlayRows,
  rowId,
  sameValue,
  stageCell,
  stageColumn,
  stageDelete,
  stageInsertCell,
  toPayload,
  trayCount,
  type Tray,
} from "./change-tray";

const key = (id: number) => ({ id });

function edited(tray: Tray, column: string, value: unknown, original: unknown, id = 1) {
  return stageCell(tray, {
    key: key(id),
    column,
    value: value as never,
    original: original as never,
    hasOriginal: true,
  });
}

describe("rowId", () => {
  it("does not depend on key order", () => {
    expect(rowId({ a: 1, b: "x" })).toBe(rowId({ b: "x", a: 1 }));
  });

  it("separates rows whose keys differ only by type", () => {
    // 1 and "1" address different rows on a database that distinguishes them.
    expect(rowId({ id: 1 })).not.toBe(rowId({ id: "1" }));
  });

  it("reads only the key columns from a row", () => {
    expect(keyOf({ id: 3, region: "eu" }, ["id"])).toEqual({ id: 3 });
  });
});

describe("coerceValue", () => {
  it("sends a number to a numeric column", () => {
    expect(coerceValue("10", "INTEGER")).toBe(10);
    expect(coerceValue("10.5", "numeric(10,2)")).toBe(10.5);
    expect(coerceValue("1,200", "bigint")).toBe(1200);
  });

  it("leaves an unparseable numeric alone so the database can refuse it", () => {
    // Silently turning "abc" into 0 would write a wrong number confidently.
    expect(coerceValue("abc", "INTEGER")).toBe("abc");
  });

  it("reads the words people actually type for booleans", () => {
    expect(coerceValue("yes", "boolean")).toBe(true);
    expect(coerceValue("FALSE", "boolean")).toBe(false);
  });

  it("treats an emptied cell as null", () => {
    expect(coerceValue("", "text")).toBeNull();
    expect(coerceValue("   ", "integer")).toBeNull();
  });

  it("keeps text exactly, including its spaces", () => {
    expect(coerceValue("  hello ", "text")).toBe("  hello ");
  });
});

describe("sameValue", () => {
  it("compares across the string/number divide", () => {
    expect(sameValue(10, "10")).toBe(true);
    expect(sameValue(10.0, "10.00")).toBe(true);
  });

  it("does not treat null as empty string", () => {
    expect(sameValue(null, "")).toBe(false);
    expect(sameValue(null, null)).toBe(true);
  });
});

describe("stageCell", () => {
  it("stages one edit", () => {
    const tray = edited(emptyTray(), "region", "emea", "eu");
    expect(tray.cells).toHaveLength(1);
    expect(tray.cells[0].value).toBe("emea");
    expect(tray.cells[0].previous).toBe("eu");
  });

  it("keeps the database's value as `previous` across repeated edits", () => {
    // This is what the server compares against to spot a concurrent change.
    // Overwriting it with the intermediate value would disable that check.
    let tray = edited(emptyTray(), "region", "emea", "eu");
    tray = edited(tray, "region", "apac", "emea");
    expect(tray.cells).toHaveLength(1);
    expect(tray.cells[0].value).toBe("apac");
    expect(tray.cells[0].previous).toBe("eu");
  });

  it("drops the edit when a cell is typed back to its stored value", () => {
    let tray = edited(emptyTray(), "region", "emea", "eu");
    tray = edited(tray, "region", "eu", "emea");
    expect(isEmpty(tray)).toBe(true);
  });

  it("keeps edits to different columns of one row apart", () => {
    let tray = edited(emptyTray(), "region", "emea", "eu");
    tray = edited(tray, "amount", 5, 1);
    expect(tray.cells).toHaveLength(2);
  });

  it("ignores edits to a row already staged for deletion", () => {
    let tray = stageDelete(emptyTray(), key(1));
    tray = edited(tray, "region", "emea", "eu");
    expect(tray.cells).toHaveLength(0);
    expect(tray.deletes).toHaveLength(1);
  });

  it("stages an edit with no known previous value without claiming one", () => {
    const tray = stageCell(emptyTray(), {
      key: key(1),
      column: "region",
      value: "emea",
      original: null,
      hasOriginal: false,
    });
    expect(tray.cells[0].hasPrevious).toBe(false);
    expect(toPayload(tray)[0]).not.toHaveProperty("has_previous");
  });
});

describe("stageDelete", () => {
  it("discards pending edits to the row it removes", () => {
    let tray = edited(emptyTray(), "region", "emea", "eu");
    tray = stageDelete(tray, key(1));
    expect(tray.cells).toHaveLength(0);
    expect(tray.deletes).toHaveLength(1);
  });

  it("is idempotent", () => {
    let tray = stageDelete(emptyTray(), key(1));
    tray = stageDelete(tray, key(1));
    expect(tray.deletes).toHaveLength(1);
  });
});

describe("inserts", () => {
  it("collects values into the pending row rather than into an update", () => {
    let tray = addInsert(emptyTray());
    const id = tray.inserts[0].rowId;
    tray = stageInsertCell(tray, id, "region", "apac");
    tray = stageInsertCell(tray, id, "amount", 5);
    expect(tray.cells).toHaveLength(0);
    expect(tray.inserts[0].values).toEqual({ region: "apac", amount: 5 });
  });

  it("can be abandoned before it is sent", () => {
    let tray = addInsert(emptyTray());
    tray = discardRow(tray, tray.inserts[0].rowId);
    expect(isEmpty(tray)).toBe(true);
  });
});

describe("discarding", () => {
  it("removes one cell without touching the rest of the row", () => {
    let tray = edited(emptyTray(), "region", "emea", "eu");
    tray = edited(tray, "amount", 5, 1);
    tray = discardCell(tray, rowId(key(1)), "region");
    expect(tray.cells.map((cell) => cell.column)).toEqual(["amount"]);
  });

  it("removes a whole row's edits and its deletion together", () => {
    let tray = edited(emptyTray(), "region", "emea", "eu");
    tray = stageDelete(tray, key(2));
    tray = discardRow(tray, rowId(key(2)));
    expect(tray.deletes).toHaveLength(0);
    expect(tray.cells).toHaveLength(1);
  });
});

describe("overlayRows", () => {
  const rows = [
    { id: 1, region: "eu", amount: 10 },
    { id: 2, region: "us", amount: 20 },
  ];

  it("paints pending values over the loaded ones", () => {
    const tray = edited(emptyTray(), "region", "emea", "eu");
    const painted = overlayRows(rows, ["id"], tray);
    expect(painted[0].row.region).toBe("emea");
    expect(painted[0].state).toBe("edited");
    expect(painted[1].state).toBe("clean");
  });

  it("never mutates what was loaded", () => {
    const tray = edited(emptyTray(), "region", "emea", "eu");
    overlayRows(rows, ["id"], tray);
    expect(rows[0].region).toBe("eu");
  });

  it("marks deleted rows instead of hiding them", () => {
    // A row that vanishes on click gives no way to undo the click.
    const tray = stageDelete(emptyTray(), key(2));
    const painted = overlayRows(rows, ["id"], tray);
    expect(painted).toHaveLength(2);
    expect(painted[1].state).toBe("deleted");
  });

  it("appends new rows after the loaded ones", () => {
    const tray = addInsert(emptyTray(), { region: "apac" });
    const painted = overlayRows(rows, ["id"], tray);
    expect(painted).toHaveLength(3);
    expect(painted[2].state).toBe("new");
  });
});

describe("toPayload", () => {
  it("puts structure changes before the rows that depend on them", () => {
    let tray = stageColumn(emptyTray(), { kind: "add_column", column: "note", columnType: "text" });
    tray = edited(tray, "note", "hi", null);
    const payload = toPayload(tray);
    expect(payload[0].kind).toBe("add_column");
    expect(payload[1].kind).toBe("set_cell");
  });

  it("sends previous only when it was actually read", () => {
    const tray = edited(emptyTray(), "region", "emea", "eu");
    expect(toPayload(tray)[0]).toMatchObject({
      kind: "set_cell",
      previous: "eu",
      has_previous: true,
    });
  });

  it("sends an explicit null previous, which is a claim of its own", () => {
    const tray = edited(emptyTray(), "region", "emea", null);
    expect(toPayload(tray)[0]).toMatchObject({ previous: null, has_previous: true });
  });
});

describe("describe", () => {
  it("says what each staged change will do", () => {
    let tray = edited(emptyTray(), "region", "emea", "eu");
    tray = stageDelete(tray, key(2));
    tray = stageColumn(tray, { kind: "add_column", column: "note", columnType: "text" });
    const lines = describeTray(tray).map((line) => line.text);
    expect(lines).toContain("Add column note (text)");
    expect(lines).toContain("id 1 · region: eu → emea");
    expect(lines).toContain("Delete id 2");
  });

  it("names an emptied cell as empty rather than showing nothing", () => {
    const tray = edited(emptyTray(), "region", null, "eu");
    expect(describeTray(tray)[0].text).toBe("id 1 · region: eu → empty");
  });
});

describe("trayCount", () => {
  it("counts every kind of staged change", () => {
    let tray = edited(emptyTray(), "region", "emea", "eu");
    tray = stageDelete(tray, key(2));
    tray = addInsert(tray);
    tray = stageColumn(tray, { kind: "drop_column", column: "amount" });
    expect(trayCount(tray)).toBe(4);
  });
});
