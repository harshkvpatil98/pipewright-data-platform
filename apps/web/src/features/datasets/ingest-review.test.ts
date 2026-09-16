import {
  answerQuestion,
  blockingQuestions,
  columnOf,
  confidenceLabel,
  editColumn,
  reviewableFindings,
  specProblems,
  stageLabel,
} from "@/features/datasets/ingest-review";
import type {
  AnalyseUploadResponse,
  IngestFinding,
  IngestSpec,
} from "@platform/shared-types";

function finding(overrides: Partial<IngestFinding> = {}): IngestFinding {
  return {
    stage: "date_format",
    value: null,
    certainty: "ambiguous",
    confidence: 0.5,
    reason: "Column when: '03/04/2026' could be 3 April 2026 or 4 March 2026.",
    candidates: [
      { value: "%d/%m/%Y", score: 1, reason: "day first" },
      { value: "%m/%d/%Y", score: 1, reason: "month first" },
    ],
    evidence: ["03/04/2026"],
    needs_review: true,
    blocking: true,
    ...overrides,
  };
}

function spec(overrides: Partial<IngestSpec> = {}): IngestSpec {
  return {
    version: 1,
    format: "csv",
    container: "none",
    options: {},
    columns: [
      {
        name: "when",
        type: "string",
        date_format: null,
        decimal: null,
        thousands: null,
        null_tokens: [],
        rename: null,
        include: true,
      },
    ],
    derived_from: "x.csv",
    ...overrides,
  };
}

function analysis(overrides: Partial<AnalyseUploadResponse> = {}): AnalyseUploadResponse {
  return {
    file_name: "x.csv",
    file_size_bytes: 10,
    analysis: {
      container: "none",
      format: "csv",
      read_options: {},
      findings: [],
      columns: [],
      members: [],
      tables: [],
      warnings: [],
      blocked_by: [],
      needs_review: 0,
      row_count_sampled: 1,
    },
    spec: spec(),
    preview: { columns: [], dtypes: {}, rows: [] },
    conversion_notes: [],
    matched_spec: null,
    questions: [],
    ...overrides,
  };
}

describe("which findings the person is asked about", () => {
  it("separates blocking questions from things merely worth a glance", () => {
    const blocking = finding();
    const glance = finding({
      stage: "delimiter",
      certainty: "uncertain",
      blocking: false,
      reason: "Chosen by consistency.",
    });
    const result = analysis({
      questions: [blocking],
      analysis: { ...analysis().analysis, findings: [blocking, glance] },
    });

    expect(blockingQuestions(result)).toHaveLength(1);
    expect(reviewableFindings(result).map((item) => item.stage)).toEqual(["delimiter"]);
  });

  it("does not list a blocking stage twice", () => {
    const blocking = finding();
    const result = analysis({
      questions: [blocking],
      analysis: { ...analysis().analysis, findings: [blocking] },
    });
    expect(reviewableFindings(result)).toEqual([]);
  });

  it("falls back to the analysis when questions were not sent separately", () => {
    const blocking = finding();
    const result = analysis({
      analysis: { ...analysis().analysis, blocked_by: [blocking] },
    });
    expect(blockingQuestions(result)).toHaveLength(1);
  });
});

describe("answering a question edits the spec", () => {
  it("records the chosen date format and types the column", () => {
    const answered = answerQuestion(spec(), finding(), "%d/%m/%Y");
    expect(answered.columns[0].date_format).toBe("%d/%m/%Y");
    expect(answered.columns[0].type).toBe("date");
  });

  it("chooses timestamp when the format carries a time", () => {
    const answered = answerQuestion(spec(), finding(), "%Y-%m-%d %H:%M:%S");
    expect(answered.columns[0].type).toBe("timestamp(naive)");
  });

  it("sets both separators when the decimal point is chosen", () => {
    const answered = answerQuestion(
      spec(),
      finding({ stage: "number_format", reason: "Column when: '1.234' could be either." }),
      ",",
    );
    expect(answered.columns[0].decimal).toBe(",");
    expect(answered.columns[0].thousands).toBe(".");
  });

  it("leaves the spec alone when the finding names no column", () => {
    const orphan = finding({ reason: "No column named here." });
    expect(answerQuestion(spec(), orphan, "%d/%m/%Y")).toEqual(spec());
  });
});

describe("what stops an import", () => {
  it("refuses a date column with no format", () => {
    const withDate = editColumn(spec(), "when", { type: "date" });
    expect(specProblems(withDate)).toEqual([
      "when is a date but no format has been chosen.",
    ]);
  });

  it("accepts a date column once the format is set", () => {
    const answered = answerQuestion(spec(), finding(), "%d/%m/%Y");
    expect(specProblems(answered)).toEqual([]);
  });

  it("refuses two columns renamed to the same thing", () => {
    const clashing = spec({
      columns: [
        { ...spec().columns[0], name: "a", rename: "total" },
        { ...spec().columns[0], name: "b", rename: "total" },
      ],
    });
    expect(specProblems(clashing)[0]).toContain('all be called "total"');
  });

  it("refuses excluding every column", () => {
    const empty = editColumn(spec(), "when", { include: false });
    expect(specProblems(empty)).toContain(
      "Every column is excluded, so there would be nothing to import.",
    );
  });

  it("ignores an excluded column's problems", () => {
    const excluded = editColumn(
      spec({
        columns: [
          { ...spec().columns[0], name: "keep", type: "string" },
          { ...spec().columns[0], name: "when", type: "date" },
        ],
      }),
      "when",
      { include: false },
    );
    expect(specProblems(excluded)).toEqual([]);
  });
});

describe("reading a finding", () => {
  it("finds the column a question is about", () => {
    expect(columnOf(finding())).toBe("when");
    expect(columnOf(finding({ reason: "No column here." }))).toBeNull();
  });

  it("says 'certain' rather than '100% sure'", () => {
    expect(confidenceLabel(finding({ certainty: "certain", confidence: 1 }))).toBe("certain");
    expect(confidenceLabel(finding({ certainty: "likely", confidence: 0.87 }))).toBe(
      "87% sure",
    );
  });

  it("turns a stage name into words", () => {
    expect(stageLabel("header_row")).toBe("Header row");
    expect(stageLabel("something_new")).toBe("something new");
  });
});
