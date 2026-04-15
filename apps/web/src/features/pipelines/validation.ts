import type { TransformationStep } from "@platform/shared-types";

export function validatePipelineName(name: string): string | null {
  const normalized = name.trim();
  if (normalized.length < 2) {
    return "Pipeline name must be at least 2 characters.";
  }
  if (normalized.length > 160) {
    return "Pipeline name must be at most 160 characters.";
  }
  return null;
}

export function validatePipelineDraft(input: {
  name: string;
  baseDatasetId: string | null;
  steps: TransformationStep[];
}): string[] {
  const errors: string[] = [];
  const nameError = validatePipelineName(input.name);
  if (nameError) {
    errors.push(nameError);
  }
  if (!input.baseDatasetId) {
    errors.push("Choose a base dataset for this pipeline.");
  }
  if (input.steps.length === 0) {
    errors.push("Add at least one transformation step.");
  }
  return errors;
}
