"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import type {
  AuthUser,
  DataContract,
  DataContractListResponse,
  DatasetRecord,
  RecipeSharedCopy,
  TransformationPipelineRecord,
  TransformationRunResponse,
} from "@platform/shared-types";
import { Badge, Button, Icon, Modal, useToast } from "@platform/shared-ui";

import { AppFrame } from "@/components/shell/app-frame";
import type { Command } from "@/components/shell/command-palette";
import { STUDIO_TOUR_ID, studioTour } from "@/components/tour/tours";
import { useTour } from "@/components/tour/tour-provider";
import { ActionMenu } from "@/components/ui/action-menu";
import { missingPromised } from "@/features/contracts/contract-words";
import { AddDataDialog } from "@/features/datasets/components/add-data-dialog";
import { useUnsavedChangesGuard } from "@/features/navigation/unsaved-changes-guard";
import { DetailsDrawer, type ExecutionPlan, type IncrementalMode } from "@/features/studio/details-drawer";
import { DataGrid, type GridColumn } from "@/features/studio/grid/data-grid";
import {
  CompareDialog,
  CopyDialog,
  MergeDialog,
  ParametersDialog,
  RunWithValuesDialog,
  SaveTemplateDialog,
  SplitDialog,
  usedParameters,
  type RecipeParameter,
} from "@/features/studio/recipe-actions";
import { RecipeTemplatesDialog } from "@/features/studio/recipe-templates-dialog";
import { clearDraft, draftKey, readDraft, writeDraft, type RecipeDraft } from "@/features/studio/recipe-draft";
import { CellFilterMenu, type PickedCell } from "@/features/studio/cell-filter-menu";
import { stableJson, type Doc } from "@/features/studio/coedit";
import { ENABLED, GROUP, NOTE, groupOf, grouped, isOff, turned, withoutRemarks } from "@/features/studio/step-flags";
import { STEP_COMMANDS, type StepCommandId } from "@/features/studio/palette-search";
import { PresenceDots } from "@/features/studio/presence-dots";
import { SuggestDialog } from "@/features/studio/suggest-dialog";
import { SuggestionsDrawer } from "@/features/studio/suggestions-drawer";
import { newStepId, useRecipeEditing } from "@/features/studio/use-recipe-editing";
import { usePresence } from "@/features/studio/use-presence";
import { STEP_BY_TYPE, prefillConfig, type StepDefinition } from "@/features/studio/step-catalog";
import { StepPalette } from "@/features/studio/step-palette";
import { OtherDatasetsProvider, datasetColumns } from "@/features/studio/tools/other-datasets";
import { SampleValuesProvider } from "@/features/studio/tools/regex-tester";
import { StepsTimeline, type StepOutcome, type TimelineStep } from "@/features/studio/steps-timeline";
import type { ToolCatalogue } from "@/features/studio/tools/tool-catalogue";
import { planPhrase, previewScope } from "@/features/studio/studio-words";
import { sortForView, type ViewSort } from "@/features/studio/view-sort";
import { apiFetch } from "@/lib/api/client";
import { ApiError, extractErrorMessage, failedStepIndex } from "@/lib/api/errors";
import { friendlyStepMessage } from "@/lib/labels";
import { cx } from "@/lib/utils";
import { countOf, formatCount, formatShortDate, formatTime } from "@/lib/format";
import { recipeHref } from "@/lib/navigation";

type PreviewResponse = {
  preview_rows: Record<string, unknown>[];
  preview_columns: string[];
  row_count_before: number;
  row_count_after: number;
  column_count_before: number;
  column_count_after: number;
  schema_before: { ordered_columns: string[] };
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
  /** Its shared working copy, and what the person may do with it (C2). */
  shared?: RecipeSharedCopy | null;
};

/** A step id unique across everyone's browsers, so people editing together never collide. */
const nextUid = newStepId;

const withUids = (steps: StoredStep[]): TimelineStep[] =>
  steps.map((step) => ({ uid: nextUid(), step_type: step.step_type, config: step.config }));

/** A saved recipe's steps with their stable ids. */
const savedSteps = (recipe: TransformationPipelineRecord | null): TimelineStep[] => {
  const stored = (recipe?.steps_json as StoredStep[] | undefined) ?? [];
  const ids = recipe?.step_ids ?? [];
  return stored.map((step, index) => ({
    uid: ids.length === stored.length ? ids[index] : nextUid(),
    step_type: step.step_type,
    config: step.config,
  }));
};

const stored = (steps: TimelineStep[]): StoredStep[] =>
  steps.map((step) => ({ step_type: step.step_type, config: step.config }));

/** A recipe's name and steps, to tell whether two are the same. */
const signature = (name: string, steps: TimelineStep[]) => stableJson([name.trim(), stored(steps)]);

/** Messages that mean "this step is not set up yet": guidance, not failure. */
const INCOMPLETE = /cannot be empty|missing required field|must be a non-empty|is required/i;

