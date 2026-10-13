import { describe, expect, it } from "vitest";

import { describeParserMetadata } from "@/features/datasets/parser-metadata";

describe("describeParserMetadata", () => {
  const metadata = {
    format: "csv",
    container: null,
    row_count: 10,
    column_count: 3,
    findings: [
      {
        stage: "encoding",
        value: "utf-8",
        certainty: "certain",
        reason: "Every byte decodes as UTF-8.",
        needs_review: false,
        blocking: false,
      },
      {
        stage: "date_format",
        value: "DD/MM/YYYY",
        certainty: "likely",
        reason: "A day above 12 settles the order.",
        needs_review: true,
        blocking: false,
      },
    ],
    needs_review: ["date_format"],
    spec_supplied: false,
    delimiter: ",",
    quote_char: '"',
    encoding: "utf-8",
    skip_rows: 0,
    has_header: true,
  };

  it("never prints an object as [object Object]", () => {
    const { facts, notes } = describeParserMetadata(metadata);
    const text = JSON.stringify([facts, notes]);
    expect(text).not.toContain("[object Object]");
  });

  it("labels settings in plain words", () => {
    const { facts } = describeParserMetadata(metadata);
    expect(facts).toContainEqual({ label: "File format", value: "CSV" });
    expect(facts).toContainEqual({ label: "Column separator", value: "comma (,)" });
    expect(facts).toContainEqual({ label: "First row is headings", value: "Yes" });
  });

  it("leaves out empty, zero and repeated values", () => {
    const labels = describeParserMetadata(metadata).facts.map((fact) => fact.label);
    expect(labels).not.toContain("Packaged as");
    expect(labels).not.toContain("Lines skipped before the table");
    expect(labels).not.toContain("Saved import settings");
    expect(labels).not.toContain("Row count");
  });

  it("turns findings into sentences, the ones needing review first", () => {
    const { notes } = describeParserMetadata(metadata);
    expect(notes.map((note) => note.label)).toEqual(["Dates", "Text encoding"]);
    expect(notes[0]).toMatchObject({ needsReview: true, reason: "A day above 12 settles the order." });
  });

  it("copes with missing metadata", () => {
    expect(describeParserMetadata(null)).toEqual({ facts: [], notes: [] });
  });
});
