import { describe, expect, it } from "vitest";

import {
  fitText,
  formatCell,
  isNumericType,
  typeGlyph,
} from "@/features/studio/grid/grid-theme";

describe("formatting cells", () => {
  it("shows null as a word, muted, rather than as blank", () => {
    // An empty string and a null are different facts. Rendering both as blank
    // hides the one that usually matters.
    const style = formatCell(null);
    expect(style.text).toBe("null");
    expect(style.muted).toBe(true);
  });

  it("keeps an empty string blank and unmuted", () => {
    expect(formatCell("")).toEqual({ text: "", align: "left", muted: false });
  });

  it("right-aligns numbers so digits line up", () => {
    expect(formatCell(42).align).toBe("right");
    expect(formatCell("42").align).toBe("left");
  });

  it("does not group integers", () => {
    // An order_id of 1001 must not read as "1,001". Identifiers are the
    // commonest integer column, and Excel does not group by default either.
    expect(formatCell(1001).text).toBe("1001");
    expect(formatCell(1234567).text).toBe("1234567");
  });

  it("keeps negative numbers intact", () => {
    expect(formatCell(-42).text).toBe("-42");
    expect(formatCell(-0.5).text).toBe("-0.5");
  });

  it("does not show floating-point noise", () => {
    // 0.30000000000000004 in a cell makes people distrust the whole table.
    expect(formatCell(0.1 + 0.2).text).toBe("0.3");
  });

  it("renders booleans as words", () => {
    expect(formatCell(true).text).toBe("true");
    expect(formatCell(false).text).toBe("false");
  });

  it("passes through infinities rather than formatting them", () => {
    expect(formatCell(Number.POSITIVE_INFINITY).text).toBe("Infinity");
  });
});

describe("fitting text", () => {
  // Stand-in for a canvas context: every character is 10 units wide.
  const context = {
    measureText: (text: string) => ({ width: text.length * 10 }),
  } as unknown as CanvasRenderingContext2D;

  it("leaves text that fits alone", () => {
    expect(fitText(context, "abc", 100)).toBe("abc");
  });

  it("truncates with an ellipsis", () => {
    const result = fitText(context, "abcdefghij", 50);
    expect(result.endsWith("…")).toBe(true);
    expect(result.length * 10).toBeLessThanOrEqual(50);
  });

  it("returns nothing when there is no room at all", () => {
    expect(fitText(context, "abc", 0)).toBe("");
    expect(fitText(context, "abcdef", 5)).toBe("");
  });

  it("fits exactly at the boundary", () => {
    expect(fitText(context, "abc", 30)).toBe("abc");
  });
});

describe("type glyphs", () => {
  it.each([
    ["int64", "123"],
    ["int", "123"],
    ["float64", "1.2"],
    ["string", "ABC"],
    ["string(80)", "ABC"],
    ["boolean", "T/F"],
    ["uuid", "ID"],
    ["mixed", "MIX"],
    ["unknown", "?"],
  ])("names %s", (type, expected) => {
    expect(typeGlyph(type)).toBe(expected);
  });

  it("marks a decimal as exact, distinct from a float", () => {
    // The distinction the type lattice exists to preserve; collapsing both to
    // "1.2" in the header throws it away at the last step.
    expect(typeGlyph("decimal(18,2)")).not.toBe(typeGlyph("float64"));
  });

  it("shows whether a timestamp carries a timezone", () => {
    expect(typeGlyph("timestamp(6,tz)")).toBe("CAL·TZ");
    expect(typeGlyph("timestamp(6,naive)")).toBe("CAL");
  });

  it("names nested types", () => {
    expect(typeGlyph("array<int64>")).toBe("{ }");
    expect(typeGlyph("struct<a:int64>")).toBe("{ }");
  });

  it("says nothing for an absent or unrecognised type", () => {
    expect(typeGlyph(undefined)).toBe("");
    expect(typeGlyph("quaternion")).toBe("");
  });
});

describe("numeric alignment", () => {
  it.each(["int64", "uint8", "float64", "decimal(18,2)", "double"])(
    "right-aligns %s",
    (type) => {
      expect(isNumericType(type)).toBe(true);
    }
  );

  it.each(["string", "boolean", "timestamp(6,tz)", "uuid", undefined])(
    "left-aligns %s",
    (type) => {
      expect(isNumericType(type)).toBe(false);
    }
  );
});

