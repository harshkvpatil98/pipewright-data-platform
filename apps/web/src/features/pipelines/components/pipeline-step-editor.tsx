"use client";

import { EmptyState, SectionPanel } from "@platform/shared-ui";

import {
  EditorStep,
  STEP_TYPE_OPTIONS,
  summarizeStep,
  validateEditorStep,
} from "@/features/pipelines/pipeline-editor-state";
import { StepFormRouter } from "@/features/pipelines/components/step-forms";

type PipelineStepEditorProps = {
  step: EditorStep | null;
  onChange: (step: EditorStep) => void;
};

export function PipelineStepEditor({ step, onChange }: PipelineStepEditorProps) {
  if (!step) {
    return (
      <SectionPanel title="Step configuration" description="Choose a step from the list to edit its structured configuration.">
        <EmptyState
          title="Select a step"
          description="The editor will show the selected step configuration here."
        />
      </SectionPanel>
    );
  }

  const { fields: fieldErrors } = validateEditorStep(step);

  return (
    <SectionPanel
      title={labelForStepType(step.step_type)}
      description={summarizeStep(step)}
    >
      <div className="space-y-5">
        <StepFormRouter step={step} onChange={onChange} fieldErrors={fieldErrors} />
      </div>
    </SectionPanel>
  );
}

function labelForStepType(stepType: EditorStep["step_type"]): string {
  return STEP_TYPE_OPTIONS.find((option) => option.value === stepType)?.label ?? stepType;
}
