"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import type { AuthUser, DatasetRecord } from "@platform/shared-types";

import { DataGrid, type GridColumn } from "@/features/studio/grid/data-grid";
import {
  sortFromSteps,
  sortStepConfig,
  type SortDirection,
} from "@/features/studio/grid/column-state";
import { AppFrame } from "@/components/shell/app-frame";
import type { Command } from "@/components/shell/command-palette";
import type { RibbonGroup } from "@/components/shell/ribbon";
import { useToast } from "@/components/providers/toast-provider";
import { STUDIO_TOUR_ID, studioTour } from "@/components/tour/tours";
import { useTour } from "@/components/tour/tour-provider";
import { Icon } from "@/components/ui/icon";
import { StepEditor } from "@/features/studio/step-editor";
import {
  STEP_BY_TYPE,
  STEP_CATALOG,
  STEP_GROUPS,
  type StepDefinition,
} from "@/features/studio/step-catalog";
import { RecipeYamlPanel } from "@/features/studio/recipe-yaml-panel";
import { ColumnMenu } from "@/features/studio/tools/column-menu";
import { ToolBrowser } from "@/features/studio/tools/tool-browser";
import {
  describeToolStep,
  ToolStepEditor,
} from "@/features/studio/tools/tool-step-editor";
import {
  toolsForColumn,
  type Tool,
  type ToolCatalogue,
} from "@/features/studio/tools/tool-catalogue";
import { friendlyStepMessage, typeLabel } from "@/lib/labels";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
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
  execution_plan?: {
    source_type: string;
    surface: string;
    pushed_steps: number;
    local_steps: number;
    sql?: string | null;
    placements: { node: string; pushed: boolean; reason: string }[];
    note?: string;
  } | null;
  step_outcomes?: {
    index: number;
    step_type: string;
    rows_before: number;
    rows_after: number;
    columns_before: number;
    columns_after: number;
  }[];
  warnings: string[];
};

type AppliedStep = {
  /** Stable key for list rendering and reordering. */
  uid: string;
  step_type: string;
  config: Record<string, unknown>;
};

type StudioPageProps = {
  currentUser: AuthUser;
  projectId: string;
  projectName: string;
  datasets: DatasetRecord[];
  initialDatasetId?: string;
};

let uidCounter = 0;
const nextUid = () => `step-${++uidCounter}`;

