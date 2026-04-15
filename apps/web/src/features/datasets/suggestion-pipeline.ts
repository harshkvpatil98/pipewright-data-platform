import type {
  TransformationPipelineCreatePayload,
  TransformationSuggestion,
  TransformationStep,
} from "@platform/shared-types";

export function getDefaultSuggestionPipelineName(datasetName: string): string {
  const trimmed = datasetName.trim();
  return `${trimmed || "Dataset"} suggested cleanup`;
}

export function toggleSuggestionSelection(
  selectedIds: string[],
  suggestionId: string,
): string[] {
  return selectedIds.includes(suggestionId)
    ? selectedIds.filter((id) => id !== suggestionId)
    : [...selectedIds, suggestionId];
}

export function getSelectedSuggestionsInOrder(
  suggestions: TransformationSuggestion[],
  selectedIds: string[],
): TransformationSuggestion[] {
  const selectedSet = new Set(selectedIds);
  return suggestions.filter((suggestion) => selectedSet.has(suggestion.suggestion_id));
}

export function buildSuggestionPipelinePayload(args: {
  suggestions: TransformationSuggestion[];
  selectedIds: string[];
  pipelineName: string;
  description?: string;
}): TransformationPipelineCreatePayload {
  const name = args.pipelineName.trim();
  if (name.length < 2) {
    throw new Error("Pipeline name must be at least 2 characters.");
  }

  const selectedSuggestions = getSelectedSuggestionsInOrder(args.suggestions, args.selectedIds);
  if (selectedSuggestions.length === 0) {
    throw new Error("Select at least one suggestion to create a draft pipeline.");
  }

  const steps_json: TransformationStep[] = selectedSuggestions.map((suggestion) => ({
    step_type: suggestion.step_type as TransformationStep["step_type"],
    config: suggestion.config,
  }));

  return {
    name,
    description: args.description?.trim() ? args.description.trim() : null,
    status: "draft",
    steps_json,
  };
}
