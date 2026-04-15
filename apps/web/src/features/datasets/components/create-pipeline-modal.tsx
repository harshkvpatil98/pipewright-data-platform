"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import type { TransformationPipelineCreatePayload, TransformationStep } from "@platform/shared-types";
import { Button, FormField, Input, Modal, Textarea } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";

type CreatePipelineModalProps = {
  open: boolean;
  onClose: () => void;
  projectId: string;
  datasetId: string;
};

function parseStepsJson(rawValue: string): TransformationStep[] {
  const parsed = JSON.parse(rawValue) as unknown;

  if (!Array.isArray(parsed)) {
    throw new Error("Steps JSON must be a JSON array.");
  }

  return parsed as TransformationStep[];
}

export function CreatePipelineModal({ open, onClose, projectId, datasetId }: CreatePipelineModalProps) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [stepsJsonText, setStepsJsonText] = useState(
    JSON.stringify(
      [
        {
          step_type: "rename_columns",
          config: {
            mappings: {
              old_name: "new_name",
            },
          },
        },
      ],
      null,
      2,
    ),
  );
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const isNameValid = useMemo(() => name.trim().length >= 2, [name]);

  const handleClose = () => {
    setName("");
    setDescription("");
    setStepsJsonText(
      JSON.stringify(
        [
          {
            step_type: "rename_columns",
            config: {
              mappings: {
                old_name: "new_name",
              },
            },
          },
        ],
        null,
        2,
      ),
    );
    setError(null);
    setSubmitting(false);
    onClose();
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (!isNameValid) {
      setError("Pipeline name must be at least 2 characters.");
      return;
    }

    let stepsJson: TransformationStep[];
    try {
      stepsJson = parseStepsJson(stepsJsonText);
    } catch (parseError) {
      setError(extractErrorMessage(parseError));
      return;
    }

    const payload: TransformationPipelineCreatePayload = {
      name: name.trim(),
      description: description.trim() || null,
      status: "draft",
      steps_json: stepsJson,
    };

    try {
      setSubmitting(true);
      await apiFetch(`/projects/${projectId}/datasets/${datasetId}/pipelines`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      handleClose();
      router.push(`/projects/${projectId}/datasets/${datasetId}`);
      router.refresh();
    } catch (submitError) {
      setError(extractErrorMessage(submitError));
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Create pipeline"
      description="Create a reusable transformation pipeline for this dataset using raw JSON steps."
      footer={
        <div className="flex items-center justify-end gap-3">
          <Button variant="secondary" onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
          <Button type="submit" form="create-pipeline-form" disabled={submitting || !isNameValid}>
            {submitting ? "Creating..." : "Create pipeline"}
          </Button>
        </div>
      }
    >
      <form id="create-pipeline-form" className="space-y-5" onSubmit={handleSubmit}>
        <FormField
          label="Pipeline name"
          htmlFor="pipeline-name"
          description="Use a clear name that describes the dataset preparation intent."
        >
          <Input
            id="pipeline-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Standardize customer exports"
            autoFocus
          />
        </FormField>

        <FormField
          label="Description"
          htmlFor="pipeline-description"
          description="Optional context for future editors of this pipeline."
        >
          <Textarea
            id="pipeline-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Normalize column names and prepare the dataset for downstream reporting."
          />
        </FormField>

        <FormField
          label="Steps JSON"
          htmlFor="pipeline-steps-json"
          description="Provide an ordered JSON array. Each step must include step_type and config."
        >
          <Textarea
            id="pipeline-steps-json"
            value={stepsJsonText}
            onChange={(event) => setStepsJsonText(event.target.value)}
            className="min-h-[260px] font-mono text-[13px]"
          />
        </FormField>

        {error ? (
          <div className="rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">
            {error}
          </div>
        ) : null}
      </form>
    </Modal>
  );
}