export function StudioPage({
  currentUser,
  projectId,
  projectName,
  datasets,
  initialDatasetId,
}: StudioPageProps) {
  const router = useRouter();
  const toast = useToast();
  const { startIfUnseen } = useTour();

  const [datasetId, setDatasetId] = useState(initialDatasetId ?? datasets[0]?.id ?? "");
  const [steps, setSteps] = useState<AppliedStep[]>([]);
  const [selectedUid, setSelectedUid] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  /**
   * Columns of the untransformed source. Held separately so the step editor
   * still offers real column names while the current step is half-configured
   * and the live preview is therefore failing.
   */
  const [baseColumns, setBaseColumns] = useState<string[]>([]);

  const dataset = useMemo(
    () => datasets.find((item) => item.id === datasetId) ?? null,
    [datasets, datasetId],
  );

  const selected = useMemo(
    () => steps.find((step) => step.uid === selectedUid) ?? null,
    [steps, selectedUid],
  );

  useEffect(() => {
    const timer = setTimeout(() => startIfUnseen(studioTour, STUDIO_TOUR_ID), 1200);
    return () => clearTimeout(timer);
  }, [startIfUnseen]);

  // Preview is debounced and generation-guarded: rapid edits cancel earlier
  // results so a slow response cannot overwrite a newer one.
  const generation = useRef(0);

  const runPreview = useCallback(
    async (activeSteps: AppliedStep[], activeDatasetId: string) => {
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
          {
            method: "POST",
            body: JSON.stringify({
              steps: activeSteps.map((step) => ({ step_type: step.step_type, config: step.config })),
            }),
          },
        );
        if (ticket === generation.current) setPreview(response);
      } catch (caught) {
        if (ticket === generation.current) {
          setError(extractErrorMessage(caught));
          // The last good preview is KEPT. A step is added before it is
          // configured, so the first request after every single "add step"
          // fails -- and discarding the preview made the data vanish at exactly
          // the moment somebody needed to look at it to configure the step.
          // The grid stays, marked stale, until a request succeeds.
        }
      } finally {
        if (ticket === generation.current) setLoading(false);
      }
    },
    [projectId],
  );

  useEffect(() => {
    const timer = setTimeout(() => runPreview(steps, datasetId), 320);
    return () => clearTimeout(timer);
  }, [steps, datasetId, runPreview]);

  // Read the source shape once per dataset, independent of the applied steps.
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
        if (!cancelled) setBaseColumns(response.preview_columns);
      })
      .catch(() => {
        if (!cancelled) setBaseColumns([]);
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId, projectId]);

  // ------------------------------------------------------------- tool library
  //
  // Fetched once and held: the catalogue is a property of the platform, and
  // re-fetching it per keystroke is what makes a palette feel slow.
  const [catalogue, setCatalogue] = useState<ToolCatalogue>({ categories: [], items: [] });
  const [browserOpen, setBrowserOpen] = useState(false);
  const [browserColumn, setBrowserColumn] = useState<string | null>(null);
  const [restrictToType, setRestrictToType] = useState(false);
  const [columnMenu, setColumnMenu] = useState<
    { column: string; at: { x: number; y: number } } | null
  >(null);
  //: Chosen from the context menu; the browser opens with it already selected.
  const [pendingTool, setPendingTool] = useState<string | null>(null);
  //: The recipe as code. Both directions, which is what makes it reviewable.
  const [yamlOpen, setYamlOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiFetch<ToolCatalogue>("/transformations/tools")
      .then((response) => {
        if (!cancelled) setCatalogue(response);
      })
      .catch(() => {
        // The ribbon's built-in steps still work without it; the tool browser
        // says so rather than opening empty.
        if (!cancelled) setCatalogue({ categories: [], items: [] });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const addToolStep = useCallback((config: Record<string, unknown>) => {
    setSteps((current) => [
      ...current,
      { uid: nextUid(), step_type: "tool", config },
    ]);
    setBrowserOpen(false);
    setColumnMenu(null);
  }, []);

  const addStep = useCallback((definition: StepDefinition) => {
    const step: AppliedStep = {
      uid: nextUid(),
      step_type: definition.type,
      config: { ...(definition.defaults ?? {}) },
    };
    setSteps((current) => [...current, step]);
    setSelectedUid(step.uid);
  }, []);

  /**
   * A header sort is a STEP, not a view operation.
   *
   * The grid holds a page of rows, so sorting what is loaded would order a
   * sample and present it as the order of the table. Replacing the existing
   * sort rather than stacking another keeps the header and the pipeline
   * telling the same story -- two sort_rows steps would show one arrow and
   * apply the other.
   */
  const sort = useMemo(() => sortFromSteps(steps), [steps]);

  const handleSortChange = useCallback(
    (next: { column: string; direction: SortDirection } | null) => {
      setSteps((current) => {
        const withoutSort = current.filter((step) => step.step_type !== "sort_rows");
        if (next === null) return withoutSort;
        const { config } = sortStepConfig(next);
        return [...withoutSort, { uid: nextUid(), step_type: "sort_rows", config }];
      });
    },
    []
  );

  const updateStep = (uid: string, config: Record<string, unknown>) =>
    setSteps((current) => current.map((step) => (step.uid === uid ? { ...step, config } : step)));

  const removeStep = (uid: string) => {
    setSteps((current) => current.filter((step) => step.uid !== uid));
    setSelectedUid((current) => (current === uid ? null : current));
  };

  const moveStep = (uid: string, direction: -1 | 1) => {
    setSteps((current) => {
      const index = current.findIndex((step) => step.uid === uid);
      const target = index + direction;
      if (index === -1 || target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  };

  const savePipeline = useCallback(async () => {
    if (!dataset || steps.length === 0) return;
    setSaving(true);
    try {
      const created = await apiFetch<{ id: string; name: string }>(
        `/projects/${projectId}/datasets/${dataset.id}/pipelines`,
        {
          method: "POST",
          body: JSON.stringify({
            name: `${dataset.name} · ${steps.length} step${steps.length === 1 ? "" : "s"}`,
            steps_json: steps.map((step) => ({ step_type: step.step_type, config: step.config })),
          }),
        },
      );
      toast.notify({
        tone: "success",
        title: "Pipeline saved",
        description: `“${created.name}” is ready to run or schedule.`,
        actions: [
          {
            label: "Run now",
            onClick: () => {
              void apiFetch(`/projects/${projectId}/pipelines/${created.id}/run`, {
                method: "POST",
              })
                .then(() => toast.info("Run started", "Watch it under the project’s runs."))
                .catch((caught) => toast.error("Could not start the run", extractErrorMessage(caught)));
            },
          },
          {
            label: "Schedule",
            onClick: () => router.push(`/projects/${projectId}/schedules?new=1`),
          },
        ],
      });
      router.refresh();
    } catch (caught) {
      toast.error("Could not save pipeline", extractErrorMessage(caught));
    } finally {
      setSaving(false);
    }
  }, [dataset, steps, projectId, toast, router]);

  // Columns come from the live preview so they reflect the steps applied so far.
  const columns = useMemo<GridColumn[]>(() => {
    if (!preview) return [];
    // Prefer the canonical type: `decimal(18,2)` and `timestamp(6,tz)` say
    // things the seven-word vocabulary cannot, and the header glyph shows them.
    const types = new Map(
      preview.schema_after.columns.map((c) => [c.name, c.canonical_type ?? c.inferred_type])
    );
    return preview.preview_columns.map((name) => ({ name, type: types.get(name) }));
  }, [preview]);

  /**
   * Column names offered to the step editor.
   *
   * The live preview reflects every applied step, so it is the most accurate
   * source when it succeeds. While a step is mid-configuration the preview
   * fails, and falling back to the source columns keeps real names on offer
   * instead of dropping the user into a free-text box.
   */
  const columnsForSelected = useMemo(() => {
    const fromPreview = preview?.preview_columns ?? [];
    const merged = new Set([...fromPreview, ...baseColumns]);
    return Array.from(merged);
  }, [preview, baseColumns]);

  const ribbon = useMemo<RibbonGroup[]>(
    () => [
      {
        id: "pipeline",
        label: "Pipeline",
        actions: [
          {
            id: "save",
            label: "Save",
            icon: "check",
            prominent: true,
            disabled: steps.length === 0 || saving || !dataset,
            onClick: savePipeline,
          },
          {
            id: "tools",
            label: `All tools${catalogue.items.length ? ` (${catalogue.items.length})` : ""}`,
            icon: "sparkles",
            prominent: true,
            hint: "Search the whole library — or right-click a column header",
            disabled: !dataset || catalogue.items.length === 0,
            onClick: () => {
              setBrowserColumn(null);
              setRestrictToType(false);
              setBrowserOpen(true);
            },
          },
          {
            id: "yaml",
            label: yamlOpen ? "Hide YAML" : "As YAML",
            icon: "book",
            hint: "Edit the recipe as a file, or keep it in git",
            disabled: !dataset,
            onClick: () => setYamlOpen((current) => !current),
          },
          {
            id: "clear",
            label: "Clear",
            icon: "trash",
            disabled: steps.length === 0,
            onClick: () => {
              setSteps([]);
              setSelectedUid(null);
            },
          },
        ],
      },
      ...STEP_GROUPS.map((group) => ({
        id: group.toLowerCase(),
        label: group,
        actions: STEP_CATALOG.filter((step) => step.group === group).map((step) => ({
          id: step.type,
          label: step.label,
          icon: step.icon,
          disabled: !dataset,
          onClick: () => addStep(step),
        })),
      })),
    ],
    [steps.length, saving, dataset, addStep, savePipeline, catalogue.items.length, yamlOpen],
  );

  const rowDelta = preview ? preview.row_count_after - preview.row_count_before : 0;

  // A freshly added step is unconfigured by definition; that is guidance, not a
  // failure, so it is presented differently from a genuine execution error.
  const incomplete =
    error !== null &&
    /cannot be empty|missing required field|must be a non-empty|is required/i.test(error);

  /**
   * Every tool, in the command palette.
   *
   * The palette caps its results, so adding a hundred and sixty-seven entries
   * costs nothing on screen and makes Ctrl+K the fastest way to reach any of
   * them -- which is the point of a library this size.
   */
  const toolCommands = useMemo<Command[]>(
    () =>
      catalogue.items.map((tool) => ({
        id: `tool:${tool.name}`,
        label: tool.title,
        group: tool.category,
        icon: "sparkles" as const,
        hint: tool.summary,
        keywords: [tool.name.replace(/[._]/g, " "), ...tool.synonyms].join(" "),
        run: () => {
          setBrowserColumn(null);
          setRestrictToType(false);
          setPendingTool(tool.name);
          setBrowserOpen(true);
        },
      })),
    [catalogue.items],
  );

  const menuColumn = columnMenu
    ? columns.find((entry) => entry.name === columnMenu.column)
    : undefined;

  return (
    <AppFrame
      currentUser={currentUser}
      crumbs={[
        { label: "Projects", href: "/projects" },
        { label: projectName, href: `/projects/${projectId}` },
        { label: "Studio" },
      ]}
      ribbon={ribbon}
      commands={toolCommands}
      disableWelcomeTour
      statusItems={[
        { id: "dataset", label: "Source", value: dataset?.name ?? "none" },
        { id: "steps", label: "Steps", value: String(steps.length) },
        {
          id: "rows",
          label: "Rows",
          value: preview ? preview.row_count_after.toLocaleString() : "—",
          tone: rowDelta < 0 ? "warn" : "neutral",
        },
        {
          id: "cols",
          label: "Columns",
          value: preview ? String(preview.column_count_after) : "—",
        },
      ]}
      health={{ label: loading ? "Computing preview" : "Preview current", healthy: !error }}
      inspector={{
        title: yamlOpen ? "Recipe as code" : selected ? "Step settings" : "Inspector",
        content: yamlOpen ? (
          <RecipeYamlPanel
            steps={steps.map((step) => ({ step_type: step.step_type, config: step.config }))}
            onApply={(next) => {
              setSteps(
                next.map((step) => ({
                  uid: nextUid(),
                  step_type: step.step_type,
                  config: step.config,
                })),
              );
              setSelectedUid(null);
              toast.success("Recipe updated", "The steps now match the file.");
            }}
            onClose={() => setYamlOpen(false)}
          />
        ) : selected ? (
          selected.step_type === "tool" ? (
            <ToolStepEditor
              config={selected.config}
              tools={catalogue.items}
              columns={columns.length ? columns : columnsForSelected.map((name) => ({ name }))}
              onChange={(config) => updateStep(selected.uid, config)}
            />
          ) : (
            <StepEditor
              definition={STEP_BY_TYPE.get(selected.step_type)!}
              config={selected.config}
              columns={columnsForSelected}
              datasets={datasets
                .filter((item) => item.id !== datasetId)
                .map((item) => ({ id: item.id, name: item.name }))}
              onChange={(config) => updateStep(selected.uid, config)}
            />
          )
        ) : (
          <InspectorIdle dataset={dataset} preview={preview} />
        ),
      }}
    >
      <div className="flex h-full min-h-0">
        {/* Applied steps */}
        <div
          data-tour="applied-steps"
          className="flex w-[260px] shrink-0 flex-col border-r border-line bg-[color:var(--panel)]"
        >
          <div className="flex h-10 items-center justify-between border-b border-line px-3">
            <span className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted">
              Applied steps
            </span>
            {steps.length > 0 ? (
              <span className="tabular rounded-full bg-surface-2 px-1.5 py-0.5 text-[10px] text-ink-3">
                {steps.length}
              </span>
            ) : null}
          </div>

          <div data-tour="studio-source" className="border-b border-line p-3">
            <label
              htmlFor="studio-dataset"
              className="mb-1.5 block text-[11px] font-medium text-ink-3"
            >
              Source dataset
            </label>
            <select
              id="studio-dataset"
              value={datasetId}
              onChange={(event) => {
                setDatasetId(event.target.value);
                setSteps([]);
                setSelectedUid(null);
              }}
              className="h-9 w-full rounded-lg border border-line bg-sunken px-2.5 text-[13px] text-ink outline-none focus:border-[color:var(--accent)]"
            >
              {datasets.length === 0 ? <option value="">No datasets yet</option> : null}
              {datasets.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>

          <ol className="flex-1 overflow-y-auto p-2">
            {steps.length === 0 ? (
              <li className="px-2 py-8 text-center text-[12px] leading-5 text-muted">
                Pick a tool from the ribbon above to add your first step.
              </li>
            ) : (
              steps.map((step, index) => {
                const definition = STEP_BY_TYPE.get(step.step_type);
                // A tool step has no entry in the built-in catalogue: its name
                // and icon come from the library instead, or the list would
                // read "tool" a hundred times over.
                const asTool =
                  step.step_type === "tool"
                    ? describeToolStep(step.config, catalogue.items)
                    : null;
                const active = step.uid === selectedUid;
                return (
                  <li key={step.uid}>
                    <div
                      className={cx(
                        "group mb-1 flex items-center gap-2 rounded-lg border px-2 py-2 transition duration-[var(--duration-fast)]",
                        active
                          ? "border-[color:var(--accent-soft)] bg-[color:var(--accent-faint)]"
                          : "border-transparent hover:bg-surface",
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => setSelectedUid(active ? null : step.uid)}
                        className="flex min-w-0 flex-1 items-center gap-2 text-left"
                      >
                        <span className="tabular w-4 shrink-0 text-[10px] text-muted">
                          {index + 1}
                        </span>
                        <Icon
                          name={definition?.icon ?? (asTool ? "sparkles" : "transform")}
                          size={14}
                          className={active ? "text-ink" : "text-ink-3"}
                        />
                        <span
                          className={cx(
                            "truncate text-[12px]",
                            active ? "text-ink" : "text-ink-2",
                          )}
                        >
                          {asTool ? asTool.label : (definition?.label ?? step.step_type)}
                          {asTool?.detail ? (
                            <span className="text-ink-3"> · {asTool.detail}</span>
                          ) : null}
                        </span>
                        {/* What this step actually did. A step whose effect is
                            invisible is a step nobody can debug. */}
                        <StepDelta outcome={preview?.step_outcomes?.[index]} />
                      </button>
                      <div className="flex shrink-0 items-center opacity-0 transition group-hover:opacity-100">
                        <button
                          type="button"
                          onClick={() => moveStep(step.uid, -1)}
                          disabled={index === 0}
                          aria-label="Move step up"
                          className="rounded p-0.5 text-muted transition hover:text-ink disabled:opacity-25"
                        >
                          <Icon name="chevronDown" size={12} className="rotate-180" />
                        </button>
                        <button
                          type="button"
                          onClick={() => moveStep(step.uid, 1)}
                          disabled={index === steps.length - 1}
                          aria-label="Move step down"
                          className="rounded p-0.5 text-muted transition hover:text-ink disabled:opacity-25"
                        >
                          <Icon name="chevronDown" size={12} />
                        </button>
                        <button
                          type="button"
                          onClick={() => removeStep(step.uid)}
                          aria-label="Remove step"
                          className="rounded p-0.5 text-muted transition hover:text-danger"
                        >
                          <Icon name="close" size={12} />
                        </button>
                      </div>
                    </div>
                  </li>
                );
              })
            )}
          </ol>
        </div>

        {/* Preview canvas */}
        <div data-tour="studio-preview" className="flex min-w-0 flex-1 flex-col p-4">
          {error ? (
            <div
              className={cx(
                "mb-3 flex items-start gap-2.5 rounded-xl border px-3.5 py-2.5 text-[13px]",
                incomplete
                  ? "border-info-line bg-info-soft text-info"
                  : "border-danger-line bg-danger-soft text-danger",
              )}
            >
              <Icon name={incomplete ? "info" : "warning"} size={15} className="mt-0.5 shrink-0" />
              <div>
                <div className="font-medium">
                  {incomplete ? "Finish setting up this step" : "This step cannot run"}
                </div>
                <div className="mt-0.5 text-[12px] opacity-90">{friendlyStepMessage(error)}</div>
              </div>
            </div>
          ) : null}

          {preview && preview.warnings.length > 0 ? (
            <div className="mb-3 rounded-xl border border-warning-line bg-warning-soft px-3.5 py-2.5 text-[12px] text-warning">
              {preview.warnings.map((warning) => (
                <div key={warning} className="flex items-start gap-2">
                  <Icon name="info" size={13} className="mt-0.5 shrink-0 opacity-80" />
                  {warning}
                </div>
              ))}
            </div>
          ) : null}

          {preview?.execution_plan ? (
            <ExecutionPlanStrip plan={preview.execution_plan} />
          ) : null}

          <div className="mb-3 flex flex-wrap items-center gap-3">
            <Metric label="Rows" value={preview ? preview.row_count_after.toLocaleString() : "—"} delta={rowDelta} />
            <Metric
              label="Columns"
              value={preview ? String(preview.column_count_after) : "—"}
              delta={preview ? preview.column_count_after - preview.column_count_before : 0}
            />
            {loading ? (
              <span className="flex items-center gap-1.5 text-[11px] text-muted">
                <span className="h-1.5 w-1.5 animate-live rounded-full bg-[color:var(--accent)]" />
                Recomputing
              </span>
            ) : null}
          </div>

          <div className={cx("min-h-0 flex-1 transition-opacity", loading && "opacity-60")}>
            {datasets.length === 0 ? (
              <EmptyState
                title="No datasets in this project yet"
                body="Upload a file or run an extraction job, then come back to shape the data here."
              />
            ) : (
              <DataGrid
                columns={columns}
                rows={preview?.preview_rows ?? []}
                sort={sort}
                onSortChange={handleSortChange}
                onColumnMenu={(column, at) => setColumnMenu({ column, at })}
                stale={error !== null}
                emptyMessage={
                  steps.length > 0
                    ? "These steps produced no rows. Try relaxing a filter."
                    : "Loading preview…"
                }
              />
            )}
          </div>
        </div>
      </div>

      {columnMenu ? (
        <ColumnMenu
          column={columnMenu.column}
          columnType={menuColumn?.type}
          tools={toolsForColumn(catalogue.items, menuColumn?.type)}
          at={columnMenu.at}
          onPick={(tool: Tool) => {
            setBrowserColumn(columnMenu.column);
            setRestrictToType(true);
            setColumnMenu(null);
            setBrowserOpen(true);
            setPendingTool(tool.name);
          }}
          onBrowseAll={() => {
            setBrowserColumn(columnMenu.column);
            setRestrictToType(true);
            setColumnMenu(null);
            setBrowserOpen(true);
          }}
          onClose={() => setColumnMenu(null)}
        />
      ) : null}

      {browserOpen ? (
        <ToolBrowser
          tools={catalogue.items}
          categories={catalogue.categories}
          columns={columns.map((entry) => ({ name: entry.name, type: entry.type }))}
          initialColumn={browserColumn}
          restrictToColumnType={restrictToType}
          preselect={pendingTool}
          sampleRows={preview?.preview_rows ?? []}
          onAdd={addToolStep}
          onClose={() => {
            setBrowserOpen(false);
            setPendingTool(null);
          }}
        />
      ) : null}
    </AppFrame>
  );
}

function Metric({ label, value, delta }: { label: string; value: string; delta: number }) {
  return (
    <div className="flex items-baseline gap-2 rounded-lg border border-line bg-surface px-3 py-1.5">
      <span className="text-[10px] uppercase tracking-[0.16em] text-muted">{label}</span>
      <span className="tabular text-[15px] font-semibold text-ink">{value}</span>
      {delta !== 0 ? (
        <span
          className={cx(
            "tabular text-[11px]",
            delta > 0 ? "text-success" : "text-warning",
          )}
        >
          {delta > 0 ? "+" : ""}
          {delta.toLocaleString()}
        </span>
      ) : null}
    </div>
  );
}

function InspectorIdle({
  dataset,
  preview,
}: {
  dataset: DatasetRecord | null;
  preview: PreviewResponse | null;
}) {
  if (!dataset) {
    return <p className="text-[12px] leading-5 text-muted">Select a dataset to begin.</p>;
  }
  return (
    <div className="space-y-4">
      <div>
        <div className="text-[11px] uppercase tracking-[0.16em] text-muted">Dataset</div>
        <div className="mt-1 text-[13px] font-medium text-ink">{dataset.name}</div>
        <div className="mt-0.5 text-[11px] text-muted">
          {dataset.row_count?.toLocaleString() ?? "?"} rows · {dataset.column_count ?? "?"} columns
        </div>
      </div>
      {preview ? (
        <div>
          <div className="mb-1.5 text-[11px] uppercase tracking-[0.16em] text-muted">
            Output schema
          </div>
          <ul className="space-y-1">
            {preview.schema_after.columns.map((column) => (
              <li
                key={column.name}
                className="flex items-center justify-between gap-2 rounded-md bg-surface px-2 py-1.5"
              >
                <span className="truncate text-[12px] text-ink">{column.name}</span>
                <span
                  className="shrink-0 text-[10.5px] text-muted"
                  title={column.canonical_type ?? column.inferred_type}
                >
                  {typeLabel(column.canonical_type ?? column.inferred_type)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="text-[11px] leading-5 text-muted">
        Select a step on the left to edit its settings here.
      </p>
    </div>
  );
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center rounded-xl border border-dashed border-line px-6 text-center">
      <Icon name="table" size={26} className="text-muted" />
      <h3 className="mt-3 text-[14px] font-medium text-ink-2">{title}</h3>
      <p className="mt-1.5 max-w-sm text-[12px] leading-5 text-muted">{body}</p>
    </div>
  );
}

/**
 * The row and column change one step made.
 *
 * Silent when a step changed nothing, so the panel draws attention to the steps
 * that did something rather than to a column of zeroes.
 */
function StepDelta({
  outcome,
}: {
  outcome?: { rows_before: number; rows_after: number; columns_before: number; columns_after: number };
}) {
  if (!outcome) return null;
  const rows = outcome.rows_after - outcome.rows_before;
  const columns = outcome.columns_after - outcome.columns_before;
  if (rows === 0 && columns === 0) return null;

  const parts: string[] = [];
  if (rows !== 0) parts.push(`${rows > 0 ? "+" : ""}${rows.toLocaleString()} rows`);
  if (columns !== 0) parts.push(`${columns > 0 ? "+" : ""}${columns} cols`);

  return (
    <span
      className={cx(
        "tabular ml-auto shrink-0 pl-2 text-[10.5px]",
        rows < 0 || columns < 0 ? "text-warning" : "text-muted",
      )}
      title={`${outcome.rows_before.toLocaleString()} → ${outcome.rows_after.toLocaleString()} rows`}
    >
      {parts.join(" · ")}
    </span>
  );
}

/**
 * Where the work would happen on a full run against this dataset's source.
 *
 * Labelled carefully: a preview always reads the materialised file, so this
 * describes the *run*, not what just happened. "Nothing pushes down, because
 * this is a stored file" is the useful answer -- it is the reason a pipeline
 * over a hundred million rows would be slow, and it is invisible otherwise.
 */
function ExecutionPlanStrip({
  plan,
}: {
  plan: {
    source_type: string;
    surface: string;
    pushed_steps: number;
    local_steps: number;
    sql?: string | null;
    placements: { node: string; pushed: boolean; reason: string }[];
    note?: string;
  };
}) {
  const [open, setOpen] = useState(false);
  const pushes = plan.pushed_steps > 1; // a bare scan is not pushdown

  return (
    <div className="mb-3 rounded-xl border border-line bg-surface">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 px-3.5 py-2 text-left"
      >
        <Icon
          name={pushes ? "activity" : "info"}
          size={14}
          className={pushes ? "text-success" : "text-ink-3"}
        />
        <span className="text-[12px] text-ink">
          {pushes
            ? `${plan.pushed_steps} step${plan.pushed_steps === 1 ? "" : "s"} would run in ${plan.source_type}`
            : `All steps will run in Pipewright — a ${plan.source_type} source cannot run them at the source`}
        </span>
        {plan.local_steps > 0 ? (
          <span className="tabular text-[11px] text-muted">
            {plan.local_steps} local
          </span>
        ) : null}
        <Icon
          name="chevronDown"
          size={12}
          className={cx("ml-auto text-muted transition", open && "rotate-180")}
        />
      </button>

      {open ? (
        <div className="border-t border-line px-3.5 py-2.5">
          {plan.note ? <p className="mb-2 text-[11.5px] text-muted">{plan.note}</p> : null}
          <ul className="grid gap-1">
            {plan.placements.map((placement, index) => (
              <li key={`${placement.node}-${index}`} className="flex items-start gap-2 text-[11.5px]">
                <span
                  className={cx(
                    "mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em]",
                    placement.pushed
                      ? "bg-success-soft text-success"
                      : "bg-surface-2 text-ink-3",
                  )}
                >
                  {placement.pushed ? "source" : "here"}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="text-ink">{placement.node}</span>
                  <span className="text-muted"> — {placement.reason}</span>
                </span>
              </li>
            ))}
          </ul>
          {plan.sql ? (
            <pre className="mt-2.5 overflow-x-auto rounded-lg bg-sunken p-2.5 text-[11px] leading-5 text-ink-2">
              {plan.sql}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

