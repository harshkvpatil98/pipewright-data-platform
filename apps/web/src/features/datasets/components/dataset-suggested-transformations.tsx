"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import type {
  TransformationPipelineRecord,
  TransformationSuggestion,
} from "@platform/shared-types";
import { Button, FormField, Input, SectionPanel, Textarea } from "@platform/shared-ui";

import { Modal } from "@/components/ui/modal";
import {
  buildSuggestionPipelinePayload,
  getDefaultSuggestionPipelineName,
  toggleSuggestionSelection,
} from "@/features/datasets/suggestion-pipeline";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";

type DatasetSuggestedTransformationsProps = {
  projectId: string;
  datasetId: string;
  datasetName: string;
  suggestions: TransformationSuggestion[];
};

function confidenceClass(confidence: TransformationSuggestion["confidence"]): string {
  if (confidence === "high") {
    return "border-success-line bg-success-soft text-success";
  }
  if (confidence === "medium") {
    return "border-warning-line bg-warning-soft text-warning";
  }
  return "border-line-strong bg-surface text-ink-2";
}

export function DatasetSuggestedTransformations({
  projectId,
  datasetId,
  datasetName,
  suggestions,
}: DatasetSuggestedTransformationsProps) {
  const router = useRouter();
  const [jsonModal, setJsonModal] = useState<TransformationSuggestion | null>(null);
  const [selectedSuggestionIds, setSelectedSuggestionIds] = useState<string[]>([]);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [pipelineName, setPipelineName] = useState(getDefaultSuggestionPipelineName(datasetName));
  const [description, setDescription] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const selectedCount = selectedSuggestionIds.length;

  useEffect(() => {
    if (!createModalOpen) {
      setPipelineName(getDefaultSuggestionPipelineName(datasetName));
      setDescription("");
      setCreateError(null);
      setCreating(false);
    }
  }, [createModalOpen, datasetName]);

  const selectedSuggestions = useMemo(
    () => suggestions.filter((suggestion) => selectedSuggestionIds.includes(suggestion.suggestion_id)),
    [selectedSuggestionIds, suggestions],
  );

  async function handleCreateDraftPipeline(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreateError(null);

    let payload;
    try {
      payload = buildSuggestionPipelinePayload({
        suggestions,
        selectedIds: selectedSuggestionIds,
        pipelineName,
        description,
      });
    } catch (error) {
      setCreateError(extractErrorMessage(error));
      return;
    }

    try {
      setCreating(true);
      const created = await apiFetch<TransformationPipelineRecord>(
        `/projects/${projectId}/datasets/${datasetId}/pipelines`,
        {
          method: "POST",
          body: JSON.stringify(payload),
        },
      );
      router.push(
        `/projects/${projectId}/datasets/${created.base_dataset_id}/pipelines/${created.id}`,
      );
      router.refresh();
    } catch (error) {
      setCreateError(extractErrorMessage(error));
      setCreating(false);
    }
  }

  if (suggestions.length === 0) {
    return (
      <SectionPanel
        title="Suggested transformations"
        description="Rule-based recommendations from your dataset profile and schema. None apply for this dataset yet."
      >
        <p className="text-sm text-ink-3">
          No suggestions right now. After ingestion profiles the columns, refresh this page to re-evaluate.
        </p>
      </SectionPanel>
    );
  }

  return (
    <>
      <SectionPanel
        title="Suggested transformations"
        description="Deterministic, explainable steps derived from schema, profile, and preview metadata. Suggestions are not applied automatically."
      >
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-line bg-sunken px-4 py-3">
          <div className="text-sm text-ink-2">
            <span className="font-medium text-ink">{selectedCount}</span> selected
            {selectedSuggestions.length > 0 ? (
              <span className="text-ink-3">
                {" "}
                · {selectedSuggestions.map((suggestion) => suggestion.step_type).join(", ")}
              </span>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {selectedCount > 0 ? (
              <Button
                variant="secondary"
                size="sm"
                type="button"
                onClick={() => setSelectedSuggestionIds([])}
              >
                Clear selection
              </Button>
            ) : null}
            <Button
              size="sm"
              type="button"
              disabled={selectedCount === 0}
              onClick={() => setCreateModalOpen(true)}
            >
              Create draft pipeline
            </Button>
          </div>
        </div>
        <div className="space-y-3">
          {suggestions.map((s) => {
            const isSelected = selectedSuggestionIds.includes(s.suggestion_id);
            return (
              <div
                key={s.suggestion_id}
                role="button"
                tabIndex={0}
                onClick={() =>
                  setSelectedSuggestionIds((current) =>
                    toggleSuggestionSelection(current, s.suggestion_id),
                  )
                }
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setSelectedSuggestionIds((current) =>
                      toggleSuggestionSelection(current, s.suggestion_id),
                    );
                  }
                }}
                className={[
                  "flex flex-col gap-3 rounded-2xl border p-4 transition md:flex-row md:items-start md:justify-between",
                  isSelected
                    ? "border-accent-line bg-accent-soft"
                    : "border-line bg-sunken hover:border-line-strong hover:bg-surface",
                ].join(" ")}
              >
                <div className="min-w-0 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={[
                        "inline-flex h-5 w-5 items-center justify-center rounded border text-[11px] font-semibold",
                        isSelected
                          ? "border-accent-line bg-accent-soft text-accent"
                          : "border-line-strong bg-transparent text-transparent",
                      ].join(" ")}
                    >
                      ✓
                    </span>
                    <span className="font-medium text-ink">{s.title}</span>
                    <span className="rounded-full border border-line px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide text-ink-3">
                      {s.step_type}
                    </span>
                    <span
                      className={`rounded-full border px-2 py-0.5 text-[11px] uppercase tracking-wide ${confidenceClass(s.confidence)}`}
                    >
                      {s.confidence} confidence
                    </span>
                  </div>
                  <p className="text-sm leading-6 text-ink-3">{s.explanation}</p>
                  <pre className="max-h-28 overflow-auto rounded-xl border border-line bg-sunken p-3 font-mono text-[11px] text-ink-2">
                    {JSON.stringify(s.config, null, 2)}
                  </pre>
                </div>
                <div className="flex shrink-0 flex-col gap-2 md:items-end">
                  <Button
                    variant={isSelected ? "secondary" : "ghost"}
                    size="sm"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      setSelectedSuggestionIds((current) =>
                        toggleSuggestionSelection(current, s.suggestion_id),
                      );
                    }}
                  >
                    {isSelected ? "Selected" : "Select"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      setJsonModal(s);
                    }}
                  >
                    View step JSON
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      </SectionPanel>

      <Modal
        open={createModalOpen}
        title="Create draft pipeline"
        description="Create a real draft pipeline from the selected suggested transformations. Nothing runs automatically."
        onClose={() => setCreateModalOpen(false)}
        footer={
          <div className="flex items-center justify-end gap-3">
            <Button
              variant="secondary"
              onClick={() => setCreateModalOpen(false)}
              disabled={creating}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              form="create-suggestion-pipeline-form"
              disabled={creating || selectedCount === 0 || pipelineName.trim().length < 2}
            >
              {creating ? "Creating..." : "Create draft pipeline"}
            </Button>
          </div>
        }
      >
        <form
          id="create-suggestion-pipeline-form"
          className="space-y-5"
          onSubmit={handleCreateDraftPipeline}
        >
          <FormField
            label="Pipeline name"
            htmlFor="suggestion-pipeline-name"
            description="This draft pipeline will be saved immediately, then opened in the editor."
          >
            <Input
              id="suggestion-pipeline-name"
              value={pipelineName}
              onChange={(event) => setPipelineName(event.target.value)}
              placeholder={getDefaultSuggestionPipelineName(datasetName)}
              autoFocus
            />
          </FormField>

          <FormField
            label="Description"
            htmlFor="suggestion-pipeline-description"
            description="Optional context about why these suggestions were selected."
          >
            <Textarea
              id="suggestion-pipeline-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Draft pipeline created from suggested cleanup steps."
            />
          </FormField>

          <div className="rounded-2xl border border-line bg-sunken px-4 py-4 text-sm text-ink-2">
            Creating a draft pipeline with <span className="font-medium text-ink">{selectedCount}</span>{" "}
            step{selectedCount === 1 ? "" : "s"}, in the same order shown above.
          </div>

          {createError ? (
            <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
              {createError}
            </div>
          ) : null}
        </form>
      </Modal>

      <Modal
        open={jsonModal !== null}
        title={jsonModal ? jsonModal.title : "Suggested step"}
        description="Review the exact pipeline step payload generated from this suggestion."
        onClose={() => setJsonModal(null)}
        footer={
          <Button variant="secondary" onClick={() => setJsonModal(null)}>
            Close
          </Button>
        }
      >
        {jsonModal ? (
          <pre className="max-h-[320px] overflow-auto rounded-xl border border-line bg-sunken p-3 font-mono text-[12px] leading-5 text-ink">
            {JSON.stringify({ step_type: jsonModal.step_type, config: jsonModal.config }, null, 2)}
          </pre>
        ) : null}
      </Modal>
    </>
  );
}
