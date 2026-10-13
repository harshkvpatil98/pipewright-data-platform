"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import type {
  AuthUser,
  DatasetRecord,
  TransformationPipelineRecord,
  TransformationRunResponse,
} from "@platform/shared-types";
import { Button } from "@platform/shared-ui";

import { AppFrame } from "@/components/shell/app-frame";
import type { Command } from "@/components/shell/command-palette";
import { useToast } from "@/components/providers/toast-provider";
import { STUDIO_TOUR_ID, studioTour } from "@/components/tour/tours";
import { useTour } from "@/components/tour/tour-provider";
import { ActionMenu } from "@/components/ui/action-menu";
import { Icon } from "@/components/ui/icon";
import { AddDataDialog } from "@/features/datasets/components/add-data-dialog";
import { useUnsavedChangesGuard } from "@/features/navigation/unsaved-changes-guard";
import { DetailsDrawer, type ExecutionPlan } from "@/features/studio/details-drawer";
import { DataGrid, type GridColumn } from "@/features/studio/grid/data-grid";
import { RecipeTemplatesDialog } from "@/features/studio/recipe-templates-dialog";
import { clearDraft, draftKey, readDraft, writeDraft, type RecipeDraft } from "@/features/studio/recipe-draft";
import { record, redo, startHistory, undo, type History } from "@/features/studio/recipe-history";
import { prefillConfig, type StepDefinition } from "@/features/studio/step-catalog";
import { StepPalette } from "@/features/studio/step-palette";
import { StepsTimeline, type StepOutcome, type TimelineStep } from "@/features/studio/steps-timeline";
import type { ToolCatalogue } from "@/features/studio/tools/tool-catalogue";
import { planPhrase, previewScope } from "@/features/studio/studio-words";
import { sortForView, type ViewSort } from "@/features/studio/view-sort";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { friendlyStepMessage } from "@/lib/labels";
import { cx } from "@/lib/utils";

type PreviewResponse = {
  preview_rows: Record<string, unknown>[];
  preview_columns: string[];
  row_count_before: number;
  row_count_after: number;
  column_count_before: number;
  column_count_after: number;
  schema_after: {
    columns: { name: string; inferred_type: string; canonical_type?: string | null }[];
  };
  execution_plan?: ExecutionPlan | null;
  step_outcomes?: (StepOutcome & { index: number; step_type: string })[];
  warnings: string[];
};

type StoredStep = { step_type: string; config: Record<string, unknown> };

type StudioPageProps = {
  currentUser: AuthUser;
  projectId: string;
  datasets: DatasetRecord[];
  initialDatasetId?: string;
  /** An existing recipe to open, from `?recipe=`. */
  recipe?: TransformationPipelineRecord | null;
};

let uidCounter = 0;
const nextUid = () => `step-${++uidCounter}`;

const withUids = (steps: StoredStep[]): TimelineStep[] =>
  steps.map((step) => ({ uid: nextUid(), step_type: step.step_type, config: step.config }));

const stored = (steps: TimelineStep[]): StoredStep[] =>
  steps.map((step) => ({ step_type: step.step_type, config: step.config }));

/** What "unsaved" is measured against: the name and steps as last saved. */
const signature = (name: string, steps: TimelineStep[]) => JSON.stringify([name.trim(), stored(steps)]);

/** Messages that mean "this step is not set up yet": guidance, not failure. */
const INCOMPLETE = /cannot be empty|missing required field|must be a non-empty|is required/i;

