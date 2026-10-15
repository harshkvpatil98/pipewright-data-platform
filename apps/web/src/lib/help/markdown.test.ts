import { describe, expect, it } from "vitest";

import { helpHref, parseInline, parseMarkdown, slugify, summarise } from "./markdown";

describe("help markdown", () => {
  it("reads headings, paragraphs, lists, quotes, code and tables", () => {
    const blocks = parseMarkdown(
      [
        "# Getting started",
        "",
        "Bring data in, then",
        "clean it.",
        "",
        "## Add data",
        "",
        "1. Open **Data**.",
        "2. Choose `Add data`.",
        "",
        "- one",
        "- two",
        "  continued",
        "",
        "> A tip.",
        "",
        "```bash",
        "curl /api/v1/health",
        "```",
        "",
        "| Word | Means |",
        "|---|---|",
        "| Recipe | Steps |",
      ].join("\n"),
    );
    expect(blocks.map((block) => block.kind)).toEqual(["heading", "paragraph", "heading", "list", "list", "quote", "code", "table"]);
    expect(blocks[1]).toEqual({ kind: "paragraph", content: [{ kind: "text", text: "Bring data in, then clean it." }] });
    expect(blocks[2]).toMatchObject({ kind: "heading", level: 2, id: "add-data" });
    expect(blocks[3]).toMatchObject({ kind: "list", ordered: true });
    expect(blocks[4]).toMatchObject({ kind: "list", ordered: false, items: [[{ text: "one" }], [{ text: "two continued" }]] });
    expect(blocks[6]).toEqual({ kind: "code", language: "bash", text: "curl /api/v1/health" });
    expect(blocks[7]).toMatchObject({ kind: "table", rows: [[[{ text: "Recipe" }], [{ text: "Steps" }]]] });
  });

  it("turns links to other help files into help pages", () => {
    expect(helpHref("data.md")).toBe("/help/data");
    expect(helpHref("./trust.md#checks")).toBe("/help/trust#checks");
    expect(helpHref("index.md")).toBe("/help");
    expect(helpHref("#checks")).toBe("#checks");
    expect(helpHref("https://example.com")).toBe("https://example.com");
    expect(parseInline("See [Data](data.md) and `x`.")).toEqual([
      { kind: "text", text: "See " },
      { kind: "link", text: "Data", href: "/help/data" },
      { kind: "text", text: " and " },
      { kind: "code", text: "x" },
      { kind: "text", text: "." },
    ]);
  });

  it("names a page by its first heading and paragraph", () => {
    expect(summarise(parseMarkdown("# Trust\n\nChecks and incidents.\n"))).toEqual({ title: "Trust", summary: "Checks and incidents." });
    expect(slugify("Add a check, then run it")).toBe("add-a-check-then-run-it");
  });
});

describe("pictures in the help (A9, Z2)", () => {
  it("reads a picture on a line of its own, and serves it from beside the help", () => {
    expect(parseMarkdown("![The overview, with its checklist](images/overview.png)")).toEqual([
      { kind: "image", alt: "The overview, with its checklist", src: "/help/images/overview.png" },
    ]);
    // Inside a sentence it is text, not a picture.
    expect(parseMarkdown("See ![this](images/overview.png) here")[0].kind).toBe("paragraph");
  });
});
