"use client";

import { useEffect, useMemo, useState } from "react";

import type {
  ContractColumn,
  ContractColumnKind,
  ContractEnforcement,
  ContractTerms,
  DataContractWrite,
  ImpactAnalysis,
} from "@platform/shared-types";
import { Button, FormField, Input, SectionPanel, Select, Textarea } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { countOf } from "@/lib/format";

import { KIND_WORDS, KINDS, blankColumn, takesRange } from "../contract-words";

type ContractEditorProps = {
  projectId: string;
  datasetId: string;
  /** The dataset's columns now, offered when adding a promise. */
  columns: string[];
  people: { id: string; username: string }[];
  initial: DataContractWrite;
  /** The promises saved before this edit, to show what dropping one affects. */
  saved: ContractTerms | null;
  busy: boolean;
  error: string | null;
  onSave: (contract: DataContractWrite) => void;
  onCancel: () => void;
};

const numberOrNull = (text: string): number | null => {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
};

const text = (value: number | null) => (value === null ? "" : String(value));

const valuesText = (values: string[] | null) => (values ?? []).join(", ");

const parseValues = (raw: string): string[] | null => {
  const values = raw
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  return values.length ? values : null;
};

/**
 * Writing or changing a contract (Phase 19, C1): who owns it, what happens
 * to data that breaks it, a promise per column and about the dataset as a
 * whole. Dropping a promise that something reads says what, before saving.
 */
