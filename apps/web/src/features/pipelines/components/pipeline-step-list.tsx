"use client";

import { useState } from "react";

import { Button, EmptyState, Select } from "@platform/shared-ui";

import {
  EditorStep,
  STEP_TYPE_OPTIONS,
  getEditorStepError,
  summarizeStep,
} from "@/features/pipelines/pipeline-editor-state";

type PipelineStepListProps = {
  steps: EditorStep[];
  selectedStepId: string | null;
  onSelect: (stepId: string) => void;
  onAdd: (stepType: (typeof STEP_TYPE_OPTIONS)[number]["value"]) => void;
  onRemove: (stepId: string) => void;
  onMove: (stepId: string, direction: "up" | "down") => void;
};

export function PipelineStepList({
  steps,
  selectedStepId,
  onSelect,
  onAdd,
  onRemove,
  onMove,
}: PipelineStepListProps) {
  return (
    <div className="space-y-4">
      {steps.length === 0 ? (
        <EmptyState
          title="No steps yet"
          description="Add the first transformation step to start building this pipeline."
          action={<StepAddAction onAdd={onAdd} />}
        />
      ) : (
        <>
          <StepAddAction onAdd={onAdd} />
          <div className="space-y-3">
            {steps.map((step, index) => {
              const isSelected = step.id === selectedStepId;
              const stepError = getEditorStepError(step);
              return (
                <div
                  key={step.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => onSelect(step.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelect(step.id);
                    }
                  }}
                  className={[
                    "w-full rounded-2xl border px-4 py-4 text-left transition",
                    isSelected
                      ? "border-accent-line bg-accent-soft"
                      : stepError
                        ? "border-danger-line bg-danger-soft hover:bg-danger-soft"
                        : "border-line bg-sunken hover:bg-surface",
                  ].join(" ")}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-xs uppercase tracking-[0.18em] text-muted">
                        Step {index + 1}
                      </div>
                      <div className="mt-2 font-medium text-ink">{labelForStepType(step.step_type)}</div>
                      <div className="mt-1 text-sm text-ink-3">{summarizeStep(step)}</div>
                      {stepError ? (
                        <div className="mt-2 text-sm text-danger">{stepError}</div>
                      ) : null}
                    </div>
                    <div className="flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(event) => {
                          event.stopPropagation();
                          onMove(step.id, "up");
                        }}
                        disabled={index === 0}
                      >
                        Up
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(event) => {
                          event.stopPropagation();
                          onMove(step.id, "down");
                        }}
                        disabled={index === steps.length - 1}
                      >
                        Down
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(event) => {
                          event.stopPropagation();
                          onRemove(step.id);
                        }}
                      >
                        Remove
                      </Button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

function StepAddAction({
  onAdd,
}: {
  onAdd: (stepType: (typeof STEP_TYPE_OPTIONS)[number]["value"]) => void;
}) {
  const [stepType, setStepType] = useState<(typeof STEP_TYPE_OPTIONS)[number]["value"]>("rename_columns");

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-line bg-sunken p-3">
      <Select
        value={stepType}
        onChange={(event) => setStepType(event.target.value as (typeof STEP_TYPE_OPTIONS)[number]["value"])}
      >
        {STEP_TYPE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </Select>
      <Button variant="secondary" size="sm" onClick={() => onAdd(stepType)}>
        Add step
      </Button>
      <div className="text-xs text-muted">Steps run from top to bottom in this order.</div>
    </div>
  );
}

function labelForStepType(stepType: EditorStep["step_type"]): string {
  return STEP_TYPE_OPTIONS.find((option) => option.value === stepType)?.label ?? stepType;
}