export function StudioPage({ currentUser, projectId, datasets, initialDatasetId, recipe = null }: StudioPageProps) {
  const router = useRouter();
  const toast = useToast();
  const { start, startIfUnseen } = useTour();

  const [datasetId, setDatasetId] = useState(
    recipe?.base_dataset_id ?? initialDatasetId ?? datasets[0]?.id ?? "",
  );
  const dataset = useMemo(() => datasets.find((item) => item.id === datasetId) ?? null, [datasets, datasetId]);

  // ----------------------------------------------------------- the recipe
  const [saved, setSaved] = useState<{ id: string; name: string } | null>(
    recipe ? { id: recipe.id, name: recipe.name } : null,
  );
  const [history, setHistory] = useState<History<TimelineStep[]>>(() =>
    startHistory(withUids((recipe?.steps_json as StoredStep[] | undefined) ?? [])),
  );
  const steps = history.present;
  const [name, setName] = useState(recipe?.name ?? (dataset ? `${dataset.name} recipe` : ""));
  const [nameTouched, setNameTouched] = useState(Boolean(recipe));
  const [baseline, setBaseline] = useState(() => (recipe ? signature(recipe.name, history.present) : null));
  const dirty = baseline === null ? steps.length > 0 : signature(name, steps) !== baseline;

  const change = useCallback(
    (next: (current: TimelineStep[]) => TimelineStep[], group?: string) =>
      setHistory((current) => record(current, next(current.present), { group })),
    [],
  );

  // ------------------------------------------------------- local draft
  // Unsaved work is kept in this browser, so an ended session, a closed tab
  // or a crash does not lose it. It is offered back the next time this recipe
  // (or a new recipe on this dataset) is opened.
  const key = draftKey(projectId, saved?.id ?? null, datasetId);
  const [offer, setOffer] = useState<RecipeDraft | null>(null);
  const offerChecked = useRef(false);

  useEffect(() => {
    if (offerChecked.current) return;
    offerChecked.current = true;
    const draft = readDraft(key);
    if (draft && JSON.stringify([draft.name.trim(), draft.steps]) !== signature(name, steps)) setOffer(draft);
    // Checked once, against what the page opened with.
  }, []);

  useEffect(() => {
    if (!dirty) {
      // An offered draft stays until it is restored or discarded.
      if (!offer) clearDraft(key);
      return;
    }
    // Starting fresh while the offer is showing is the answer to it.
    if (offer) setOffer(null);
    const timer = setTimeout(() => writeDraft(key, { name, steps: stored(steps), at: Date.now() }), 500);
    return () => clearTimeout(timer);
  }, [key, dirty, name, steps, offer]);

  const restoreDraft = () => {
    if (!offer) return;
    change(() => withUids(offer.steps));
    setName(offer.name);
    setNameTouched(true);
    setOpenUid(null);
    setOffer(null);
  };

  // A new recipe's name follows the dataset until somebody types one.
  useEffect(() => {
    if (!nameTouched && !saved && dataset) setName(`${dataset.name} recipe`);
  }, [dataset, nameTouched, saved]);

  const [openUid, setOpenUid] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteColumn, setPaletteColumn] = useState<string | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [addDataOpen, setAddDataOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [viewSort, setViewSort] = useState<ViewSort | null>(null);

  useUnsavedChangesGuard({
    when: dirty,
    title: "Leave without saving?",
    message: saved
      ? "Your changes to this recipe are not saved. They stay in this browser and are offered back the next time you open the recipe here."
      : "This recipe is not saved yet. Its steps stay in this browser and are offered back the next time you open this dataset in the Studio.",
  });

  // Once saved, the address names the recipe, so a reload or a bookmark opens
  // it again. Deferred a moment: the leave guard steps back out of the history
  // entry it added while there were unsaved changes, and replacing the address
  // before that would replace the wrong entry.
  useEffect(() => {
    if (dirty || !saved) return;
    const target = `/projects/${projectId}/studio?recipe=${saved.id}`;
    const timer = setTimeout(() => {
      if (`${window.location.pathname}${window.location.search}` !== target) {
        window.history.replaceState(null, "", target);
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [dirty, saved, projectId]);

  useEffect(() => {
    const timer = setTimeout(() => startIfUnseen(studioTour, STUDIO_TOUR_ID), 1200);
    return () => clearTimeout(timer);
  }, [startIfUnseen]);

  // ------------------------------------------------------------- preview
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Generation-guarded: a slow response never overwrites a newer one.
  const generation = useRef(0);

  const runPreview = useCallback(
    async (activeSteps: TimelineStep[], activeDatasetId: string) => {
      if (!activeDatasetId) {
        setPreview(null);
        return;
      }
      const ticket = ++generation.current;
      setLoading(true);
      setError(null);
      try {
        const response = await apiFetch<PreviewResponse>(
          `/projects/${projectId}/datasets/${activeDatasetId}/pipelines/preview`,
          { method: "POST", body: JSON.stringify({ steps: stored(activeSteps) }) },
        );
        if (ticket === generation.current) setPreview(response);
      } catch (caught) {
        // The last good preview is kept, marked stale: a step is added before
        // it is set up, and the data vanishing at that moment is exactly when
        // somebody needs to look at it.
        if (ticket === generation.current) setError(extractErrorMessage(caught));
      } finally {
        if (ticket === generation.current) setLoading(false);
      }
    },
    [projectId],
  );

  useEffect(() => {
    const timer = setTimeout(() => void runPreview(steps, datasetId), 320);
    return () => clearTimeout(timer);
  }, [steps, datasetId, runPreview]);

  // The source's own columns, so a half-set-up step still offers real names.
  const [baseColumns, setBaseColumns] = useState<{ name: string; type?: string }[]>([]);
  useEffect(() => {
    if (!datasetId) {
      setBaseColumns([]);
      return;
    }
    let cancelled = false;
    apiFetch<PreviewResponse>(`/projects/${projectId}/datasets/${datasetId}/pipelines/preview`, {
      method: "POST",
      body: JSON.stringify({ steps: [] }),
    })
      .then((response) => {
        if (cancelled) return;
        const types = new Map(response.schema_after.columns.map((c) => [c.name, c.canonical_type ?? c.inferred_type]));
        setBaseColumns(response.preview_columns.map((column) => ({ name: column, type: types.get(column) })));
      })
      .catch(() => {
        if (!cancelled) setBaseColumns([]);
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId, projectId]);

  const columns = useMemo<GridColumn[]>(() => {
    if (!preview) return [];
    const types = new Map(preview.schema_after.columns.map((c) => [c.name, c.canonical_type ?? c.inferred_type]));
    return preview.preview_columns.map((column) => ({ name: column, type: types.get(column) }));
  }, [preview]);

  /** Columns offered in step settings: the result's, plus the source's while a step is half set up. */
  const settingsColumns = useMemo(() => {
    const seen = new Map<string, { name: string; type?: string }>();
    for (const column of [...columns, ...baseColumns]) if (!seen.has(column.name)) seen.set(column.name, column);
    return Array.from(seen.values());
  }, [columns, baseColumns]);

  // A view sort on a column that has gone (renamed, removed) is dropped.
  useEffect(() => {
    if (viewSort && preview && !preview.preview_columns.includes(viewSort.column)) setViewSort(null);
  }, [preview, viewSort]);

  const rows = useMemo(() => sortForView(preview?.preview_rows ?? [], viewSort), [preview, viewSort]);

  // --------------------------------------------------------- tool library
  const [catalogue, setCatalogue] = useState<ToolCatalogue>({ categories: [], items: [] });
  const [preselect, setPreselect] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    apiFetch<ToolCatalogue>("/transformations/tools")
      .then((response) => {
        if (!cancelled) setCatalogue(response);
      })
      .catch(() => {
        // The common steps still work without the library.
        if (!cancelled) setCatalogue({ categories: [], items: [] });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // ------------------------------------------------------------- editing
  const openPalette = useCallback((column: string | null = null, tool: string | null = null) => {
    setPaletteColumn(column);
    setPreselect(tool);
    setPaletteOpen(true);
  }, []);

  const addBuiltIn = (definition: StepDefinition, column: string | null) => {
    const step: TimelineStep = { uid: nextUid(), step_type: definition.type, config: prefillConfig(definition, column) };
    change((current) => [...current, step]);
    setOpenUid(step.uid);
    setPaletteOpen(false);
  };

  const addTool = (config: Record<string, unknown>) => {
    const step: TimelineStep = { uid: nextUid(), step_type: "tool", config };
    change((current) => [...current, step]);
    setOpenUid(null);
    setPaletteOpen(false);
  };

  const updateStep = (uid: string, config: Record<string, unknown>) =>
    change((current) => current.map((step) => (step.uid === uid ? { ...step, config } : step)), `config:${uid}`);

  const removeStep = (uid: string) => {
    change((current) => current.filter((step) => step.uid !== uid));
    setOpenUid((current) => (current === uid ? null : current));
  };

  const moveStep = (uid: string, direction: -1 | 1) =>
    change((current) => {
      const index = current.findIndex((step) => step.uid === uid);
      const target = index + direction;
      if (index === -1 || target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });

  const sortWholeTable = () => {
    if (!viewSort) return;
    const step: TimelineStep = {
      uid: nextUid(),
      step_type: "sort_rows",
      config: { columns: [viewSort.column], ascending: viewSort.direction === "asc" },
    };
    change((current) => [...current, step]);
    setViewSort(null);
  };

  const doUndo = useCallback(() => setHistory((current) => undo(current)), []);
  const doRedo = useCallback(() => setHistory((current) => redo(current)), []);

  // "/" adds a step; ⌘Z and ⇧⌘Z undo and redo. All ignored while typing.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.tagName === "SELECT" ||
        target?.isContentEditable;
      if (typing || paletteOpen) return;
      if (event.key === "/" && !event.metaKey && !event.ctrlKey && datasetId) {
        event.preventDefault();
        openPalette();
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) doRedo();
        else doUndo();
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "y") {
        event.preventDefault();
        doRedo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [paletteOpen, datasetId, openPalette, doUndo, doRedo]);

  // -------------------------------------------------------- save and run
  const save = useCallback(
    async (asNew = false) => {
      if (!dataset || steps.length === 0) return;
      const chosenName = name.trim() || `${dataset.name} recipe`;
      const finalName = asNew && saved ? `${chosenName} (copy)` : chosenName;
      setSaving(true);
      try {
        const body = JSON.stringify({ name: finalName, steps_json: stored(steps) });
        const result =
          saved && !asNew
            ? await apiFetch<TransformationPipelineRecord>(`/projects/${projectId}/pipelines/${saved.id}`, {
                method: "PATCH",
                body,
              })
            : await apiFetch<TransformationPipelineRecord>(`/projects/${projectId}/datasets/${dataset.id}/pipelines`, {
                method: "POST",
                body,
              });
        // The draft was kept under this recipe's key before it was saved; a
        // first save changes the key, so the old one is cleared here.
        clearDraft(draftKey(projectId, saved?.id ?? null, dataset.id));
        setSaved({ id: result.id, name: result.name });
        setName(result.name);
        setNameTouched(true);
        setBaseline(signature(result.name, steps));
        toast.success("Recipe saved", "Run it to save the result as a dataset, or put it on a schedule.");
      } catch (caught) {
        toast.error("Could not save the recipe", extractErrorMessage(caught));
      } finally {
        setSaving(false);
      }
    },
    [dataset, steps, name, saved, projectId, toast],
  );

  const run = useCallback(async () => {
    if (!saved || dirty) return;
    setRunning(true);
    try {
      const result = await apiFetch<TransformationRunResponse>(`/projects/${projectId}/pipelines/${saved.id}/run`, {
        method: "POST",
      });
      toast.notify({
        tone: "success",
        title: "Recipe ran",
        description: `The result, ${result.dataset.row_count?.toLocaleString() ?? "?"} rows, is saved as “${result.dataset.name}”.`,
        actions: [
          { label: "Open the result", onClick: () => router.push(`/projects/${projectId}/datasets/${result.dataset.id}`) },
          { label: "Schedule it", onClick: () => router.push(`/projects/${projectId}/schedules?new=1`) },
        ],
      });
    } catch (caught) {
      toast.error("The run did not finish", extractErrorMessage(caught));
    } finally {
      setRunning(false);
    }
  }, [saved, dirty, projectId, router, toast]);

  // ------------------------------------------------------------- display
  const incomplete = error !== null && INCOMPLETE.test(error);
  const problem = error ? { message: error, incomplete } : null;
  const plan = preview?.execution_plan ?? null;

  const toolCommands = useMemo<Command[]>(
    () =>
      catalogue.items.map((tool) => ({
        id: `tool:${tool.name}`,
        label: tool.title,
        group: tool.category,
        icon: "sparkles" as const,
        hint: tool.summary,
        keywords: [tool.name.replace(/[._]/g, " "), ...tool.synonyms].join(" "),
        run: () => openPalette(null, tool.name),
      })),
    [catalogue.items, openPalette],
  );

  const status = saved ? (dirty ? "Unsaved changes" : "Saved") : steps.length > 0 ? "Not saved yet" : "New recipe";

  return (
    <AppFrame currentUser={currentUser} commands={toolCommands} disableWelcomeTour>
      <div className="flex h-full min-h-0 flex-col">
        {/* ---------------------------------------------------------- header */}
        <header className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-[color:var(--panel)] px-4 py-2.5">
          <div className="min-w-0 flex-1 basis-[280px]">
            <div className="flex min-w-0 items-center gap-2">
              <label htmlFor="recipe-name" className="sr-only">
                Recipe name
              </label>
              <input
                id="recipe-name"
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                  setNameTouched(true);
                }}
                placeholder="Name this recipe"
                className="h-8 min-w-0 max-w-[320px] flex-1 rounded-lg border border-transparent bg-transparent px-1.5 text-[16px] font-semibold text-ink outline-none transition hover:border-line focus:border-[color:var(--accent)] focus:bg-sunken"
              />
              <span
                className={cx(
                  "shrink-0 rounded-full px-2 py-0.5 text-[12px]",
                  dirty ? "bg-warning-soft text-warning" : saved ? "bg-success-soft text-success" : "bg-surface-2 text-ink-3",
                )}
              >
                {status}
              </span>
            </div>
            <div data-tour="studio-source" className="mt-0.5 flex min-w-0 items-center gap-1.5 px-1.5 text-[13px] text-ink-3">
              <span className="shrink-0">From</span>
              {saved ? (
                <span
                  className="max-w-[240px] shrink-0 truncate font-medium text-ink-2"
                  title="A saved recipe always starts from the same dataset"
                >
                  {dataset?.name ?? "a dataset that is no longer here"}
                </span>
              ) : (
                <select
                  aria-label="Dataset to start from"
                  value={datasetId}
                  onChange={(event) => setDatasetId(event.target.value)}
                  className="h-7 min-w-0 max-w-[220px] rounded-md border border-line bg-sunken px-1.5 text-[13px] text-ink outline-none focus:border-[color:var(--accent)]"
                >
                  {datasets.length === 0 ? <option value="">No data yet</option> : null}
                  {datasets.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              )}
              <span className="hidden shrink-0 sm:inline">
                · {steps.length} step{steps.length === 1 ? "" : "s"}
              </span>
              <span className="hidden min-w-0 truncate [@media(min-height:700px)]:inline">
                · Clean and reshape a dataset step by step. The original is never changed.
              </span>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-1.5">
            <IconButton icon="undo" label="Undo" shortcut="⌘Z" disabled={history.past.length === 0} onClick={doUndo} />
            <IconButton icon="redo" label="Redo" shortcut="⇧⌘Z" disabled={history.future.length === 0} onClick={doRedo} />
            <button
              type="button"
              onClick={() => setDetailsOpen((current) => !current)}
              aria-pressed={detailsOpen}
              className={cx(
                "flex h-9 items-center gap-1.5 rounded-lg px-2.5 text-[13px] transition",
                detailsOpen ? "bg-surface-2 text-ink" : "text-ink-3 hover:bg-surface-2 hover:text-ink",
              )}
            >
              <Icon name="panelRight" size={15} />
              Details
            </button>
            <ActionMenu
              label="More"
              variant="ghost"
              items={[
                ...(steps.length === 0 && datasetId
                  ? [{ id: "template", label: "Start from a template", icon: "sparkles" as const, onSelect: () => setTemplatesOpen(true) }]
                  : []),
                ...(saved && steps.length > 0
                  ? [{ id: "copy", label: "Save as a new recipe", icon: "plus" as const, onSelect: () => void save(true) }]
                  : []),
                ...(steps.length > 0
                  ? [
                      {
                        id: "clear",
                        label: "Remove all steps",
                        icon: "trash" as const,
                        description: "You can undo this.",
                        onSelect: () => change(() => []),
                      },
                    ]
                  : []),
                { id: "recipes", label: "All recipes", icon: "list" as const, href: `/projects/${projectId}/pipelines` },
                { id: "tour", label: "Show me around", icon: "help" as const, onSelect: () => start(studioTour, STUDIO_TOUR_ID) },
              ]}
            />
            <Button
              variant={dirty || !saved ? "primary" : "secondary"}
              size="sm"
              onClick={() => void save()}
              disabled={saving || !dataset || steps.length === 0 || (saved !== null && !dirty)}
            >
              {saving ? "Saving…" : "Save"}
            </Button>
            <Button
              variant={saved && !dirty ? "primary" : "secondary"}
              size="sm"
              onClick={() => void run()}
              disabled={running || !saved || dirty}
              title={
                !saved
                  ? "Save the recipe first"
                  : dirty
                    ? "Save your changes first; a run uses the saved recipe"
                    : "Run the saved recipe on the whole dataset and save the result"
              }
            >
              <Icon name="play" size={13} />
              {running ? "Running…" : "Run"}
            </Button>
          </div>
        </header>

        {/* ------------------------------------------------------------ body */}
        <div className="relative flex min-h-0 flex-1">
          <div className="flex w-[320px] shrink-0 flex-col border-r border-line bg-[color:var(--panel)]">
            <StepsTimeline
              sourceName={dataset?.name ?? null}
              source={preview ? { rows: preview.row_count_before, columns: preview.column_count_before } : null}
              result={preview && !error ? { rows: preview.row_count_after, columns: preview.column_count_after } : null}
              steps={steps}
              outcomes={error ? undefined : preview?.step_outcomes}
              openUid={openUid}
              onOpen={setOpenUid}
              onChange={updateStep}
              onMove={moveStep}
              onRemove={removeStep}
              onAdd={() => openPalette()}
              onTemplates={datasetId ? () => setTemplatesOpen(true) : null}
              problem={openUid ? problem : null}
              tools={catalogue.items}
              columns={settingsColumns}
              datasets={datasets.filter((item) => item.id !== datasetId).map((item) => ({ id: item.id, name: item.name }))}
            />
          </div>

          <section data-tour="studio-preview" aria-label="Preview" className="flex min-w-0 flex-1 flex-col p-3">
            {offer ? (
              <div
                role="status"
                className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl border border-info-line bg-info-soft px-3 py-2 text-[13px] text-info"
              >
                <Icon name="clock" size={15} className="shrink-0" />
                <span className="min-w-0 flex-1">
                  <span className="font-medium">You have unsaved work here from {draftTime(offer.at)}.</span>{" "}
                  {offer.steps.length} step{offer.steps.length === 1 ? "" : "s"} in “{offer.name || "an unnamed recipe"}”.
                </span>
                <span className="flex shrink-0 gap-1.5">
                  <Button size="sm" onClick={restoreDraft}>
                    Restore it
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      clearDraft(key);
                      setOffer(null);
                    }}
                  >
                    Discard
                  </Button>
                </span>
              </div>
            ) : null}
            {error && !openUid ? (
              <div
                role="status"
                className={cx(
                  "mb-2 flex items-start gap-2.5 rounded-xl border px-3 py-2 text-[13px]",
                  incomplete ? "border-info-line bg-info-soft text-info" : "border-danger-line bg-danger-soft text-danger",
                )}
              >
                <Icon name={incomplete ? "info" : "warning"} size={15} className="mt-0.5 shrink-0" />
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{incomplete ? "A step needs setting up. " : "A step cannot run. "}</span>
                  {friendlyStepMessage(error)}
                </span>
                {steps.length > 0 ? (
                  <button
                    type="button"
                    onClick={() => setOpenUid(steps[steps.length - 1].uid)}
                    className="shrink-0 rounded-md px-2 py-0.5 font-medium underline-offset-2 hover:underline"
                  >
                    Open the last step
                  </button>
                ) : null}
              </div>
            ) : null}

            {preview && preview.warnings.length > 0 ? (
              <div className="mb-2 rounded-xl border border-warning-line bg-warning-soft px-3 py-2 text-[13px] text-warning">
                {preview.warnings.map((warning) => (
                  <div key={warning} className="flex items-start gap-2">
                    <Icon name="info" size={14} className="mt-0.5 shrink-0" />
                    {warning}
                  </div>
                ))}
              </div>
            ) : null}

            <div className="mb-2 flex min-h-7 flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-ink-3">
              {preview ? (
                <>
                  <span className="tabular font-medium text-ink-2">
                    {previewScope(preview.preview_rows.length, preview.row_count_after)}
                  </span>
                  <span aria-hidden="true">·</span>
                  <span className="tabular">{preview.column_count_after} columns</span>
                  {preview.row_count_before !== preview.row_count_after ? (
                    <>
                      <span aria-hidden="true">·</span>
                      <span className="tabular">
                        {preview.row_count_before.toLocaleString()} → {preview.row_count_after.toLocaleString()} rows after
                        these steps
                      </span>
                    </>
                  ) : null}
                  {planPhrase(plan) ? (
                    <>
                      <span aria-hidden="true">·</span>
                      <button
                        type="button"
                        onClick={() => setDetailsOpen(true)}
                        className="underline-offset-2 hover:text-ink hover:underline"
                      >
                        {planPhrase(plan)}
                      </button>
                    </>
                  ) : null}
                </>
              ) : datasetId ? (
                <span>Loading the preview…</span>
              ) : null}
              {loading && preview ? (
                <span className="ml-auto flex items-center gap-1.5 text-muted">
                  <span className="h-1.5 w-1.5 animate-live rounded-full bg-[color:var(--accent)]" />
                  Updating
                </span>
              ) : null}
            </div>

            {viewSort ? (
              <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-line bg-surface px-3 py-1.5 text-[13px]">
                <Icon name="sort" size={14} className="text-ink-3" />
                <span className="text-ink">
                  Sorted by {viewSort.column}, {viewSort.direction === "asc" ? "A to Z" : "Z to A"}, for viewing.
                  <span className="text-ink-3"> Only the rows shown are sorted.</span>
                </span>
                <span className="ml-auto flex items-center gap-1">
                  <button
                    type="button"
                    onClick={sortWholeTable}
                    className="rounded-md px-2 py-1 font-medium text-[color:var(--accent-muted)] hover:bg-[color:var(--accent-faint)]"
                  >
                    Sort the whole table
                  </button>
                  <button
                    type="button"
                    onClick={() => setViewSort(null)}
                    aria-label="Stop sorting the view"
                    className="rounded-md p-1 text-muted hover:bg-surface-2 hover:text-ink"
                  >
                    <Icon name="close" size={13} />
                  </button>
                </span>
              </div>
            ) : null}

            <div className={cx("min-h-0 flex-1 transition-opacity", loading && "opacity-70")}>
              {datasets.length === 0 ? (
                <div className="flex h-full flex-col items-center justify-center rounded-xl border border-dashed border-line px-6 text-center">
                  <Icon name="table" size={26} className="text-muted" />
                  <h3 className="mt-3 text-[15px] font-medium text-ink-2">Nothing to clean yet</h3>
                  <p className="mt-1.5 max-w-sm text-[13px] leading-5 text-muted">
                    Add some data to this project, then come back to clean and reshape it here.
                  </p>
                  <div className="mt-4">
                    <Button size="sm" onClick={() => setAddDataOpen(true)}>
                      Add data
                    </Button>
                  </div>
                </div>
              ) : (
                <DataGrid
                  columns={columns}
                  rows={rows}
                  sort={viewSort}
                  onSortChange={(next) => setViewSort(next)}
                  onColumnMenu={(column) => openPalette(column)}
                  stale={error !== null}
                  emptyMessage={steps.length > 0 ? "These steps leave no rows. Try loosening a filter." : "Loading the preview…"}
                />
              )}
            </div>
          </section>

          <DetailsDrawer
            open={detailsOpen}
            onClose={() => setDetailsOpen(false)}
            columns={preview?.schema_after.columns ?? []}
            plan={plan}
            steps={stored(steps)}
            discussion={saved ? { projectId, recipeId: saved.id, currentUsername: currentUser.username } : null}
            onApplyFile={(next) => {
              change(() => withUids(next));
              setOpenUid(null);
              toast.success("Recipe updated", "The steps now match the file.");
            }}
          />
        </div>
      </div>

      {paletteOpen ? (
        <StepPalette
          tools={catalogue.items}
          columns={settingsColumns}
          column={paletteColumn}
          preselect={preselect}
          sampleRows={preview?.preview_rows ?? []}
          onAddBuiltIn={addBuiltIn}
          onAddTool={addTool}
          onClose={() => {
            setPaletteOpen(false);
            setPreselect(null);
          }}
        />
      ) : null}

      <RecipeTemplatesDialog
        open={templatesOpen}
        onClose={() => setTemplatesOpen(false)}
        projectId={projectId}
        datasetId={datasetId}
        onApply={(templateSteps, templateName) => {
          const added = withUids(templateSteps);
          change((current) => [...current, ...added]);
          setOpenUid(null);
          toast.success(
            `${templateName}: ${added.length} step${added.length === 1 ? "" : "s"} added`,
            "Check the result in the preview, change any step, then save the recipe.",
          );
        }}
      />
      <AddDataDialog open={addDataOpen} onClose={() => setAddDataOpen(false)} projectId={projectId} />

    </AppFrame>
  );
}

/** "14:05 today", or "3 Oct, 14:05" for an older draft. */
function draftTime(at: number): string {
  const when = new Date(at);
  const time = when.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  return when.toDateString() === new Date().toDateString()
    ? `${time} today`
    : `${when.toLocaleDateString(undefined, { day: "numeric", month: "short" })}, ${time}`;
}

function IconButton({
  icon,
  label,
  shortcut,
  disabled,
  onClick,
}: {
  icon: "undo" | "redo";
  label: string;
  shortcut: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={`${label} (${shortcut})`}
      className="flex h-9 w-9 items-center justify-center rounded-lg text-ink-3 transition hover:bg-surface-2 hover:text-ink disabled:opacity-30 disabled:hover:bg-transparent"
    >
      <Icon name={icon} size={16} />
    </button>
  );
}