export function ContractEditor({
  projectId,
  datasetId,
  columns,
  people,
  initial,
  saved,
  busy,
  error,
  onSave,
  onCancel,
}: ContractEditorProps) {
  const [owner, setOwner] = useState(initial.owner_user_id ?? "");
  const [description, setDescription] = useState(initial.description ?? "");
  const [enforcement, setEnforcement] = useState<ContractEnforcement>(initial.enforcement);
  const [promised, setPromised] = useState<ContractColumn[]>(initial.terms.columns);
  // What people type into the list and number boxes, kept as typed.
  const [allowedText, setAllowedText] = useState<string[]>(initial.terms.columns.map((c) => valuesText(c.allowed_values)));
  const [lowText, setLowText] = useState<string[]>(initial.terms.columns.map((c) => text(c.lowest)));
  const [highText, setHighText] = useState<string[]>(initial.terms.columns.map((c) => text(c.highest)));
  const [otherColumns, setOtherColumns] = useState(initial.terms.other_columns);
  const [atLeast, setAtLeast] = useState(text(initial.terms.rows_at_least));
  const [atMost, setAtMost] = useState(text(initial.terms.rows_at_most));
  const [drop, setDrop] = useState(text(initial.terms.largest_drop_percent));
  const [every, setEvery] = useState(text(initial.terms.new_data_every_hours));
  const [adding, setAdding] = useState("");
  const [impact, setImpact] = useState<ImpactAnalysis | null>(null);

  const promisedNames = useMemo(() => new Set(promised.map((column) => column.name)), [promised]);
  const unpromised = columns.filter((name) => !promisedNames.has(name));
  const dropped = useMemo(
    () => (saved?.columns ?? []).map((column) => column.name).filter((name) => !promisedNames.has(name) && columns.includes(name)),
    [saved, promisedNames, columns],
  );

  // What reads a column no longer promised, from the column impact analysis.
  useEffect(() => {
    if (dropped.length === 0) {
      setImpact(null);
      return;
    }
    let cancelled = false;
    apiFetch<ImpactAnalysis>(`/projects/${projectId}/datasets/${datasetId}/impact`, {
      method: "POST",
      body: JSON.stringify({ columns: dropped }),
    })
      .then((found) => {
        if (!cancelled) setImpact(found);
      })
      .catch(() => {
        if (!cancelled) setImpact(null);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, datasetId, dropped]);

  const change = (index: number, patch: Partial<ContractColumn>) =>
    setPromised((current) => current.map((column, at) => (at === index ? { ...column, ...patch } : column)));

  const remove = (index: number) => {
    setPromised((current) => current.filter((_, at) => at !== index));
    setAllowedText((current) => current.filter((_, at) => at !== index));
    setLowText((current) => current.filter((_, at) => at !== index));
    setHighText((current) => current.filter((_, at) => at !== index));
  };

  const add = () => {
    const name = adding.trim();
    if (!name || promisedNames.has(name)) return;
    setPromised((current) => [...current, blankColumn(name)]);
    setAllowedText((current) => [...current, ""]);
    setLowText((current) => [...current, ""]);
    setHighText((current) => [...current, ""]);
    setAdding("");
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    onSave({
      owner_user_id: owner || null,
      description: description.trim() || null,
      enforcement,
      terms: {
        columns: promised.map((column, index) => ({
          ...column,
          allowed_values: parseValues(allowedText[index] ?? ""),
          lowest: takesRange(column.kind) ? numberOrNull(lowText[index] ?? "") : null,
          highest: takesRange(column.kind) ? numberOrNull(highText[index] ?? "") : null,
        })),
        other_columns: otherColumns,
        rows_at_least: numberOrNull(atLeast),
        rows_at_most: numberOrNull(atMost),
        largest_drop_percent: numberOrNull(drop),
        new_data_every_hours: numberOrNull(every),
      },
    });
  };

  return (
    <form onSubmit={submit} className="space-y-6">
      <SectionPanel title="About it" description="Who answers for it, and what happens to new data that breaks it.">
        <div className="grid gap-4 md:grid-cols-2">
          <FormField label="Owner" htmlFor="contract-owner" description="Told first when it breaks; answers for fixing it.">
            <Select id="contract-owner" value={owner} onChange={(event) => setOwner(event.target.value)}>
              {owner === "" ? <option value="">You</option> : null}
              {people.map((person) => (
                <option key={person.id} value={person.id}>
                  {person.username}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField
            label="When new data breaks it"
            htmlFor="contract-enforcement"
            description="Stopping keeps what people use unchanged until the data is fixed."
          >
            <Select
              id="contract-enforcement"
              value={enforcement}
              onChange={(event) => setEnforcement(event.target.value as ContractEnforcement)}
            >
              <option value="stop">Stop the data, and keep the current data</option>
              <option value="warn">Let it through, with a warning</option>
            </Select>
          </FormField>
          <div className="md:col-span-2">
            <FormField label="Description" htmlFor="contract-description" description="What this data is, and who relies on it.">
              <Textarea
                id="contract-description"
                rows={2}
                maxLength={2000}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="Orders after cleaning, used by the finance dashboard every morning."
              />
            </FormField>
          </div>
        </div>
      </SectionPanel>

      <SectionPanel
        title="Columns"
        description="What each promised column holds. A missing column always breaks the contract."
      >
        {promised.length === 0 ? (
          <p className="text-sm text-ink-3">No columns promised yet. Add the ones people rely on.</p>
        ) : (
          <ul className="space-y-3">
            {promised.map((column, index) => (
              <li key={column.name} className="rounded-2xl border border-line bg-surface px-4 py-3">
                <div className="flex flex-wrap items-end gap-3">
                  <div className="min-w-[10rem] flex-1">
                    <div className="text-[13px] text-ink-3">Column</div>
                    <div className="mt-1 truncate text-[15px] font-medium text-ink" title={column.name}>
                      {column.name}
                      {!columns.includes(column.name) ? (
                        <span className="ml-2 text-[13px] font-normal text-warning">not in the data now</span>
                      ) : null}
                    </div>
                  </div>
                  <div className="w-44">
                    <FormField label="Kind" htmlFor={`kind-${index}`}>
                      <Select
                        id={`kind-${index}`}
                        value={column.kind}
                        onChange={(event) => change(index, { kind: event.target.value as ContractColumnKind })}
                      >
                        {KINDS.map((kind) => (
                          <option key={kind} value={kind}>
                            {KIND_WORDS[kind]}
                          </option>
                        ))}
                      </Select>
                    </FormField>
                  </div>
                  <label className="flex h-11 items-center gap-2 text-sm text-ink-2">
                    <input
                      type="checkbox"
                      className="h-4 w-4"
                      checked={column.always_filled}
                      onChange={(event) => change(index, { always_filled: event.target.checked })}
                    />
                    Always filled
                  </label>
                  <label className="flex h-11 items-center gap-2 text-sm text-ink-2">
                    <input
                      type="checkbox"
                      className="h-4 w-4"
                      checked={column.no_repeats}
                      onChange={(event) => change(index, { no_repeats: event.target.checked })}
                    />
                    No repeats
                  </label>
                  <Button type="button" variant="ghost" size="sm" onClick={() => remove(index)} aria-label={`Stop promising ${column.name}`}>
                    Remove
                  </Button>
                </div>
                <div className="mt-3 grid gap-3 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
                  <FormField label="Only these values" htmlFor={`values-${index}`} description="Separated by commas; leave empty for any.">
                    <Input
                      id={`values-${index}`}
                      value={allowedText[index] ?? ""}
                      onChange={(event) =>
                        setAllowedText((current) => current.map((value, at) => (at === index ? event.target.value : value)))
                      }
                      placeholder="shipped, cancelled, refunded"
                    />
                  </FormField>
                  {takesRange(column.kind) ? (
                    <>
                      <FormField label="Lowest" htmlFor={`low-${index}`}>
                        <Input
                          id={`low-${index}`}
                          type="number"
                          step="any"
                          inputMode="decimal"
                          value={lowText[index] ?? ""}
                          onChange={(event) =>
                            setLowText((current) => current.map((value, at) => (at === index ? event.target.value : value)))
                          }
                        />
                      </FormField>
                      <FormField label="Highest" htmlFor={`high-${index}`}>
                        <Input
                          id={`high-${index}`}
                          type="number"
                          step="any"
                          inputMode="decimal"
                          value={highText[index] ?? ""}
                          onChange={(event) =>
                            setHighText((current) => current.map((value, at) => (at === index ? event.target.value : value)))
                          }
                        />
                      </FormField>
                    </>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-4 flex flex-wrap items-end gap-3">
          <div className="min-w-[14rem] flex-1">
            <FormField label="Promise another column" htmlFor="contract-add-column">
              {unpromised.length ? (
                <Select id="contract-add-column" value={adding} onChange={(event) => setAdding(event.target.value)}>
                  <option value="">Choose a column</option>
                  {unpromised.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </Select>
              ) : (
                <Input
                  id="contract-add-column"
                  value={adding}
                  onChange={(event) => setAdding(event.target.value)}
                  placeholder="Every column is promised; type a new one"
                />
              )}
            </FormField>
          </div>
          <Button type="button" variant="secondary" onClick={add} disabled={!adding.trim()}>
            Add
          </Button>
        </div>

        {dropped.length ? (
          <div className="mt-4 rounded-2xl border border-warning-line bg-warning-soft px-4 py-3 text-sm text-ink-2">
            <p className="font-medium text-warning">
              No longer promising {dropped.join(", ")}.
            </p>
            {impact && impact.findings.length ? (
              <>
                <p className="mt-1">
                  {countOf(impact.findings.length, "thing")} in this project {impact.findings.length === 1 ? "reads" : "read"}{" "}
                  {dropped.length === 1 ? "it" : "them"}, and would break if {dropped.length === 1 ? "it goes" : "they go"}:
                </p>
                <ul className="mt-1 list-disc pl-5">
                  {impact.findings.slice(0, 8).map((finding) => (
                    <li key={`${finding.kind}-${finding.id}`}>
                      {finding.name}: {finding.detail}
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="mt-1">Nothing in this project reads {dropped.length === 1 ? "it" : "them"} now.</p>
            )}
          </div>
        ) : null}
      </SectionPanel>

      <SectionPanel title="The dataset as a whole" description="Leave a box empty to promise nothing about it.">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <FormField label="At least this many rows" htmlFor="contract-at-least">
            <Input id="contract-at-least" type="number" min={0} step={1} value={atLeast} onChange={(event) => setAtLeast(event.target.value)} />
          </FormField>
          <FormField label="At most this many rows" htmlFor="contract-at-most">
            <Input id="contract-at-most" type="number" min={0} step={1} value={atMost} onChange={(event) => setAtMost(event.target.value)} />
          </FormField>
          <FormField
            label="Largest fall in rows (%)"
            htmlFor="contract-drop"
            description="Compared with the data it would replace."
          >
            <Input id="contract-drop" type="number" min={0} max={100} step="any" value={drop} onChange={(event) => setDrop(event.target.value)} />
          </FormField>
          <FormField
            label="New data at least every (hours)"
            htmlFor="contract-every"
            description="Also shown as this dataset's freshness on Data health."
          >
            <Input id="contract-every" type="number" min={0} step="any" value={every} onChange={(event) => setEvery(event.target.value)} />
          </FormField>
          <FormField label="Other columns" htmlFor="contract-other-columns">
            <Select
              id="contract-other-columns"
              value={otherColumns}
              onChange={(event) => setOtherColumns(event.target.value as ContractTerms["other_columns"])}
            >
              <option value="allowed">New columns may appear</option>
              <option value="not_allowed">Only the promised columns</option>
            </Select>
          </FormField>
        </div>
      </SectionPanel>

      {error ? (
        <p role="alert" className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save the contract"}
        </Button>
      </div>
    </form>
  );
}
