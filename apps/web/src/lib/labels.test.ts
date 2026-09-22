import { friendlyStepMessage, ruleTypeLabel, severityLabel, typeLabel } from "@/lib/labels";

describe("type labels", () => {
  it("maps every engine spelling a surface actually emits", () => {
    // The pairs the review saw on-screen, plus the canonical vocabulary.
    expect(typeLabel("float64")).toBe("Decimal number");
    expect(typeLabel("float")).toBe("Decimal number");
    expect(typeLabel("int")).toBe("Whole number");
    expect(typeLabel("int64")).toBe("Whole number");
    expect(typeLabel("string")).toBe("Text");
    expect(typeLabel("bool")).toBe("True / false");
    expect(typeLabel("date")).toBe("Date");
    expect(typeLabel("datetime")).toBe("Date & time");
    expect(typeLabel("decimal")).toBe("Decimal (exact)");
  });

  it("never shows an underscore or a bare engine token", () => {
    for (const raw of ["some_new_type", "UNKNOWN", "  int  "]) {
      const label = typeLabel(raw);
      expect(label).not.toMatch(/_/);
      expect(label[0]).toBe(label[0].toUpperCase());
    }
  });

  it("treats missing as Unknown rather than crashing a schema panel", () => {
    expect(typeLabel(null)).toBe("Unknown");
    expect(typeLabel(undefined)).toBe("Unknown");
  });
});

describe("rule and severity labels", () => {
  it("translates the built-in rule types", () => {
    expect(ruleTypeLabel("not_null")).toBe("Must have a value");
    expect(ruleTypeLabel("unique")).toBe("No duplicate values");
  });

  it("prettifies unknown rule types instead of leaking snake_case", () => {
    expect(ruleTypeLabel("future_rule_kind")).toBe("Future rule kind");
  });

  it("explains what a severity actually does", () => {
    expect(severityLabel("error")).toMatch(/quarantined/);
    expect(severityLabel("warn")).toMatch(/nothing is blocked/i);
  });
});

describe("friendly step messages", () => {
  it("translates the engine's exact validation strings", () => {
    expect(friendlyStepMessage("config.conditions must be a non-empty list.")).toBe(
      "Add at least one condition to keep rows.",
    );
    expect(friendlyStepMessage("config.aggregations must be a non-empty list.")).toMatch(
      /aggregation/,
    );
  });

  it("de-jargons unmapped config messages generically", () => {
    const out = friendlyStepMessage("config.widgets must be a non-empty list.");
    expect(out).not.toMatch(/config\./);
    expect(out).toMatch(/needs at least one entry/);
  });

  it("passes through messages it does not understand", () => {
    expect(friendlyStepMessage("Column 'x' does not exist.")).toBe(
      "Column 'x' does not exist.",
    );
  });
});
