"use client";

import Link from "next/link";
import { useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import type {
  AuthUser,
  DatasetRecord,
  ProjectDetail,
  TransformationPreviewResponse,
  TransformationPipelineRecord,
  TransformationRunResponse,
  TransformationStep,
} from "@platform/shared-types";
import { Button, FormField, Input, SectionPanel, Select, StatusBadge, Textarea } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { PipelinePreviewPanel } from "@/features/pipelines/components/pipeline-preview-panel";
import { PipelineStepEditor } from "@/features/pipelines/components/pipeline-step-editor";
import { PipelineStepList } from "@/features/pipelines/components/pipeline-step-list";
import { useUnsavedChangesGuard } from "@/features/navigation/unsaved-changes-guard";
import { getPipelineEditorUnsavedChangesGuard } from "@/features/pipelines/pipeline-editor-guard";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import {
  buildPipelineDraftPayload,
  createDefaultStep,
  EditorStep,
  isPipelineDraftValid,
  serializePipelineEditorBaseline,
  STEP_TYPE_OPTIONS,
  toApiSteps,
  toEditorSteps,
  validatePipelineName,
} from "@/features/pipelines/pipeline-editor-state";

type PipelineEditorPageViewProps = {
  currentUser: AuthUser;
  project: ProjectDetail;
  datasets: DatasetRecord[];
  pipeline: TransformationPipelineRecord | null;
  initialDatasetId: string | null;
  /** When creating a pipeline, optional steps from the suggestion engine (e.g. query param). */
  initialStarterSteps?: TransformationStep[] | null;
};

function resolveInitialEditorSteps(
  pipeline: TransformationPipelineRecord | null,
  initialStarterSteps: TransformationStep[] | null | undefined,
): EditorStep[] {
  if (pipeline?.steps_json?.length) {
    return toEditorSteps(pipeline.steps_json);
  }
  if (initialStarterSteps?.length) {
    return toEditorSteps(initialStarterSteps);
  }
  return [];
}

export function PipelineEditorPageView({
  currentUser,
  project,
  datasets,
  pipeline,
  initialDatasetId,
  initialStarterSteps = null,
}: PipelineEditorPageViewProps) {
  const router = useRouter();
  const initialEditorStepsRef = useRef<EditorStep[]>(resolveInitialEditorSteps(pipeline, initialStarterSteps));
  const initialSnapshotRef = useRef(
    serializePipelineEditorBaseline({
      name: pipeline?.name ?? "",
      description: pipeline?.description ?? "",
      status: pipeline?.status ?? "draft",
      baseDatasetId: pipeline?.base_dataset_id ?? initialDatasetId,
      steps: initialEditorStepsRef.current,
    }),
  );
  const [name, setName] = useState(pipeline?.name ?? "");
  const [description, setDescription] = useState(pipeline?.description ?? "");
  const [status, setStatus] = useState<"draft" | "active">(pipeline?.status ?? "draft");
  const [baseDatasetId, setBaseDatasetId] = useState<string | null>(pipeline?.base_dataset_id ?? initialDatasetId);
  const [steps, setSteps] = useState<EditorStep[]>(initialEditorStepsRef.current);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(
    initialEditorStepsRef.current[0]?.id ?? null,
  );
  const [saving, setSaving] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [runLoading, setRunLoading] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [preview, setPreview] = useState<TransformationPreviewResponse | null>(null);

  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === baseDatasetId) ?? null,
    [datasets, baseDatasetId],
  );
  const selectedStep = useMemo(
    () => steps.find((step) => step.id === selectedStepId) ?? null,
    [steps, selectedStepId],
  );
  const nameError = useMemo(() => validatePipelineName(name), [name]);
  const draftValid = useMemo(() => isPipelineDraftValid({ name, steps }), [name, steps]);

  const currentSnapshot = serializePipelineEditorBaseline({
    name,
    description,
    status,
    baseDatasetId,
    steps,
  });
  const hasUnsavedChanges = currentSnapshot !== initialSnapshotRef.current;
  useUnsavedChangesGuard(getPipelineEditorUnsavedChangesGuard(hasUnsavedChanges));
  const editorHref = pipeline && baseDatasetId ? `/projects/${project.id}/datasets/${baseDatasetId}/pipelines/${pipeline.id}` : null;

  const saveDisabled =
    saving || previewLoading || !hasUnsavedChanges || !draftValid || !baseDatasetId;
  const previewDisabled = previewLoading || saving || !baseDatasetId || !draftValid;

  const actionLinks = (
    <>
      <Link
        href={baseDatasetId ? `/projects/${project.id}/datasets/${baseDatasetId}` : `/projects/${project.id}/pipelines`}
        className="inline-flex h-11 items-center justify-center rounded-xl border border-line bg-surface-2 px-4 text-sm font-medium text-ink transition hover:border-line-strong hover:bg-surface-2"
      >
        {baseDatasetId ? "Back to dataset" : "Back to pipelines"}
      </Link>
      {pipeline ? (
        <Link
          href={`/projects/${project.id}/schedules?new=1&type=transformation_pipeline_run&pipelineId=${pipeline.id}`}
          className="inline-flex h-11 items-center justify-center rounded-xl border border-line bg-surface-2 px-4 text-sm font-medium text-ink transition hover:border-line-strong hover:bg-surface-2"
        >
          Schedule
        </Link>
      ) : null}
      <Button variant="secondary" onClick={handlePreview} disabled={previewDisabled}>
        {previewLoading ? "Previewing..." : "Preview"}
      </Button>
      <Button variant="secondary" onClick={handleSave} disabled={saveDisabled}>
        {saving ? "Saving..." : "Save"}
      </Button>
      <Button
        onClick={handleRun}
        disabled={!pipeline || hasUnsavedChanges || runLoading || saving || previewLoading}
      >
        {runLoading ? "Running..." : "Run"}
      </Button>
    </>
  );

  async function handleSave() {
    const pipelineNameMessage = validatePipelineName(name);
    if (pipelineNameMessage) {
      setFormError(pipelineNameMessage);
      return;
    }
    if (!baseDatasetId) {
      setFormError("Choose a base dataset for this pipeline.");
      return;
    }

    if (!isPipelineDraftValid({ name, steps })) {
      setFormError("Fix validation errors in the pipeline details and steps before saving.");
      return;
    }

    try {
      setSaving(true);
      setFormError(null);
      setSuccessMessage(null);
      const payload = buildPipelineDraftPayload({
        name,
        description,
        status,
        steps,
      });

      if (pipeline) {
        const updated = await apiFetch<TransformationPipelineRecord>(`/projects/${project.id}/pipelines/${pipeline.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        setSuccessMessage("Pipeline saved successfully.");
        router.replace(`/projects/${project.id}/datasets/${updated.base_dataset_id}/pipelines/${updated.id}`);
      } else {
        const created = await apiFetch<TransformationPipelineRecord>(
          `/projects/${project.id}/datasets/${baseDatasetId}/pipelines`,
          {
            method: "POST",
            body: JSON.stringify(payload),
          },
        );
        setSuccessMessage("Pipeline created successfully.");
        router.replace(`/projects/${project.id}/datasets/${created.base_dataset_id}/pipelines/${created.id}`);
      }

      router.refresh();
    } catch (error) {
      setFormError(extractErrorMessage(error));
    } finally {
      setSaving(false);
    }
  }

  async function handlePreview() {
    if (!baseDatasetId) {
      setPreviewError("Choose a base dataset before previewing.");
      return;
    }
    const pipelineNameMessage = validatePipelineName(name);
    if (pipelineNameMessage) {
      setPreviewError(pipelineNameMessage);
      return;
    }
    if (!isPipelineDraftValid({ name, steps })) {
      setPreviewError("Fix validation errors before previewing.");
      return;
    }

    try {
      setPreviewLoading(true);
      setPreviewError(null);
      setPreview(
        await apiFetch<TransformationPreviewResponse>(
          `/projects/${project.id}/datasets/${baseDatasetId}/pipelines/preview`,
          {
            method: "POST",
            body: JSON.stringify({ steps: toApiSteps(steps) }),
          },
        ),
      );
    } catch (error) {
      setPreviewError(extractErrorMessage(error));
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleRun() {
    if (!pipeline) {
      setFormError("Save the pipeline before running it.");
      return;
    }
    if (hasUnsavedChanges) {
      setFormError("Save changes before running the pipeline so execution matches the editor.");
      return;
    }

    try {
      setRunLoading(true);
      setFormError(null);
      setSuccessMessage(null);
      const result = await apiFetch<TransformationRunResponse>(
        `/projects/${project.id}/pipelines/${pipeline.id}/run`,
        {
          method: "POST",
        },
      );
      setSuccessMessage("Pipeline run succeeded. Opening the derived dataset...");
      router.push(`/projects/${project.id}/datasets/${result.dataset.id}`);
      router.refresh();
    } catch (error) {
      setFormError(extractErrorMessage(error));
    } finally {
      setRunLoading(false);
    }
  }

  function handleAddStep(stepType: (typeof STEP_TYPE_OPTIONS)[number]["value"]) {
    const nextStep = createDefaultStep(stepType);
    setSteps((current) => [...current, nextStep]);
    setSelectedStepId(nextStep.id);
    setSuccessMessage(null);
  }

  function handleRemoveStep(stepId: string) {
    const nextSteps = steps.filter((step) => step.id !== stepId);
    setSteps(nextSteps);
    if (selectedStepId === stepId) {
      setSelectedStepId(nextSteps[0]?.id ?? null);
    }
    setSuccessMessage(null);
  }

  function handleMoveStep(stepId: string, direction: "up" | "down") {
    setSteps((current) => {
      const index = current.findIndex((step) => step.id === stepId);
      if (index === -1) {
        return current;
      }
      const targetIndex = direction === "up" ? index - 1 : index + 1;
      if (targetIndex < 0 || targetIndex >= current.length) {
        return current;
      }
      const next = [...current];
      const [step] = next.splice(index, 1);
      next.splice(targetIndex, 0, step);
      return next;
    });
    setSuccessMessage(null);
  }

  function handleStepChange(nextStep: EditorStep) {
    setSteps((current) => current.map((step) => (step.id === nextStep.id ? nextStep : step)));
    setSuccessMessage(null);
  }

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Pipeline editor"
      title={name.trim() || pipeline?.name || "New pipeline"}
      subtitle="Build reusable transformation pipelines with structured step forms, explicit preview, and controlled execution."
      actions={actionLinks}
      meta={
        <>
          <StatusBadge value={status} />
          {hasUnsavedChanges ? (
            <span className="rounded-full border border-warning-line bg-warning-soft px-3 py-1 text-xs uppercase tracking-[0.18em] text-warning">
              Unsaved changes
            </span>
          ) : null}
          {selectedDataset ? (
            <span className="rounded-full border border-line bg-surface px-3 py-1 text-xs uppercase tracking-[0.18em] text-ink-2">
              {selectedDataset.name}
            </span>
          ) : null}
        </>
      }
    >
      {formError ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-4 text-sm text-danger shadow-[var(--shadow-md)]">
          {formError}
        </div>
      ) : null}
      {successMessage ? (
        <div className="rounded-2xl border border-success-line bg-success-soft px-4 py-4 text-sm text-success shadow-[var(--shadow-md)]">
          {successMessage}
        </div>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[0.28fr_0.72fr]">
        <SectionPanel title="Pipeline details" description="Name, lifecycle status, and the source dataset for this reusable pipeline definition.">
          <div className="space-y-5">
            <FormField label="Pipeline name" htmlFor="pipeline-name" error={nameError}>
              <Input id="pipeline-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Standardize customer orders" />
            </FormField>

            <FormField label="Description" htmlFor="pipeline-description">
              <Textarea id="pipeline-description" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Normalize incoming order data, remove invalid rows, and prepare a reusable derived dataset." />
            </FormField>

            <div className="grid gap-4 md:grid-cols-2">
              <FormField label="Status" htmlFor="pipeline-status">
                <Select id="pipeline-status" value={status} onChange={(event) => setStatus(event.target.value as typeof status)}>
                  <option value="draft">Draft</option>
                  <option value="active">Active</option>
                </Select>
              </FormField>

              <FormField label="Base dataset" htmlFor="pipeline-dataset">
                <Select
                  id="pipeline-dataset"
                  value={baseDatasetId ?? ""}
                  onChange={(event) => setBaseDatasetId(event.target.value || null)}
                  disabled={Boolean(pipeline)}
                >
                  <option value="">Select a dataset</option>
                  {datasets.map((dataset) => (
                    <option key={dataset.id} value={dataset.id}>
                      {dataset.name}
                    </option>
                  ))}
                </Select>
              </FormField>
            </div>

            {selectedDataset ? (
              <div className="rounded-2xl border border-line bg-sunken px-4 py-4 text-sm text-ink-2">
                <div className="text-[11px] uppercase tracking-[0.18em] text-muted">Base dataset</div>
                <div className="mt-2">
                  <Link href={`/projects/${project.id}/datasets/${selectedDataset.id}`} className="text-accent hover:text-accent">
                    {selectedDataset.name}
                  </Link>
                </div>
              </div>
            ) : null}
            {editorHref ? (
              <div className="rounded-2xl border border-line bg-sunken px-4 py-4 text-sm text-ink-2">
                <div className="text-[11px] uppercase tracking-[0.18em] text-muted">Editor route</div>
                <div className="mt-2 break-all">
                  <Link href={editorHref} className="text-accent hover:text-accent">
                    {editorHref}
                  </Link>
                </div>
              </div>
            ) : null}
          </div>
        </SectionPanel>

        <SectionPanel title="Steps" description="Add, order, and configure transformation steps without hand-writing JSON.">
          <PipelineStepList
            steps={steps}
            selectedStepId={selectedStepId}
            onSelect={setSelectedStepId}
            onAdd={handleAddStep}
            onRemove={handleRemoveStep}
            onMove={handleMoveStep}
          />
        </SectionPanel>
      </div>

      <div className="grid gap-6 xl:grid-cols-[0.42fr_0.58fr]">
        <PipelineStepEditor
          step={selectedStep}
          onChange={handleStepChange}
        />

        <div className="space-y-6">
          <PipelinePreviewPanel preview={preview} loading={previewLoading} error={previewError} />

          <SectionPanel
            title="Advanced JSON"
            description="Secondary escape hatch for inspection only. Structured forms remain the primary editing experience."
          >
            <Textarea
              value={JSON.stringify(toApiSteps(steps), null, 2)}
              readOnly
              className="min-h-[260px] font-mono text-[13px]"
            />
          </SectionPanel>
        </div>
      </div>

      <SectionPanel title="Run behavior" description="Preview never persists data. Save persists the pipeline definition. Run executes only the last saved version and creates a derived dataset.">
        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-2xl border border-line bg-sunken px-4 py-4 text-sm leading-6 text-ink-2">
            Preview the current draft on demand before saving.
          </div>
          <div className="rounded-2xl border border-line bg-sunken px-4 py-4 text-sm leading-6 text-ink-2">
            Save writes `name`, `description`, `status`, and `steps_json` through the existing pipeline CRUD API.
          </div>
          <div className="rounded-2xl border border-line bg-sunken px-4 py-4 text-sm leading-6 text-ink-2">
            Run is enabled only for saved pipelines with no unsaved changes.
          </div>
        </div>
      </SectionPanel>
    </AppShell>
  );
}
