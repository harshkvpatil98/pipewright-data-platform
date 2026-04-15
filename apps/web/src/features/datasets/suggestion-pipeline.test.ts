import type { TransformationSuggestion } from "@platform/shared-types";

import {
  buildSuggestionPipelinePayload,
  getDefaultSuggestionPipelineName,
  getSelectedSuggestionsInOrder,
  toggleSuggestionSelection,
} from "@/features/datasets/suggestion-pipeline";

const suggestions: TransformationSuggestion[] = [
  {
    suggestion_id: "s1",
    step_type: "trim_strings",
    title: "Trim",
    explanation: "Trim text columns.",
    confidence: "medium",
    config: { columns: ["name"] },
    source_signals: [],
    priority: 10,
  },
  {
    suggestion_id: "s2",
    step_type: "fill_nulls",
    title: "Fill",
    explanation: "Fill nulls.",
    confidence: "medium",
    config: { strategy: "mode", columns: ["status"] },
    source_signals: [],
    priority: 30,
  },
  {
    suggestion_id: "s3",
    step_type: "remove_duplicates",
    title: "Deduplicate",
    explanation: "Remove dupes.",
    confidence: "high",
    config: { keep: "first" },
    source_signals: [],
    priority: 40,
  },
];

describe("suggestion pipeline helpers", () => {
  it("builds a sensible default pipeline name", () => {
    expect(getDefaultSuggestionPipelineName("Customer orders")).toBe(
      "Customer orders suggested cleanup",
    );
  });

  it("toggles suggestion selection", () => {
    expect(toggleSuggestionSelection([], "s1")).toEqual(["s1"]);
    expect(toggleSuggestionSelection(["s1", "s2"], "s1")).toEqual(["s2"]);
  });

  it("preserves backend suggestion order, not click order", () => {
    expect(getSelectedSuggestionsInOrder(suggestions, ["s3", "s1"])).toEqual([
      suggestions[0],
      suggestions[2],
    ]);
  });

  it("builds a create-pipeline payload from selected suggestions", () => {
    expect(
      buildSuggestionPipelinePayload({
        suggestions,
        selectedIds: ["s3", "s1"],
        pipelineName: "  Suggested cleanup  ",
        description: "  Draft from suggestions  ",
      }),
    ).toEqual({
      name: "Suggested cleanup",
      description: "Draft from suggestions",
      status: "draft",
      steps_json: [
        { step_type: "trim_strings", config: { columns: ["name"] } },
        { step_type: "remove_duplicates", config: { keep: "first" } },
      ],
    });
  });

  it("prevents empty selection submission", () => {
    expect(() =>
      buildSuggestionPipelinePayload({
        suggestions,
        selectedIds: [],
        pipelineName: "Draft",
      }),
    ).toThrow("Select at least one suggestion");
  });
});
