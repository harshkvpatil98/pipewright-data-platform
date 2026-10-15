"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { Badge, Button, Input, Modal, Select, Textarea } from "@platform/shared-ui";

import { compareRecipes, type PlainStep, type RecipeChange } from "@/features/studio/recipe-diff";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { countOf } from "@/lib/format";
import { recipeHref } from "@/lib/navigation";

/** A recipe parameter (E1): {{name}} in any setting, with a value per run. */
export type RecipeParameter = {
  name: string;
  label?: string | null;
  kind: "text" | "number" | "whole number" | "date" | "true or false";
  default?: unknown;
  description?: string | null;
};

const KINDS: RecipeParameter["kind"][] = ["text", "number", "whole number", "date", "true or false"];

/** The {{names}} a recipe's steps use. */
export function usedParameters(steps: PlainStep[]): string[] {
  const found = new Set<string>();
  const visit = (value: unknown) => {
    if (typeof value === "string") {
      for (const match of value.matchAll(/\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g)) found.add(match[1]);
    } else if (Array.isArray(value)) value.forEach(visit);
    else if (value && typeof value === "object") Object.values(value).forEach(visit);
  };
  steps.forEach((step) => visit(step.config));
  return [...found];
}

function Field({ label, help, children }: { label: string; help?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>
      {children}
      {help ? <span className="text-xs text-muted">{help}</span> : null}
    </label>
  );
}

function Problem({ text }: { text: string | null }) {
  return text ? <p className="rounded-lg border border-danger-line bg-danger-soft px-3 py-2 text-[13px] text-ink">{text}</p> : null;
}

// ------------------------------------------------------------ save as template

export function SaveTemplateDialog({
  open,
  onClose,
  projectId,
  steps,
  initialName = "",
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  steps: PlainStep[];
  /** A group's name, when one group of steps is saved. */
  initialName?: string;
  onSaved: (name: string) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      setName(initialName);
      setDescription("");
      setProblem(null);
    }
  }, [open, initialName]);

  const save = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await apiFetch(`/projects/${projectId}/recipe-templates`, {
        method: "POST",
        body: JSON.stringify({ name, description: description || null, steps_json: steps }),
      });
      onSaved(name);
      onClose();
    } catch (caught) {
      setProblem(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Save steps as a template"
      description={`${countOf(steps.length, "step")}, saved for anyone in this project to add to a recipe from Templates.`}
      widthClassName="max-w-lg"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button size="sm" disabled={busy || name.trim().length < 2} onClick={() => void save()}>
            {busy ? "Saving…" : "Save template"}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        <Field label="Name">
          <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Tidy a contact list" />
        </Field>
        <Field label="What it is for">
          <Input value={description} onChange={(event) => setDescription(event.target.value)} />
        </Field>
        <Problem text={problem} />
      </div>
    </Modal>
  );
}

// ------------------------------------------------------------------ parameters

