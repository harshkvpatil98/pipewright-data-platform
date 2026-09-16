import { describe, expect, it } from "vitest";

import { csvCell, exportName, toCsv } from "./result-export";

describe("csvCell", () => {
  it("leaves a plain value alone", () => {
    expect(csvCell("hello")).toBe("hello");
    expect(csvCell(42)).toBe("42");
  });

  it("writes null as an empty field, not the word null", () => {
    expect(csvCell(null)).toBe("");
    expect(csvCell(undefined)).toBe("");
  });

  it("quotes a value containing the delimiter", () => {
    expect(csvCell("a,b")).toBe('"a,b"');
  });

  it("doubles an embedded quote", () => {
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
  });

  it("quotes a value containing a newline", () => {
    expect(csvCell("a\nb")).toBe('"a\nb"');
  });

  it("renders an object as JSON rather than [object Object]", () => {
    expect(csvCell({ a: 1 })).toBe('"{""a"":1}"');
  });
});

describe("toCsv", () => {
  it("writes a header and one line per row", () => {
    expect(toCsv(["a", "b"], [{ a: 1, b: 2 }, { a: 3, b: 4 }])).toBe("a,b\n1,2\n3,4\n");
  });

  it("keeps column order and fills missing values", () => {
    expect(toCsv(["a", "b"], [{ b: 2 }])).toBe("a,b\n,2\n");
  });

  it("ends with a newline", () => {
    // Without one, the file appends to whatever reads it next.
    expect(toCsv(["a"], [])).toBe("a\n");
  });
});

describe("exportName", () => {
  it("turns a summary into a filename", () => {
    expect(exportName("SELECT * FROM orders", "csv")).toBe("select-from-orders.csv");
  });

  it("falls back when there is nothing usable", () => {
    expect(exportName("!!!", "csv")).toBe("result.csv");
  });

  it("does not run away with a long query", () => {
    expect(exportName("a".repeat(200), "csv").length).toBeLessThanOrEqual(64);
  });
});