export function StudioPage({
  currentUser,
  projectId,
  datasets,
  initialDatasetId,
  recipe = null,
  shared = null,
}: StudioPageProps) {
  const router = useRouter();
  const toast = useToast();
  const { start, startIfUnseen } = useTour();

  const [datasetId, setDatasetId] = useState(
    recipe?.base_dataset_id ?? initialDatasetId ?? datasets[0]?.id ?? "",
  );
  const dataset = useMemo(() => datasets.find((item) => item.id === datasetId) ?? null, [datasets, datasetId]);
  // Datasets a lookup, an as-of join or a set tool can read besides this one.
  const otherDatasets = useMemo(
    () =>
      datasets
        .filter((item) => item.id !== datasetId)
        .map((item) => ({ id: item.id, name: item.name, columns: datasetColumns(item.schema_json) })),
    [datasets, datasetId],
  );

  // ----------------------------------------------------------- the recipe
  const [saved, setSaved] = useState<{ id: string; name: string } | null>(
    recipe ? { id: recipe.id, name: recipe.name } : null,
  );
  // How the saved recipe's runs compute (D2): every row, or only what changed.
  const [eachRun, setEachRun] = useState<{ mode: IncrementalMode; column: string | null }>({
    mode: recipe?.incremental_mode ?? "full",
    column: recipe?.partition_column ?? null,
  });
  // Who may do what with a saved recipe (C2). Someone who may edit works in
  // its shared copy with everyone else editing it; anyone else, or anyone in
  // a project whose changes need approval, suggests instead of saving.
  const role = shared?.your_role ?? null;
  const canEdit = shared ? role === "editor" || role === "admin" : true;
  const live = Boolean(recipe && shared && canEdit);
  const suggesting = Boolean(recipe && shared && (!canEdit || shared.needs_approval));
  const openingSteps = useMemo(() => savedSteps(recipe), [recipe]);
  const editing = useRecipeEditing({
    projectId,
    recipeId: recipe?.id ?? null,
    initialName: recipe?.name ?? "",
    initialSteps: openingSteps,
    live,
    initialRevision: recipe ? (recipe.revision ?? 1) : null,
    initialDoc: live ? ((shared?.doc as Doc | null) ?? null) : null,
  });
  const steps = editing.steps;
  const [newName, setNewName] = useState(dataset ? `${dataset.name} recipe` : "");
  const [nameTouched, setNameTouched] = useState(Boolean(recipe));
  const name = recipe ? editing.name : newName;
  const setName = (value: string) => (recipe ? editing.rename(value) : setNewName(value));
  // A new recipe just saved for the first time is not dirty while the page
  // reopens it as the saved recipe (below).
  const [firstSaved, setFirstSaved] = useState(false);
  const dirty = recipe ? editing.dirty : !firstSaved && steps.length > 0;
  const change = editing.change;

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
    // A shared copy keeps its own unsaved changes, for everyone editing it.
    if (live) return;
    const draft = readDraft(key);
    if (draft && stableJson([draft.name.trim(), draft.steps]) !== signature(name, steps)) setOffer(draft);
    // Checked once, against what the page opened with.
  }, []);

  useEffect(() => {
    if (live) return;
    if (!dirty) {
      // An offered draft stays until it is restored or discarded.
      if (!offer) clearDraft(key);
      return;
    }
    // Starting fresh while the offer is showing is the answer to it.
    if (offer) setOffer(null);
    const timer = setTimeout(() => writeDraft(key, { name, steps: stored(steps), at: Date.now() }), 500);
    return () => clearTimeout(timer);
  }, [key, dirty, name, steps, offer, live]);

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
    if (!nameTouched && !saved && dataset) setNewName(`${dataset.name} recipe`);
  }, [dataset, nameTouched, saved]);

  const [openUid, setOpenUid] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteColumn, setPaletteColumn] = useState<string | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  // Managing the recipe (E1): templates, parameters, branches, copies.
  const [managing, setManaging] = useState<
    null | "template" | "parameters" | "run-values" | "preview-values" | "merge" | "compare" | "copy" | "split"
  >(null);
  const [parameters, setParameters] = useState<RecipeParameter[]>((recipe?.parameters ?? []) as RecipeParameter[]);
  // Values the preview tries, for parameters without a default or to see another value's result.
  const [tryValues, setTryValues] = useState<Record<string, unknown>>({});
  const [parentRecipe, setParentRecipe] = useState<{ id: string; name: string } | null>(null);
  // The steps a template is saved from: all of them, or one group's.
  const [templateDraft, setTemplateDraft] = useState<{ name: string; steps: StoredStep[] } | null>(null);
  // The step a new comment is about, chosen from the steps.
  const [commentStep, setCommentStep] = useState<string | null>(null);
  const [addDataOpen, setAddDataOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [viewSort, setViewSort] = useState<ViewSort | null>(null);
  // A cell right-clicked in the preview, to keep or drop rows like it.
  const [pickedCell, setPickedCell] = useState<{ cell: PickedCell; at: { x: number; y: number } } | null>(null);

  useUnsavedChangesGuard({
    // A shared copy keeps unsaved changes on the server, so leaving loses nothing.
    when: dirty && !live,
    title: "Leave without saving?",
    message: saved
      ? "Your changes to this recipe are not saved. They stay in this browser and are offered back the next time you open the recipe here."
      : "This recipe is not saved yet. Its steps stay in this browser and are offered back the next time you open this dataset in the Studio.",
  });

  // Once saved, the address names the recipe, so a reload or a bookmark opens
  // it again. Deferred a moment: the leave guard steps back out of the history
  // entry it added while there were unsaved changes, and replacing the address
  // before that would replace the wrong entry.
  //
  // A recipe saved for the first time is opened again as itself, so that
  // from now on its editing is shared with anyone else editing it (C2).
  useEffect(() => {
    if (dirty || !saved) return;
    const target = `/projects/${projectId}/studio?recipe=${saved.id}`;
    const timer = setTimeout(() => {
      if (!recipe) router.replace(target);
      else if (`${window.location.pathname}${window.location.search}` !== target) {
        window.history.replaceState(null, "", target);
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [dirty, saved, projectId, recipe, router]);

  useEffect(() => {
    const timer = setTimeout(() => startIfUnseen(studioTour, STUDIO_TOUR_ID), 1200);
    return () => clearTimeout(timer);
  }, [startIfUnseen]);

  // The contract on the dataset this recipe's runs write, if any (C1): said
  // here so a step that drops a promised column is seen before it is run.
  const outputDatasetId = recipe?.output_dataset_id ?? null;
  const [resultContract, setResultContract] = useState<DataContract | null>(null);
  useEffect(() => {
    if (!outputDatasetId) return;
    let cancelled = false;
    apiFetch<DataContractListResponse>(`/projects/${projectId}/contracts`)
      .then((found) => {
        if (!cancelled) setResultContract(found.items.find((item) => item.dataset_id === outputDatasetId) ?? null);
      })
      .catch(() => {
        /* the notice is a convenience; the run itself is checked regardless */
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, outputDatasetId]);

  // ------------------------------------------------------------- preview
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Which step the problem is in, when the server says (from 0).
  const [errorStep, setErrorStep] = useState<number | null>(null);
  // Generation-guarded: a slow response never overwrites a newer one.
  const generation = useRef(0);

  const runPreview = useCallback(
    async (
      activeSteps: TimelineStep[],
      activeDatasetId: string,
      declared: RecipeParameter[],
      values: Record<string, unknown>,
    ) => {
      if (!activeDatasetId) {
        setPreview(null);
        return;
      }
      const ticket = ++generation.current;
      setLoading(true);
      setError(null);
      setErrorStep(null);
      try {
        const response = await apiFetch<PreviewResponse>(
          `/projects/${projectId}/datasets/${activeDatasetId}/pipelines/preview`,
          {
            method: "POST",
            body: JSON.stringify({ steps: stored(activeSteps), parameters: declared, parameter_values: values }),
          },
        );
        if (ticket === generation.current) setPreview(response);
      } catch (caught) {
        // The last good preview is kept, marked stale: a step is added before
        // it is set up, and the data vanishing at that moment is exactly when
        // somebody needs to look at it.
        if (ticket === generation.current) {
          setError(extractErrorMessage(caught));
          setErrorStep(failedStepIndex(caught));
        }
      } finally {
        if (ticket === generation.current) setLoading(false);
      }
    },
    [projectId],
  );

  // A note or a group never changes a result, so writing one does not run the preview again.
  const previewKey = useMemo(
    () => stableJson(steps.map((step) => [step.step_type, withoutRemarks(step.config)])),
    [steps],
  );
  const latestSteps = useRef(steps);
  latestSteps.current = steps;
  useEffect(() => {
    const timer = setTimeout(() => void runPreview(latestSteps.current, datasetId, parameters, tryValues), 320);
    return () => clearTimeout(timer);
  }, [previewKey, datasetId, parameters, tryValues, runPreview]);

  // The source's own columns, so a half-set-up step still offers real names.
  const [baseColumns, setBaseColumns] = useState<{ name: string; type?: string }[]>([]);
  const [baseRows, setBaseRows] = useState<Record<string, unknown>[]>([]);
  useEffect(() => {
    if (!datasetId) {
      setBaseColumns([]);
      setBaseRows([]);
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
        setBaseRows(response.preview_rows);
      })
      .catch(() => {
        if (!cancelled) {
          setBaseColumns([]);
          setBaseRows([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId, projectId]);

  // Values to try a pattern on: the source's, or the preview's for a column a step made.
  const sampleValues = useCallback(
    (column: string | null) => {
      if (!column) return [];
      const rows = baseRows.length && column in baseRows[0] ? baseRows : (preview?.preview_rows ?? []);
      const seen = new Set<string>();
      for (const row of rows) {
        const value = row[column];
        if (value !== null && value !== undefined && value !== "") seen.add(String(value));
        if (seen.size >= 8) break;
      }
      return [...seen];
    },
    [baseRows, preview],
  );

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

  const updateStep = (uid: string, config: Record<string, unknown>) => {
    // Typing in a setting is one change to undo; turning the step off is its own, and so is its note.
    const before = steps.find((step) => step.uid === uid)?.config ?? {};
    const keys = [...new Set([...Object.keys(before), ...Object.keys(config)])].filter(
      (key) => stableJson(before[key]) !== stableJson(config[key]),
    );
    const only = keys.length === 1 ? keys[0] : null;
    const group =
      only === ENABLED || only === GROUP ? undefined : only === NOTE ? `note:${uid}` : `config:${uid}`;
    change((current) => current.map((step) => (step.uid === uid ? { ...step, config } : step)), group);
  };

  const changeMany = (configs: Record<string, Record<string, unknown>>) =>
    change((current) => current.map((step) => (configs[step.uid] ? { ...step, config: configs[step.uid] } : step)));

  const duplicateStep = (uid: string) => {
    const copy = steps.find((step) => step.uid === uid);
    if (!copy) return;
    const made: TimelineStep = { uid: nextUid(), step_type: copy.step_type, config: structuredClone(copy.config) };
    change((current) => {
      const index = current.findIndex((step) => step.uid === uid);
      return index === -1 ? current : [...current.slice(0, index + 1), made, ...current.slice(index + 1)];
    });
    setOpenUid(made.uid);
  };

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

  const doUndo = editing.undo;
  const doRedo = editing.redo;

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
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  const [discarding, setDiscarding] = useState(false);

  const save = useCallback(
    async (asNew = false) => {
      if (!dataset || steps.length === 0) return;
      if (suggesting && !asNew) {
        setSuggestOpen(true);
        return;
      }
      const chosenName = name.trim() || `${dataset.name} recipe`;
      const finalName = asNew && saved ? `${chosenName} (copy)` : chosenName;
      setSaving(true);
      try {
        if (saved && !asNew) {
          // Name the revision this copy started from, so a save never writes
          // over someone else's; in a shared copy, also its epoch (C2).
          const send = () => {
            const current = editing.forSaving();
            return apiFetch<TransformationPipelineRecord>(`/projects/${projectId}/pipelines/${saved.id}`, {
              method: "PATCH",
              body: JSON.stringify({
                name: finalName,
                steps_json: stored(current.steps),
                step_ids: current.steps.map((step) => step.uid),
                expected_revision: current.revision ?? undefined,
                shared_epoch: live ? (current.epoch ?? undefined) : undefined,
              }),
            });
          };
          let result: TransformationPipelineRecord;
          try {
            result = await send();
          } catch (caught) {
            // In a shared copy, someone else's save is already merged in:
            // catch up on it, then save again.
            if (!(live && caught instanceof ApiError && caught.status === 409)) throw caught;
            await editing.refresh();
            result = await send();
          }
          await editing.markSaved(result.revision ?? 1, result.name, editing.forSaving().steps);
          setSaved({ id: result.id, name: result.name });
          toast.success("Recipe saved", "Run it to save the result as a dataset, or put it on a schedule.");
          return;
        }
        const result = await apiFetch<TransformationPipelineRecord>(
          `/projects/${projectId}/datasets/${dataset.id}/pipelines`,
          { method: "POST", body: JSON.stringify({ name: finalName, steps_json: stored(steps), parameters }) },
        );
        // The draft was kept under this recipe's key before it was saved; a
        // first save changes the key, so the old one is cleared here.
        clearDraft(draftKey(projectId, saved?.id ?? null, dataset.id));
        toast.success("Recipe saved", "Run it to save the result as a dataset, or put it on a schedule.");
        if (asNew && recipe) {
          // A copy is its own recipe, with its own shared copy: open it.
          router.push(`/projects/${projectId}/studio?recipe=${result.id}`);
          return;
        }
        // Saved: the leave guard lets go, then the page reopens it as itself.
        setFirstSaved(true);
        setSaved({ id: result.id, name: result.name });
      } catch (caught) {
        toast.error("Could not save the recipe", extractErrorMessage(caught));
      } finally {
        setSaving(false);
      }
    },
    [dataset, steps, name, saved, projectId, toast, suggesting, live, editing, router, recipe, parameters],
  );

  const discardUnsaved = useCallback(async () => {
    if (!saved) return;
    try {
      await apiFetch(`/projects/${projectId}/pipelines/${saved.id}/shared/discard`, { method: "POST" });
      await editing.refresh();
      editing.clearResetReason();
      editing.clearSetAside();
      toast.success("Unsaved changes discarded", "The recipe shows its saved version, for everyone editing it.");
    } catch (caught) {
      toast.error("Could not discard the changes", extractErrorMessage(caught));
    } finally {
      setDiscarding(false);
    }
  }, [saved, projectId, editing, toast]);

  // Someone else saved: say so once, by name.
  useEffect(() => {
    const other = editing.savedBySomeoneElse;
    if (!other) return;
    if (other.revisedBy && other.revisedBy !== currentUser.username && other.revisedBy !== currentUser.display_name) {
      toast.notify({ tone: "info", title: `${other.revisedBy} saved this recipe`, description: "What you see is what is saved, with any changes still unsaved." });
    }
    editing.clearSavedBySomeoneElse();
  }, [editing, editing.savedBySomeoneElse, currentUser, toast]);

  // Who else has this recipe open, and which step each has open.
  const others = usePresence({
    projectId,
    recipeId: recipe?.id ?? null,
    clientId: editing.clientId,
    focus: openUid ? { step: openUid } : null,
  });

  const run = useCallback(async (values?: Record<string, unknown>) => {
    if (!saved || dirty) return;
    setRunning(true);
    try {
      const result = await apiFetch<TransformationRunResponse>(`/projects/${projectId}/pipelines/${saved.id}/run`, {
        method: "POST",
        body: values ? JSON.stringify({ parameters: values }) : undefined,
      });
      toast.notify({
        tone: "success",
        title: "Recipe ran",
        description: `The result${result.dataset.row_count == null ? "" : `, ${countOf(result.dataset.row_count, "row")},`} is saved as “${result.dataset.name}”.`,
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

  // A branch merges back into the recipe it came from: by name.
  const parentId = recipe?.branched_from_id ?? null;
  useEffect(() => {
    if (!parentId) return;
    let cancelled = false;
    apiFetch<TransformationPipelineRecord>(`/projects/${projectId}/pipelines/${parentId}`)
      .then((found) => {
        if (!cancelled) setParentRecipe({ id: found.id, name: found.name });
      })
      .catch(() => {
        /* the recipe it came from was deleted: there is nothing to merge into */
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, parentId]);

  const branch = useCallback(async () => {
    if (!saved) return;
    try {
      const made = await apiFetch<TransformationPipelineRecord>(`/projects/${projectId}/pipelines/${saved.id}/branch`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      toast.success(`Branched as “${made.name}”`, "Change it freely; merge it back from More when it is ready.");
      router.push(recipeHref(projectId, made.id));
    } catch (caught) {
      toast.error("Could not branch the recipe", extractErrorMessage(caught));
    }
  }, [saved, projectId, router, toast]);

  const usedNames = useMemo(() => usedParameters(stored(steps)), [steps]);

  // A thread can be on a step as last saved; each is named by its number and words.
  const savedStepIds = useMemo(() => new Set((editing.saved?.steps ?? []).map((step) => step.uid)), [editing.saved]);
  const stepNames = useMemo(() => {
    const names: Record<string, string> = {};
    (editing.saved?.steps ?? []).forEach((step, index) => {
      const title =
        step.step_type === "tool"
          ? catalogue.items.find((tool) => tool.name === step.config.tool)?.title
          : STEP_BY_TYPE.get(step.step_type)?.label;
      names[step.uid] = `step ${index + 1} (${title ?? step.step_type.replace(/_/g, " ")})`;
    });
    return names;
  }, [editing.saved, catalogue.items]);

  // ------------------------------------------------------------- display
  const incomplete = error !== null && INCOMPLETE.test(error);
  const problem = error
    ? { message: error, incomplete, uid: errorStep === null ? null : (steps[errorStep]?.uid ?? null) }
    : null;
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

  // What can be done to the open step, from the command palette. Read through
  // a ref, so the commands are made once and always act on the current steps.
  const stepActions = useRef<(id: StepCommandId) => void>(() => {});
  stepActions.current = (id) => {
    const index = steps.findIndex((step) => step.uid === openUid);
    const step = steps[index];
    if (!step) {
      toast.notify({
        tone: "info",
        title: "Open a step first",
        description: "Choose a step in the list; its buttons turn it off, duplicate it or group it.",
      });
      return;
    }
    if (id === "studio:turn") updateStep(step.uid, turned(step.config, isOff(step.config)));
    else if (id === "studio:duplicate") duplicateStep(step.uid);
    else {
      const next = steps[index + 1];
      if (!next) {
        toast.notify({ tone: "info", title: "There is no step after this one to group it with" });
        return;
      }
      const taken = new Set(steps.map((item) => groupOf(item.config)).filter(Boolean)).size;
      const groupName = groupOf(step.config) || `Group ${taken + 1}`;
      changeMany({ [step.uid]: grouped(step.config, groupName), [next.uid]: grouped(next.config, groupName) });
    }
  };
  const commands = useMemo<Command[]>(
    () => [
      ...STEP_COMMANDS.map((command) => ({
        id: command.id,
        label: command.label,
        group: "Studio",
        icon: command.icon,
        keywords: command.keywords,
        run: () => stepActions.current(command.id),
      })),
      ...toolCommands,
    ],
    [toolCommands],
  );

  const status = suggesting
    ? dirty
      ? "Not suggested yet"
      : "Saved"
    : saved
      ? dirty
        ? "Unsaved changes"
        : "Saved"
      : steps.length > 0
        ? "Not saved yet"
        : "New recipe";
  const stepOthers = useMemo(() => {
    const byStep: Record<string, typeof others> = {};
    for (const person of others) {
      const step = person.focus?.step;
      if (step) byStep[step] = [...(byStep[step] ?? []), person];
    }
    return byStep;
  }, [others]);
  const suggestReason = !canEdit
    ? "You can see this recipe but not change it, so your changes go to someone who can, to accept or decline."
    : "Changes in this project need someone else's approval, so this goes to them to accept or decline.";

  return (
    <AppFrame currentUser={currentUser} commands={commands} heading="Studio" disableWelcomeTour>
      <OtherDatasetsProvider datasets={otherDatasets}>
      <SampleValuesProvider samples={sampleValues}>
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
              <Badge tone={dirty ? "warning" : saved ? "success" : "neutral"} className="shrink-0">
                {status}
              </Badge>
              <PresenceDots
                people={others}
                label={(person) => `${person.name} has this recipe open`}
              />
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
            <IconButton icon="undo" label="Undo" shortcut="⌘Z" disabled={!editing.canUndo} onClick={doUndo} />
            <IconButton icon="redo" label="Redo" shortcut="⇧⌘Z" disabled={!editing.canRedo} onClick={doRedo} />
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
                ...(saved && steps.length > 0 && canEdit
                  ? [{ id: "copy", label: "Save as a new recipe", icon: "plus" as const, onSelect: () => void save(true) }]
                  : []),
                ...(steps.length > 0
                  ? [
                      {
                        id: "save-template",
                        label: "Save steps as a template",
                        icon: "sparkles" as const,
                        description: "For anyone in this project to start from.",
                        onSelect: () => setManaging("template"),
                      },
                    ]
                  : []),
                ...(canEdit && !suggesting && datasetId
                  ? [
                      {
                        id: "parameters",
                        label: parameters.length ? `Parameters (${parameters.length})` : "Parameters",
                        icon: "settings" as const,
                        description: "Values each run is given, written {{name}} in a setting.",
                        onSelect: () => setManaging("parameters"),
                      },
                    ]
                  : []),
                ...(parameters.length
                  ? [
                      {
                        id: "preview-values",
                        label: "Preview with other values",
                        icon: "refresh" as const,
                        onSelect: () => setManaging("preview-values"),
                      },
                    ]
                  : []),
                ...(parameters.length && saved && !dirty && role !== "viewer"
                  ? [
                      {
                        id: "run-values",
                        label: "Run with other values",
                        icon: "play" as const,
                        onSelect: () => setManaging("run-values"),
                      },
                    ]
                  : []),
                ...(saved && !dirty && canEdit
                  ? [
                      {
                        id: "branch",
                        label: "Branch this recipe",
                        icon: "link" as const,
                        description: "A copy to try changes in, to merge back later.",
                        onSelect: () => void branch(),
                      },
                      {
                        id: "copy-to",
                        label: "Use on another dataset",
                        icon: "database" as const,
                        description: "The same steps, reading another dataset.",
                        onSelect: () => setManaging("copy"),
                      },
                      {
                        id: "split",
                        label: "One recipe for each value",
                        icon: "filter" as const,
                        description: "A copy per region, client or other value.",
                        onSelect: () => setManaging("split"),
                      },
                    ]
                  : []),
                ...(saved && !dirty && canEdit && parentRecipe
                  ? [
                      {
                        id: "merge",
                        label: `Merge into ${parentRecipe.name}`,
                        icon: "merge" as const,
                        onSelect: () => setManaging("merge"),
                      },
                    ]
                  : []),
                ...(steps.length > 0
                  ? [
                      {
                        id: "compare",
                        label: "Compare with another recipe",
                        icon: "list" as const,
                        onSelect: () => setManaging("compare"),
                      },
                    ]
                  : []),
                ...(saved && canEdit
                  ? [
                      {
                        id: "suggestions",
                        label: editing.shared?.openSuggestions
                          ? `Suggestions waiting (${editing.shared.openSuggestions})`
                          : "Suggestions",
                        icon: "mail" as const,
                        description: "Changes people suggested for this recipe.",
                        onSelect: () => setSuggestionsOpen(true),
                      },
                    ]
                  : []),
                ...(live && dirty
                  ? [
                      {
                        id: "discard",
                        label: "Discard unsaved changes",
                        icon: "undo" as const,
                        description: "For everyone editing it: back to the saved recipe.",
                        onSelect: () => setDiscarding(true),
                      },
                    ]
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
              title={suggesting ? suggestReason : undefined}
            >
              {saving ? "Saving…" : suggesting ? "Suggest" : "Save"}
            </Button>
            <Button
              variant={saved && !dirty ? "primary" : "secondary"}
              size="sm"
              onClick={() => void run()}
              disabled={running || !saved || dirty || role === "viewer"}
              title={
                !saved
                  ? "Save the recipe first"
                  : role === "viewer"
                    ? "Running a recipe needs the operator role or above"
                    : dirty
                      ? suggesting
                        ? "A run uses the saved recipe; your changes are not in it"
                        : "Save your changes first; a run uses the saved recipe"
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
              others={stepOthers}
              onOpen={setOpenUid}
              onChange={updateStep}
              onMove={moveStep}
              onRemove={removeStep}
              onDuplicate={duplicateStep}
              onChangeMany={changeMany}
              onSaveGroup={(groupName, uids) => {
                setTemplateDraft({ name: groupName, steps: stored(steps.filter((step) => uids.includes(step.uid))) });
                setManaging("template");
              }}
              onComment={
                saved
                  ? (uid) => {
                      setCommentStep(uid);
                      setDetailsOpen(true);
                    }
                  : null
              }
              savedStepIds={savedStepIds}
              onAdd={() => openPalette()}
              onTemplates={datasetId ? () => setTemplatesOpen(true) : null}
              problem={problem}
              tools={catalogue.items}
              columns={settingsColumns}
              datasets={datasets.filter((item) => item.id !== datasetId).map((item) => ({ id: item.id, name: item.name }))}
            />
          </div>

          <section data-tour="studio-preview" aria-label="Preview" className="flex min-w-0 flex-1 flex-col p-3">
            {editing.resetReason ? (
              <div
                role="status"
                className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl border border-info-line bg-info-soft px-3 py-2 text-[13px] text-info"
              >
                <Icon name="info" size={15} className="shrink-0" />
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{editing.resetReason}</span> It now shows the saved recipe.
                </span>
                <span className="flex shrink-0 gap-1.5">
                  {editing.setAside ? (
                    <Button
                      size="sm"
                      onClick={() => {
                        const kept = editing.setAside;
                        if (kept) editing.replaceWith(kept.name || name, kept.steps);
                        editing.clearSetAside();
                        editing.clearResetReason();
                      }}
                    >
                      Bring back my steps
                    </Button>
                  ) : null}
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      editing.clearSetAside();
                      editing.clearResetReason();
                    }}
                  >
                    Dismiss
                  </Button>
                </span>
              </div>
            ) : null}
            {live && !editing.connected ? (
              <div role="status" className="mb-2 flex items-start gap-2 rounded-xl border border-warning-line bg-warning-soft px-3 py-2 text-[13px] text-warning">
                <Icon name="warning" size={15} className="mt-0.5 shrink-0" />
                The server is not answering. Your changes are kept here and sent when it does.
              </div>
            ) : null}
            {suggesting && !dirty ? (
              <div className="mb-2 flex items-start gap-2 rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink-2">
                <Icon name="info" size={15} className="mt-0.5 shrink-0" />
                <span>
                  {!canEdit
                    ? "Try changes here; Suggest sends them to someone who may edit this recipe."
                    : "Changes in this project need approval: Suggest sends yours to be accepted or declined."}
                </span>
              </div>
            ) : null}
            {canEdit && saved && editing.shared?.openSuggestions ? (
              <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl border border-info-line bg-info-soft px-3 py-2 text-[13px] text-info">
                <Icon name="mail" size={15} className="shrink-0" />
                <span className="min-w-0 flex-1 font-medium">
                  {countOf(editing.shared.openSuggestions, "suggestion")} waiting for this recipe.
                </span>
                <Button size="sm" onClick={() => setSuggestionsOpen(true)}>
                  Review
                </Button>
              </div>
            ) : null}
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

            {resultContract ? (
              <ContractNotice
                projectId={projectId}
                contract={resultContract}
                missing={preview && !loading && !error ? missingPromised(resultContract.terms, preview.preview_columns) : []}
              />
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
                        {formatCount(preview.row_count_before)} → {countOf(preview.row_count_after, "row")} after
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
                  onCellMenu={(cell, at) => setPickedCell({ cell, at })}
                  stale={error !== null}
                  emptyMessage={
                    // No preview yet, or a new one on its way: not a claim
                    // about the data. Only a finished, empty result is.
                    !preview || loading
                      ? "Loading the preview…"
                      : steps.length > 0
                        ? "These steps leave no rows. Try loosening a filter."
                        : "This dataset has no rows."
                  }
                />
              )}
            </div>
          </section>

          <DetailsDrawer
            open={detailsOpen}
            onClose={() => setDetailsOpen(false)}
            columns={preview?.schema_after.columns ?? []}
            plan={plan}
            counted={error ? undefined : preview?.step_outcomes}
            runs={
              saved
                ? {
                    projectId,
                    recipeId: saved.id,
                    mode: eachRun.mode,
                    column: eachRun.column,
                    inputColumns: preview?.schema_before.ordered_columns ?? [],
                    canChange: role === null ? true : role === "editor" || role === "admin",
                    onChanged: (mode, column) => setEachRun({ mode, column }),
                  }
                : null
            }
            steps={stored(steps)}
            discussion={
              saved
                ? {
                    projectId,
                    recipeId: saved.id,
                    currentUsername: currentUser.username,
                    step: commentStep && stepNames[commentStep] ? { id: commentStep, label: stepNames[commentStep] } : null,
                    onClearStep: () => setCommentStep(null),
                    stepNames,
                  }
                : null
            }
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
      {pickedCell ? (
        <CellFilterMenu
          cell={pickedCell.cell}
          at={pickedCell.at}
          onClose={() => setPickedCell(null)}
          onPick={(config) => {
            addTool(config);
            setPickedCell(null);
          }}
        />
      ) : null}
      <SaveTemplateDialog
        open={managing === "template"}
        onClose={() => {
          setManaging(null);
          setTemplateDraft(null);
        }}
        projectId={projectId}
        steps={templateDraft?.steps ?? stored(steps)}
        initialName={templateDraft?.name ?? ""}
        onSaved={(templateName) => toast.success(`Saved “${templateName}”`, "It is under Start from a template, for anyone in this project.")}
      />
      <ParametersDialog
        open={managing === "parameters"}
        onClose={() => setManaging(null)}
        projectId={projectId}
        recipeId={saved?.id ?? null}
        parameters={parameters}
        used={usedNames}
        onSaved={(next) => {
          setParameters(next);
          // A value being tried for a parameter that is gone would only be refused.
          setTryValues((current) =>
            Object.fromEntries(Object.entries(current).filter(([key]) => next.some((item) => item.name === key))),
          );
          toast.success("Parameters saved", saved ? "Each run takes these values, or the ones it is given." : "They are saved with the recipe.");
        }}
      />
      <RunWithValuesDialog
        open={managing === "run-values" || managing === "preview-values"}
        onClose={() => setManaging(null)}
        purpose={managing === "preview-values" ? "preview" : "run"}
        parameters={parameters}
        current={managing === "preview-values" ? tryValues : {}}
        onRun={(values) => (managing === "preview-values" ? setTryValues(values) : void run(values))}
      />
      {saved && parentRecipe ? (
        <MergeDialog
          open={managing === "merge"}
          onClose={() => setManaging(null)}
          projectId={projectId}
          branchId={saved.id}
          parentId={parentRecipe.id}
          parentName={parentRecipe.name}
          onMerged={(message) => toast.success(`Merged into ${parentRecipe.name}`, message)}
        />
      ) : null}
      <CompareDialog
        open={managing === "compare"}
        onClose={() => setManaging(null)}
        projectId={projectId}
        current={{ name, steps: stored(steps) }}
        currentId={saved?.id ?? null}
      />
      {saved ? (
        <>
          <CopyDialog
            open={managing === "copy"}
            onClose={() => setManaging(null)}
            projectId={projectId}
            recipeId={saved.id}
            datasets={datasets.filter((item) => item.id !== datasetId).map((item) => ({ id: item.id, name: item.name }))}
          />
          <SplitDialog
            open={managing === "split"}
            onClose={() => setManaging(null)}
            projectId={projectId}
            recipeId={saved.id}
            columns={baseColumns.map((column) => column.name)}
          />
        </>
      ) : null}
      {saved && suggesting ? (
        <SuggestDialog
          open={suggestOpen}
          onClose={() => setSuggestOpen(false)}
          onSent={() => {
            setSuggestOpen(false);
            toast.success("Suggestion sent", "Someone who may edit this recipe will accept or decline it; you will hear which.");
            if (!live && editing.saved) {
              // The suggestion holds the changes now; this copy goes back to the saved recipe.
              editing.replaceWith(editing.saved.name, editing.saved.steps);
              clearDraft(key);
            }
          }}
          projectId={projectId}
          recipeId={saved.id}
          saved={{ name: editing.saved?.name ?? name, steps: stored(editing.saved?.steps ?? []) }}
          proposed={{ name, steps: stored(steps) }}
          reason={suggestReason}
        />
      ) : null}
      {saved && canEdit ? (
        <SuggestionsDrawer
          open={suggestionsOpen}
          onClose={() => setSuggestionsOpen(false)}
          onDecided={() => void editing.refresh()}
          projectId={projectId}
          recipeId={saved.id}
          currentUsername={currentUser.username}
        />
      ) : null}
      <Modal
        open={discarding}
        onClose={() => setDiscarding(false)}
        title="Discard the unsaved changes?"
        description="The recipe goes back to how it was last saved, for everyone editing it. This cannot be undone."
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setDiscarding(false)}>
              Keep them
            </Button>
            <Button variant="danger" size="sm" onClick={() => void discardUnsaved()}>
              Discard them
            </Button>
          </div>
        }
      >
        <p className="text-sm text-ink-2">Anyone with the recipe open sees the saved version straight away.</p>
      </Modal>

      </SampleValuesProvider>
      </OtherDatasetsProvider>
    </AppFrame>
  );
}

/** "14:05 today", or "3 Oct, 14:05" for an older draft. */
function draftTime(at: number): string {
  const when = new Date(at);
  const time = formatTime(when);
  return when.toDateString() === new Date().toDateString() ? `${time} today` : `${formatShortDate(when)}, ${time}`;
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

function ContractNotice({
  projectId,
  contract,
  missing,
}: {
  projectId: string;
  contract: DataContract;
  missing: string[];
}) {
  const href = `/projects/${projectId}/datasets/${contract.dataset_id}/contract`;
  if (missing.length === 0) {
    return (
      <div className="mb-2 flex items-start gap-2 rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink-2">
        <Icon name="contract" size={14} className="mt-0.5 shrink-0" />
        <span>
          The result goes to {contract.dataset_name}, which has a{" "}
          <Link href={href} className="underline">
            contract
          </Link>
          . Every run is checked against it.
        </span>
      </div>
    );
  }
  return (
    <div role="status" className="mb-2 flex items-start gap-2 rounded-xl border border-warning-line bg-warning-soft px-3 py-2 text-[13px] text-warning">
      <Icon name="contract" size={14} className="mt-0.5 shrink-0" />
      <span>
        The result no longer has {missing.join(", ")}, which the{" "}
        <Link href={href} className="underline">
          contract on {contract.dataset_name}
        </Link>{" "}
        promises.{" "}
        {contract.enforcement === "stop"
          ? "Running this recipe will be stopped, and the current data kept."
          : "Running it will save the result and record a problem."}
      </span>
    </div>
  );
}