export function ParametersDialog({
  open,
  onClose,
  projectId,
  recipeId,
  parameters,
  used,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  /** Null for a recipe not saved yet: the parameters are kept for its first save. */
  recipeId: string | null;
  parameters: RecipeParameter[];
  used: string[];
  onSaved: (parameters: RecipeParameter[]) => void;
}) {
  const [rows, setRows] = useState<RecipeParameter[]>(parameters);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      const missing = used.filter((name) => !parameters.some((parameter) => parameter.name === name));
      setRows([...parameters, ...missing.map((name) => ({ name, kind: "text" as const, default: "" }))]);
      setProblem(null);
    }
  }, [open, parameters, used]);

  const update = (index: number, patch: Partial<RecipeParameter>) =>
    setRows((current) => current.map((row, position) => (position === index ? { ...row, ...patch } : row)));

  const save = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const cleaned = rows
        .filter((row) => row.name.trim())
        .map((row) => ({ ...row, name: row.name.trim(), default: row.default === "" ? null : row.default }));
      if (recipeId) {
        const result = await apiFetch<{ parameters?: RecipeParameter[] }>(
          `/projects/${projectId}/pipelines/${recipeId}/parameters`,
          { method: "PUT", body: JSON.stringify({ parameters: cleaned }) },
        );
        onSaved(result.parameters ?? cleaned);
      } else {
        onSaved(cleaned);
      }
      onClose();
    } catch (caught) {
      setProblem(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Parameters"
      description="Write {{name}} in any setting; each run takes its value, or the default. Schedules, workflows and the API can give values too."
      widthClassName="max-w-2xl"
      footer={
        <div className="flex justify-between gap-2">
          <Button variant="ghost" size="sm" onClick={() => setRows((current) => [...current, { name: "", kind: "text", default: "" }])}>
            Add a parameter
          </Button>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button size="sm" disabled={busy} onClick={() => void save()}>
              {busy ? "Saving…" : "Save parameters"}
            </Button>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        {rows.length === 0 ? <p className="text-[13px] text-ink-3">This recipe has no parameters yet.</p> : null}
        {rows.map((row, index) => (
          <div key={index} className="grid grid-cols-1 gap-2 rounded-xl border border-line p-3 sm:grid-cols-4">
            <Field label="Name">
              <Input value={row.name} onChange={(event) => update(index, { name: event.target.value })} placeholder="since" />
            </Field>
            <Field label="Shown as">
              <Input value={row.label ?? ""} onChange={(event) => update(index, { label: event.target.value })} />
            </Field>
            <Field label="Kind">
              <Select value={row.kind} onChange={(event) => update(index, { kind: event.target.value as RecipeParameter["kind"] })}>
                {KINDS.map((kind) => (
                  <option key={kind} value={kind}>
                    {kind}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Default">
              <Input value={String(row.default ?? "")} onChange={(event) => update(index, { default: event.target.value })} />
            </Field>
            {used.includes(row.name) ? null : row.name ? (
              <p className="text-[12px] text-muted sm:col-span-4">No step uses {`{{${row.name}}}`} yet.</p>
            ) : null}
          </div>
        ))}
        <Problem text={problem} />
      </div>
    </Modal>
  );
}

export function RunWithValuesDialog({
  open,
  onClose,
  purpose,
  parameters,
  current,
  onRun,
}: {
  open: boolean;
  onClose: () => void;
  /** A run with these values, or the preview showing them. */
  purpose: "run" | "preview";
  parameters: RecipeParameter[];
  /** Values already being tried, shown instead of the defaults. */
  current: Record<string, unknown>;
  onRun: (values: Record<string, unknown>) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!open) return;
    const shown = (parameter: RecipeParameter) => current[parameter.name] ?? parameter.default;
    setValues(Object.fromEntries(parameters.map((p) => [p.name, shown(p) == null ? "" : String(shown(p))])));
  }, [open, parameters, current]);
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={purpose === "run" ? "Run with these values" : "Preview with these values"}
      description={
        purpose === "run"
          ? "Values for this run only; the defaults stay as they are."
          : "The preview shows the result with these values; runs still take the defaults."
      }
      widthClassName="max-w-lg"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={() => {
              onRun(Object.fromEntries(Object.entries(values).filter(([, value]) => value !== "")));
              onClose();
            }}
          >
            {purpose === "run" ? "Run" : "Show the preview"}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        {parameters.map((parameter) => (
          <Field key={parameter.name} label={parameter.label || parameter.name} help={parameter.kind}>
            <Input
              type={parameter.kind === "date" ? "date" : parameter.kind.includes("number") ? "number" : "text"}
              value={values[parameter.name] ?? ""}
              onChange={(event) => {
                const next = event.target.value;
                setValues((current) => ({ ...current, [parameter.name]: next }));
              }}
            />
          </Field>
        ))}
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------- merge

type MergeResult = {
  applied: boolean;
  added: number;
  removed: number;
  changed: number;
  conflicts: { step_id: string; step: string; what: string }[];
  message: string;
};

export function MergeDialog({
  open,
  onClose,
  projectId,
  branchId,
  parentName,
  parentId,
  onMerged,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  branchId: string;
  parentName: string;
  parentId: string;
  onMerged: (message: string) => void;
}) {
  const [preview, setPreview] = useState<MergeResult | null>(null);
  const [prefer, setPrefer] = useState<"recipe" | "branch">("recipe");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setPreview(null);
    setProblem(null);
    apiFetch<MergeResult>(`/projects/${projectId}/pipelines/${branchId}/merge/preview`, {
      method: "POST",
      body: JSON.stringify({}),
    })
      .then(setPreview)
      .catch((caught) => setProblem(extractErrorMessage(caught)));
  }, [open, projectId, branchId]);

  const merge = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const result = await apiFetch<MergeResult>(`/projects/${projectId}/pipelines/${branchId}/merge`, {
        method: "POST",
        body: JSON.stringify({ prefer: preview?.conflicts.length ? prefer : null }),
      });
      onMerged(result.message);
      onClose();
    } catch (caught) {
      setProblem(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Merge into ${parentName}`}
      description="The branch's changes go into the recipe it came from; changes made there since stay."
      widthClassName="max-w-lg"
      footer={
        <div className="flex justify-between gap-2">
          <Link href={recipeHref(projectId, parentId)} className="self-center text-[13px] text-ink-3 underline">
            Open {parentName}
          </Link>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button size="sm" disabled={busy || !preview} onClick={() => void merge()}>
              {busy ? "Merging…" : "Merge"}
            </Button>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-3 text-[13px] text-ink">
        {preview ? (
          <>
            <p>
              {countOf(preview.added, "step")} added, {preview.removed} removed and {preview.changed} changed.
            </p>
            {preview.conflicts.length ? (
              <div className="rounded-xl border border-line p-3">
                <p className="mb-2 font-medium">Both sides changed these:</p>
                <ul className="mb-3 list-disc space-y-1 pl-5 text-ink-2">
                  {preview.conflicts.map((conflict) => (
                    <li key={`${conflict.step_id}-${conflict.what}`}>
                      {conflict.step}: {conflict.what}
                    </li>
                  ))}
                </ul>
                <Field label="Where they differ, keep">
                  <Select value={prefer} onChange={(event) => setPrefer(event.target.value as "recipe" | "branch")}>
                    <option value="recipe">{parentName}&apos;s</option>
                    <option value="branch">This branch&apos;s</option>
                  </Select>
                </Field>
              </div>
            ) : (
              <Badge tone="success">Nothing conflicts</Badge>
            )}
          </>
        ) : problem ? null : (
          <p className="text-ink-3">Working out what would change…</p>
        )}
        <Problem text={problem} />
      </div>
    </Modal>
  );
}

// -------------------------------------------------------------------- compare

export function CompareDialog({
  open,
  onClose,
  projectId,
  current,
  currentId,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  current: { name: string; steps: PlainStep[] };
  currentId: string | null;
}) {
  const [recipes, setRecipes] = useState<{ id: string; name: string; steps_json: PlainStep[] }[]>([]);
  const [otherId, setOtherId] = useState("");
  useEffect(() => {
    if (!open) return;
    apiFetch<{ items: { id: string; name: string; steps_json: PlainStep[] }[] }>(`/projects/${projectId}/pipelines`)
      .then((response) => setRecipes(response.items.filter((item) => item.id !== currentId)))
      .catch(() => setRecipes([]));
  }, [open, projectId, currentId]);
  const other = recipes.find((item) => item.id === otherId);
  const changes: RecipeChange[] = useMemo(
    () => (other ? compareRecipes({ name: other.name, steps: other.steps_json }, current) : []),
    [other, current],
  );
  return (
    <Modal open={open} onClose={onClose} title="Compare with another recipe" widthClassName="max-w-xl">
      <div className="flex flex-col gap-3">
        <Field label="Compare with">
          <Select value={otherId} onChange={(event) => setOtherId(event.target.value)}>
            <option value="">Choose a recipe…</option>
            {recipes.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </Select>
        </Field>
        {other ? (
          changes.length ? (
            <div>
              <p className="mb-2 text-[13px] text-ink-3">What this recipe does differently from {other.name}:</p>
              <ul className="space-y-1.5 text-[13px] text-ink">
                {changes.map((change, index) => (
                  <li key={index} className="flex gap-2">
                    <Badge tone={change.kind === "removed" ? "danger" : change.kind === "added" ? "success" : "neutral"}>
                      {change.kind}
                    </Badge>
                    <span>{change.text}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-[13px] text-ink">The two recipes have the same steps.</p>
          )
        ) : null}
      </div>
    </Modal>
  );
}

// ------------------------------------------------- elsewhere, and per value

type CopyResult = { pipeline_id: string; name: string; warnings: string[] };

export function CopyDialog({
  open,
  onClose,
  projectId,
  recipeId,
  datasets,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  recipeId: string;
  datasets: { id: string; name: string }[];
}) {
  const [datasetId, setDatasetId] = useState("");
  const [made, setMade] = useState<CopyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      setMade(null);
      setProblem(null);
      setDatasetId("");
    }
  }, [open]);
  const copy = async () => {
    setBusy(true);
    setProblem(null);
    try {
      setMade(
        await apiFetch<CopyResult>(`/projects/${projectId}/pipelines/${recipeId}/copy`, {
          method: "POST",
          body: JSON.stringify({ base_dataset_id: datasetId }),
        }),
      );
    } catch (caught) {
      setProblem(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Use these steps on another dataset"
      description="A new recipe with the same steps, reading the dataset you choose: next month's file, another client's export."
      widthClassName="max-w-lg"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            {made ? "Done" : "Cancel"}
          </Button>
          {made ? null : (
            <Button size="sm" disabled={busy || !datasetId} onClick={() => void copy()}>
              {busy ? "Making it…" : "Make the recipe"}
            </Button>
          )}
        </div>
      }
    >
      <div className="flex flex-col gap-3 text-[13px]">
        {made ? (
          <>
            <p className="text-ink">
              Made <Link className="underline" href={recipeHref(projectId, made.pipeline_id)}>{made.name}</Link>.
            </p>
            {made.warnings.map((warning) => (
              <p key={warning} className="rounded-lg border border-line bg-sunken px-3 py-2 text-ink">
                {warning}
              </p>
            ))}
          </>
        ) : (
          <Field label="Dataset">
            <Select value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>
              <option value="">Choose a dataset…</option>
              {datasets.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <Problem text={problem} />
      </div>
    </Modal>
  );
}

export function SplitDialog({
  open,
  onClose,
  projectId,
  recipeId,
  columns,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  recipeId: string;
  columns: string[];
}) {
  const [column, setColumn] = useState("");
  const [values, setValues] = useState("");
  const [made, setMade] = useState<CopyResult[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      setMade(null);
      setProblem(null);
    }
  }, [open]);
  const split = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const listed = values.split("\n").map((line) => line.trim()).filter(Boolean);
      const response = await apiFetch<{ created: CopyResult[] }>(`/projects/${projectId}/pipelines/${recipeId}/split`, {
        method: "POST",
        body: JSON.stringify({ column, values: listed.length ? listed : null }),
      });
      setMade(response.created);
    } catch (caught) {
      setProblem(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="One recipe for each value"
      description="A copy of this recipe for each value of a column, each keeping only that value's rows: a dataset per region, per client."
      widthClassName="max-w-lg"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            {made ? "Done" : "Cancel"}
          </Button>
          {made ? null : (
            <Button size="sm" disabled={busy || !column} onClick={() => void split()}>
              {busy ? "Making them…" : "Make the recipes"}
            </Button>
          )}
        </div>
      }
    >
      <div className="flex flex-col gap-3 text-[13px]">
        {made ? (
          <ul className="space-y-1">
            {made.map((item) => (
              <li key={item.pipeline_id}>
                <Link className="text-ink underline" href={recipeHref(projectId, item.pipeline_id)}>
                  {item.name}
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <>
            <Field label="Column">
              <Select value={column} onChange={(event) => setColumn(event.target.value)}>
                <option value="">Choose a column…</option>
                {columns.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Only these values" help="One per line; leave empty for every value (up to 50).">
              <Textarea value={values} onChange={(event) => setValues(event.target.value)} className="min-h-[80px]" />
            </Field>
          </>
        )}
        <Problem text={problem} />
      </div>
    </Modal>
  );
}
