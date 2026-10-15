"use client";

import Link from "next/link";
import { useState } from "react";

import type {
  LiveMeasure,
  LiveMeasureOp,
  LiveRecipe,
  LiveRecipeCreate,
  LiveRecipeResultsResponse,
  LiveWindow,
  LiveWindowKind,
  StreamSource,
  TransformationPipelineRecord,
} from "@platform/shared-types";
import {
  Badge,
  Button,
  FormField,
  Input,
  Modal,
  SectionPanel,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@platform/shared-ui";

import { DeleteRowButton } from "@/components/ui/delete-row-button";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { countOf, formatDateTime, formatNumber } from "@/lib/format";

import { WINDOW_LABELS, lateWords, recipeState, tableList } from "../live-words";

type LiveRecipesPanelProps = {
  projectId: string;
  feed: StreamSource;
  recipes: LiveRecipe[];
  savedRecipes: TransformationPipelineRecord[];
  datasets: { id: string; name: string }[];
  onChanged: () => Promise<void>;
};

const OPS: { op: LiveMeasureOp; label: string }[] = [
  { op: "count", label: "Count of events" },
  { op: "sum", label: "Sum" },
  { op: "average", label: "Average" },
  { op: "lowest", label: "Lowest" },
  { op: "highest", label: "Highest" },
  { op: "first", label: "First" },
  { op: "last", label: "Last" },
];

const UNITS = [
  { label: "seconds", seconds: 1 },
  { label: "minutes", seconds: 60 },
  { label: "hours", seconds: 3600 },
];

/** Live recipes on a feed: what each does, how it is keeping up, its latest windows, and a way to add one (D1, L4). */
export function LiveRecipesPanel({ projectId, feed, recipes, savedRecipes, datasets, onChanged }: LiveRecipesPanelProps) {
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, LiveRecipeResultsResponse>>({});
  const base = `/projects/${projectId}/streams/${feed.id}/recipes`;

  const act = async (action: () => Promise<unknown>) => {
    setError(null);
    try {
      await action();
      await onChanged();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    }
  };

  const showResults = async (recipe: LiveRecipe) => {
    if (results[recipe.id]) {
      setResults((current) => Object.fromEntries(Object.entries(current).filter(([id]) => id !== recipe.id)));
      return;
    }
    try {
      const shown = await apiFetch<LiveRecipeResultsResponse>(`${base}/${recipe.id}/results?limit=25`);
      setResults((current) => ({ ...current, [recipe.id]: shown }));
    } catch (caught) {
      setError(extractErrorMessage(caught));
    }
  };

  return (
    <SectionPanel
      title="Live recipes"
      description="Run on each batch as it arrives: a recipe's steps, a lookup in a dataset, and a summary by time."
      actions={
        <Button variant="secondary" size="sm" onClick={() => setAdding(true)}>
          Add a live recipe
        </Button>
      }
    >
      {error ? (
        <p role="alert" className="mb-3 rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </p>
      ) : null}
      {recipes.length === 0 ? (
        <p className="text-[14px] text-ink-3">
          None yet. A live recipe can count orders per minute by region, or add each customer&apos;s region to every event.
        </p>
      ) : (
        <ul className="space-y-3">
          {recipes.map((recipe) => {
            const state = recipeState(recipe);
            const shown = results[recipe.id];
            return (
              <li key={recipe.id} className="rounded-2xl border border-line bg-surface px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-[14px] font-semibold text-ink">{recipe.name}</h3>
                  <Badge tone={state.tone}>{state.word}</Badge>
                  <div className="ml-auto flex flex-wrap gap-2">
                    {recipe.window ? (
                      <Button variant="ghost" size="sm" onClick={() => void showResults(recipe)}>
                        {shown ? "Hide its windows" : "Show its windows"}
                      </Button>
                    ) : null}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        void act(() =>
                          apiFetch(`${base}/${recipe.id}`, {
                            method: "PATCH",
                            body: JSON.stringify({ status: recipe.status === "active" ? "paused" : "active" }),
                          }),
                        )
                      }
                    >
                      {recipe.status === "active" ? "Pause" : "Resume"}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => void act(() => apiFetch(`${base}/${recipe.id}/start-again`, { method: "POST" }))}
                    >
                      Start again
                    </Button>
                    <DeleteRowButton
                      path={`${base}/${recipe.id}`}
                      name={recipe.name}
                      kind="live recipe"
                      consequences={["Its output dataset stays, as it was last saved."]}
                      onDeleted={() => void onChanged()}
                    />
                  </div>
                </div>
                <p className="mt-1 text-[13px] text-ink-2">{recipe.description}</p>
                {recipe.window ? (
                  <p className="mt-1 text-[13px] text-ink-3">
                    {recipe.window.time_column === "received_at" ? "By when each event arrived." : `By the time in ${recipe.window.time_column}.`}{" "}
                    {lateWords(recipe.window)}
                  </p>
                ) : null}
                <p className="mt-1 text-[13px] text-ink-3">
                  {[
                    countOf(recipe.events_in, "event"),
                    recipe.window ? countOf(recipe.open_windows, "window still open", "windows still open") : null,
                    recipe.complete_up_to ? `complete up to ${formatDateTime(recipe.complete_up_to)}` : null,
                    recipe.late_dropped ? `${countOf(recipe.late_dropped, "late event")} left out` : null,
                    recipe.late_restated ? `${countOf(recipe.late_restated, "late event")} updated a window` : null,
                    recipe.without_time ? `${countOf(recipe.without_time, "event")} without a readable time` : null,
                    recipe.lookup ? `${countOf(recipe.unmatched, "event")} matched nothing` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
                {recipe.output_dataset_id ? (
                  <p className="mt-1 text-[13px]">
                    <Link
                      href={`/projects/${projectId}/datasets/${recipe.output_dataset_id}`}
                      className="text-[color:var(--accent-muted)] hover:underline"
                    >
                      {recipe.output_dataset_name ?? "Its output"}
                    </Link>
                    {recipe.last_saved_at ? <span className="text-ink-3"> · saved {formatDateTime(recipe.last_saved_at)}</span> : null}
                  </p>
                ) : (
                  <p className="mt-1 text-[13px] text-ink-3">Its output dataset is made at the feed&apos;s next save.</p>
                )}
                {recipe.last_error ? <p className="mt-1 text-[13px] text-danger">{recipe.last_error}</p> : null}
                {shown ? <ResultsTable shown={shown} /> : null}
              </li>
            );
          })}
        </ul>
      )}
      <AddLiveRecipe
        open={adding}
        onClose={() => setAdding(false)}
        path={base}
        savedRecipes={savedRecipes}
        datasets={datasets}
        onAdded={async () => {
          setAdding(false);
          await onChanged();
        }}
      />
    </SectionPanel>
  );
}

function ResultsTable({ shown }: { shown: LiveRecipeResultsResponse }) {
  if (shown.items.length === 0) return <p className="mt-3 text-[13px] text-ink-3">No windows yet.</p>;
  return (
    <div className="mt-3 overflow-x-auto">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>From</TableHeaderCell>
            <TableHeaderCell>To</TableHeaderCell>
            {shown.group_by.map((name) => (
              <TableHeaderCell key={name}>{name}</TableHeaderCell>
            ))}
            {shown.measures.map((name) => (
              <TableHeaderCell key={name} numeric>
                {name}
              </TableHeaderCell>
            ))}
            <TableHeaderCell>State</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {shown.items.map((row) => (
            <TableRow key={`${row.window_start}-${row.window_end}-${JSON.stringify(row.group)}`}>
              <TableCell className="whitespace-nowrap text-ink-2">{formatDateTime(row.window_start)}</TableCell>
              <TableCell className="whitespace-nowrap text-ink-2">{formatDateTime(row.window_end)}</TableCell>
              {shown.group_by.map((name, index) => (
                <TableCell key={name} className="text-ink">
                  {String(row.group[index] ?? "")}
                </TableCell>
              ))}
              {shown.measures.map((name) => (
                <TableCell key={name} numeric className="text-ink">
                  {formatValue(row.values[name])}
                </TableCell>
              ))}
              <TableCell className="whitespace-nowrap">
                <Badge tone={row.final ? "neutral" : "info"}>{row.final ? (row.restated ? "Final, updated late" : "Final") : "Still open"}</Badge>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return formatNumber(value);
  return String(value);
}

type Duration = { amount: string; unit: number };

const seconds = (duration: Duration) => Number(duration.amount) * duration.unit;

function DurationField({ id, label, value, onChange, description }: {
  id: string;
  label: string;
  value: Duration;
  onChange: (next: Duration) => void;
  description?: string;
}) {
  return (
    <FormField label={label} htmlFor={id} description={description}>
      <div className="flex gap-2">
        <Input id={id} type="number" min={0} value={value.amount} onChange={(event) => onChange({ ...value, amount: event.target.value })} />
        <Select
          aria-label={`${label}: unit`}
          value={String(value.unit)}
          onChange={(event) => onChange({ ...value, unit: Number(event.target.value) })}
        >
          {UNITS.map((unit) => (
            <option key={unit.seconds} value={unit.seconds}>
              {unit.label}
            </option>
          ))}
        </Select>
      </div>
    </FormField>
  );
}

function AddLiveRecipe({
  open,
  onClose,
  path,
  savedRecipes,
  datasets,
  onAdded,
}: {
  open: boolean;
  onClose: () => void;
  path: string;
  savedRecipes: TransformationPipelineRecord[];
  datasets: { id: string; name: string }[];
  onAdded: () => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [recipeId, setRecipeId] = useState("");
  const [lookupOn, setLookupOn] = useState(false);
  const [lookupDataset, setLookupDataset] = useState("");
  const [eventColumn, setEventColumn] = useState("");
  const [datasetColumn, setDatasetColumn] = useState("");
  const [bring, setBring] = useState("");
  const [keepUnmatched, setKeepUnmatched] = useState(true);
  const [summarise, setSummarise] = useState(true);
  const [kind, setKind] = useState<LiveWindowKind>("tumbling");
  const [size, setSize] = useState<Duration>({ amount: "5", unit: 60 });
  const [advance, setAdvance] = useState<Duration>({ amount: "1", unit: 60 });
  const [gap, setGap] = useState<Duration>({ amount: "30", unit: 60 });
  const [timeColumn, setTimeColumn] = useState("received_at");
  const [lateness, setLateness] = useState<Duration>({ amount: "30", unit: 1 });
  const [late, setLate] = useState<"drop" | "restate">("drop");
  const [restateFor, setRestateFor] = useState<Duration>({ amount: "1", unit: 3600 });
  const [groupBy, setGroupBy] = useState("");
  const [measures, setMeasures] = useState<LiveMeasure[]>([{ name: "events", op: "count", column: null }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const windowSpec: LiveWindow = {
    kind,
    size_seconds: kind === "session" ? null : seconds(size),
    advance_seconds: kind === "hopping" ? seconds(advance) : null,
    gap_seconds: kind === "session" ? seconds(gap) : null,
    time_column: timeColumn.trim() || "received_at",
    lateness_seconds: seconds(lateness) || 0,
    late,
    restate_for_seconds: late === "restate" ? seconds(restateFor) : 0,
  };

  const missing =
    (name.trim().length < 2 ? "A name" : null) ??
    (lookupOn && (!lookupDataset || !eventColumn.trim() || !datasetColumn.trim() || tableList(bring).length === 0)
      ? "The lookup's dataset, its matching columns and what to bring"
      : null) ??
    (summarise && measures.some((measure) => !measure.name.trim() || (measure.op !== "count" && !measure.column?.trim()))
      ? "Each measure's name and column"
      : null) ??
    (!summarise && !recipeId && !lookupOn ? "Steps, a lookup or a summary" : null);

  const save = async () => {
    const body: LiveRecipeCreate = {
      name: name.trim(),
      recipe_id: recipeId || null,
      lookup: lookupOn
        ? {
            dataset_id: lookupDataset,
            on: [{ event: eventColumn.trim(), dataset: datasetColumn.trim() }],
            columns: tableList(bring),
            keep_unmatched: keepUnmatched,
          }
        : null,
      window: summarise ? windowSpec : null,
      group_by: summarise ? tableList(groupBy) : [],
      measures: summarise
        ? measures.map((measure) => ({ name: measure.name.trim(), op: measure.op, column: measure.op === "count" ? null : measure.column?.trim() || null }))
        : [],
    };
    setBusy(true);
    setError(null);
    try {
      await apiFetch(path, { method: "POST", body: JSON.stringify(body) });
      setName("");
      await onAdded();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add a live recipe"
      description="It starts with the events the feed still keeps, then runs on every batch."
      widthClassName="max-w-2xl"
      footer={
        <div className="flex w-full items-center justify-between gap-2">
          <span className="text-[13px] text-ink-3">{missing ? `${missing} still needed.` : null}</span>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button size="sm" disabled={busy || Boolean(missing)} onClick={() => void save()}>
              {busy ? "Adding…" : "Add it"}
            </Button>
          </div>
        </div>
      }
    >
      <div className="space-y-5">
        <FormField label="Name" htmlFor="live-recipe-name">
          <Input id="live-recipe-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Orders per minute" autoFocus />
        </FormField>
        <FormField
          label="Steps from a recipe (optional)"
          htmlFor="live-recipe-steps"
          description="Build it in the Studio on this feed's log dataset. Steps that work row by row only: filters, new columns, renames, clean-ups."
        >
          <Select id="live-recipe-steps" value={recipeId} onChange={(event) => setRecipeId(event.target.value)}>
            <option value="">No steps</option>
            {savedRecipes.map((recipe) => (
              <option key={recipe.id} value={recipe.id}>
                {recipe.name} ({countOf(recipe.step_count, "step")})
              </option>
            ))}
          </Select>
        </FormField>

        <fieldset className={lookupOn ? "space-y-3 rounded-2xl border border-line px-4 py-3" : "space-y-3"}>
          <legend className="px-1 text-sm font-medium text-ink">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={lookupOn} onChange={(event) => setLookupOn(event.target.checked)} className="h-4 w-4" />
              Look up each event in a dataset
            </label>
          </legend>
          {lookupOn ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <FormField label="Dataset" htmlFor="lookup-dataset">
                <Select id="lookup-dataset" value={lookupDataset} onChange={(event) => setLookupDataset(event.target.value)}>
                  <option value="">Choose…</option>
                  {datasets.map((dataset) => (
                    <option key={dataset.id} value={dataset.id}>
                      {dataset.name}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField label="Columns to bring" htmlFor="lookup-bring" description="Separate several with commas.">
                <Input id="lookup-bring" value={bring} onChange={(event) => setBring(event.target.value)} placeholder="region, tier" />
              </FormField>
              <FormField label="Event column" htmlFor="lookup-event">
                <Input id="lookup-event" value={eventColumn} onChange={(event) => setEventColumn(event.target.value)} placeholder="customer_id" />
              </FormField>
              <FormField label="Matches dataset column" htmlFor="lookup-column">
                <Input id="lookup-column" value={datasetColumn} onChange={(event) => setDatasetColumn(event.target.value)} placeholder="id" />
              </FormField>
              <label className="flex items-center gap-2 text-[14px] text-ink-2 sm:col-span-2">
                <input type="checkbox" checked={keepUnmatched} onChange={(event) => setKeepUnmatched(event.target.checked)} className="h-4 w-4" />
                Keep events that match nothing (their looked-up columns empty)
              </label>
            </div>
          ) : null}
        </fieldset>

        <fieldset className={summarise ? "space-y-3 rounded-2xl border border-line px-4 py-3" : "space-y-3"}>
          <legend className="px-1 text-sm font-medium text-ink">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={summarise} onChange={(event) => setSummarise(event.target.checked)} className="h-4 w-4" />
              Summarise by time
            </label>
          </legend>
          {summarise ? (
            <div className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <FormField label="Windows" htmlFor="window-kind" description={WINDOW_LABELS[kind].help}>
                  <Select id="window-kind" value={kind} onChange={(event) => setKind(event.target.value as LiveWindowKind)}>
                    {(Object.keys(WINDOW_LABELS) as LiveWindowKind[]).map((option) => (
                      <option key={option} value={option}>
                        {WINDOW_LABELS[option].label}
                      </option>
                    ))}
                  </Select>
                </FormField>
                {kind === "session" ? (
                  <DurationField id="window-gap" label="A session ends after this quiet" value={gap} onChange={setGap} />
                ) : (
                  <DurationField id="window-size" label="Each window is" value={size} onChange={setSize} />
                )}
                {kind === "hopping" ? (
                  <DurationField id="window-advance" label="A new one starts every" value={advance} onChange={setAdvance} />
                ) : null}
                <FormField
                  label="Time from"
                  htmlFor="window-time"
                  description="A column holding each event's time, or received_at for when it arrived."
                >
                  <Input id="window-time" value={timeColumn} onChange={(event) => setTimeColumn(event.target.value)} />
                </FormField>
                <DurationField
                  id="window-lateness"
                  label="Wait for late events"
                  value={lateness}
                  onChange={setLateness}
                  description="A window is final once events this much later than its end have arrived."
                />
                <FormField label="An event later still" htmlFor="window-late">
                  <Select id="window-late" value={late} onChange={(event) => setLate(event.target.value as "drop" | "restate")}>
                    <option value="drop">Count it and leave it out</option>
                    <option value="restate">Update the window it belongs to</option>
                  </Select>
                </FormField>
                {late === "restate" ? (
                  <DurationField id="window-restate" label="For windows closed within" value={restateFor} onChange={setRestateFor} />
                ) : null}
              </div>
              <FormField label="Group by (optional)" htmlFor="window-group" description="Columns, separated by commas: one row per window for each.">
                <Input id="window-group" value={groupBy} onChange={(event) => setGroupBy(event.target.value)} placeholder="region" />
              </FormField>
              <div className="space-y-2">
                <div className="text-sm font-medium text-ink">Measures</div>
                {measures.map((measure, index) => (
                  <div key={index} className="grid gap-2 sm:grid-cols-[1fr_1fr_1fr_auto]">
                    <Input
                      aria-label={`Measure ${index + 1}: name`}
                      value={measure.name}
                      onChange={(event) => setMeasures(measures.map((m, i) => (i === index ? { ...m, name: event.target.value } : m)))}
                      placeholder="revenue"
                    />
                    <Select
                      aria-label={`Measure ${index + 1}: what`}
                      value={measure.op}
                      onChange={(event) =>
                        setMeasures(measures.map((m, i) => (i === index ? { ...m, op: event.target.value as LiveMeasureOp } : m)))
                      }
                    >
                      {OPS.map((op) => (
                        <option key={op.op} value={op.op}>
                          {op.label}
                        </option>
                      ))}
                    </Select>
                    <Input
                      aria-label={`Measure ${index + 1}: column`}
                      value={measure.column ?? ""}
                      disabled={measure.op === "count"}
                      onChange={(event) => setMeasures(measures.map((m, i) => (i === index ? { ...m, column: event.target.value } : m)))}
                      placeholder={measure.op === "count" ? "Every event" : "amount"}
                    />
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={measures.length === 1}
                      onClick={() => setMeasures(measures.filter((_, i) => i !== index))}
                    >
                      Remove
                    </Button>
                  </div>
                ))}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setMeasures([...measures, { name: "", op: "sum", column: "" }])}
                >
                  Add a measure
                </Button>
              </div>
            </div>
          ) : null}
        </fieldset>
        {error ? (
          <p role="alert" className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
            {error}
          </p>
        ) : null}
      </div>
    </Modal>
  );
}
