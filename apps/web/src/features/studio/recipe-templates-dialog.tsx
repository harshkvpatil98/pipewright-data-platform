"use client";

import { useEffect, useMemo, useState } from "react";

import type { LineageColumnListResponse } from "@platform/shared-types";
import { Badge, Button, Icon, Modal } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { countOf } from "@/lib/format";
import { cx } from "@/lib/utils";

type Role = {
  key: string;
  label: string;
  description: string;
  kind: string;
  required: boolean;
  multiple: boolean;
};

type Template = { id: string; name: string; description: string; roles: Role[] };

type Match = {
  template: Template;
  mapping: Record<string, string | string[] | null>;
  missing: string[];
};

export type TemplateStep = { step_type: string; config: Record<string, unknown> };

/** Steps someone in this project saved as a template (E1). */
type SavedTemplate = { id: string; name: string; description: string | null; steps_json: TemplateStep[]; step_count: number };

type RecipeTemplatesDialogProps = {
  open: boolean;
  onClose: () => void;
  projectId: string;
  datasetId: string;
  onApply: (steps: TemplateStep[], templateName: string) => void;
};

/**
 * Start a recipe from a common job ("clean a contact list") instead of from
 * an empty list. The templates live on the server, which matches each one's
 * roles against this dataset's columns; the person confirms or changes the
 * columns, and the result is ordinary steps they can edit like any other.
 */
export function RecipeTemplatesDialog({
  open,
  onClose,
  projectId,
  datasetId,
  onApply,
}: RecipeTemplatesDialogProps) {
  const [columns, setColumns] = useState<string[]>([]);
  const [types, setTypes] = useState<Record<string, string>>({});
  const [matches, setMatches] = useState<Match[] | null>(null);
  const [chosen, setChosen] = useState<Match | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | string[] | null>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<SavedTemplate[]>([]);

  useEffect(() => {
    if (!open || !datasetId) return;
    let cancelled = false;
    setMatches(null);
    setChosen(null);
    setError(null);
    apiFetch<{ items: SavedTemplate[] }>(`/projects/${projectId}/recipe-templates`)
      .then((response) => {
        if (!cancelled) setSaved(response.items);
      })
      .catch(() => {
        if (!cancelled) setSaved([]);
      });
    (async () => {
      try {
        const described = await apiFetch<LineageColumnListResponse>(
          `/projects/${projectId}/datasets/${datasetId}/lineage/columns`,
        );
        const response = await apiFetch<{ items: Match[] }>("/transformations/templates/match", {
          method: "POST",
          body: JSON.stringify({ columns: described.columns, types: described.types ?? {} }),
        });
        if (cancelled) return;
        setColumns(described.columns);
        setTypes(described.types ?? {});
        setMatches(response.items);
      } catch (caught) {
        if (!cancelled) setError(extractErrorMessage(caught));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, projectId, datasetId]);

  const roleLabel = useMemo(() => {
    const labels = new Map<string, string>();
    for (const match of matches ?? []) {
      for (const role of match.template.roles) labels.set(`${match.template.id}:${role.key}`, role.label);
    }
    return labels;
  }, [matches]);

  const remove = async (template: SavedTemplate) => {
    try {
      await apiFetch(`/projects/${projectId}/recipe-templates/${template.id}`, { method: "DELETE" });
      setSaved((current) => current.filter((item) => item.id !== template.id));
    } catch (caught) {
      setError(extractErrorMessage(caught));
    }
  };

  const choose = (match: Match) => {
    setChosen(match);
    setMapping(match.mapping);
    setError(null);
  };

  const apply = async () => {
    if (!chosen) return;
    setBusy(true);
    setError(null);
    try {
      const response = await apiFetch<{ steps: TemplateStep[] }>(
        `/transformations/templates/${chosen.template.id}/steps`,
        { method: "POST", body: JSON.stringify({ columns, types, mapping }) },
      );
      onApply(response.steps, chosen.template.name);
      onClose();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const missingRequired =
    chosen?.template.roles.some((role) => {
      const value = mapping[role.key];
      return role.required && (Array.isArray(value) ? value.length === 0 : !value);
    }) ?? false;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={chosen ? chosen.template.name : "Start from a template"}
      description={
        chosen
          ? "Check which columns it should use. The steps are added to your recipe, where you can change them."
          : "Common jobs, done in a few steps. Pick one and it suggests the columns to use."
      }
      widthClassName="max-w-xl"
      footer={
        chosen ? (
          <div className="flex justify-between gap-2">
            <Button variant="ghost" size="sm" onClick={() => setChosen(null)}>
              Back
            </Button>
            <Button size="sm" onClick={() => void apply()} disabled={busy || missingRequired}>
              {busy ? "Adding…" : "Add these steps"}
            </Button>
          </div>
        ) : undefined
      }
    >
      {error ? (
        <p role="alert" className="mb-3 text-[13px] text-danger">
          {error}
        </p>
      ) : null}

      {!chosen && saved.length ? (
        <div className="mb-4">
          <p className="mb-2 text-[13px] font-medium text-ink-2">Saved in this project</p>
          <ul className="space-y-2">
            {saved.map((template) => (
              <li key={template.id} className="flex items-start gap-2 rounded-2xl border border-line bg-surface p-3">
                <button
                  type="button"
                  onClick={() => {
                    onApply(template.steps_json, template.name);
                    onClose();
                  }}
                  className="min-w-0 flex-1 text-left"
                >
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-[15px] font-semibold text-ink">{template.name}</span>
                    <Badge>{countOf(template.step_count, "step")}</Badge>
                  </span>
                  {template.description ? (
                    <span className="mt-1 block text-[13px] leading-5 text-ink-3">{template.description}</span>
                  ) : null}
                </button>
                <Button variant="ghost" size="sm" onClick={() => void remove(template)} aria-label={`Remove ${template.name}`}>
                  <Icon name="trash" size={14} />
                </Button>
              </li>
            ))}
          </ul>
          <p className="mb-2 mt-4 text-[13px] font-medium text-ink-2">Common jobs</p>
        </div>
      ) : null}

      {!chosen ? (
        matches === null ? (
          <p className="py-6 text-center text-[14px] text-muted">{error ? "" : "Looking at the columns…"}</p>
        ) : (
          <ul className="space-y-2">
            {matches.map((match) => {
              const fits = match.missing.length === 0;
              return (
                <li key={match.template.id}>
                  <button
                    type="button"
                    onClick={() => choose(match)}
                    className="flex w-full items-start gap-3 rounded-2xl border border-line bg-surface p-4 text-left transition hover:border-[color:var(--accent-soft)] hover:bg-[color:var(--accent-faint)]"
                  >
                    <Icon name="sparkles" size={17} className="mt-0.5 shrink-0 text-[color:var(--accent-muted)]" />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="text-[15px] font-semibold text-ink">{match.template.name}</span>
                        <Badge tone={fits
                              ? "success"
                              : "neutral"}>
                          {fits
                            ? "Fits this data"
                            : `Needs ${match.missing
                                .map((key) => (roleLabel.get(`${match.template.id}:${key}`) ?? key).toLowerCase())
                                .join(" and ")}`}
                        </Badge>
                      </span>
                      <span className="mt-1 block text-[13px] leading-5 text-ink-3">
                        {match.template.description}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )
      ) : (
        <div className="space-y-4">
          {chosen.template.roles.map((role) => (
            <label key={role.key} className="block">
              <span className="text-[14px] font-medium text-ink">{role.label}</span>
              <span className="mt-0.5 block text-[13px] text-ink-3">{role.description}</span>
              {role.multiple ? (
                <span className="mt-2 flex flex-wrap gap-1.5">
                  {columns.map((column) => {
                    const current = Array.isArray(mapping[role.key]) ? (mapping[role.key] as string[]) : [];
                    const on = current.includes(column);
                    return (
                      <button
                        key={column}
                        type="button"
                        aria-pressed={on}
                        onClick={() =>
                          setMapping((previous) => ({
                            ...previous,
                            [role.key]: on
                              ? current.filter((item) => item !== column)
                              : [...current, column],
                          }))
                        }
                        className={cx(
                          "rounded-full border px-2.5 py-1 text-[13px] transition",
                          on
                            ? "border-[color:var(--accent)] bg-[color:var(--accent-faint)] text-ink"
                            : "border-line text-ink-3 hover:text-ink",
                        )}
                      >
                        {column}
                      </button>
                    );
                  })}
                </span>
              ) : (
                <select
                  value={typeof mapping[role.key] === "string" ? (mapping[role.key] as string) : ""}
                  onChange={(event) => {
                    const value = event.target.value || null;
                    setMapping((previous) => ({ ...previous, [role.key]: value }));
                  }}
                  className="mt-2 h-10 w-full rounded-lg border border-line bg-sunken px-3 text-[14px] text-ink outline-none focus:border-[color:var(--accent)]"
                >
                  <option value="">{role.required ? "Choose a column…" : "None"}</option>
                  {columns.map((column) => (
                    <option key={column} value={column}>
                      {column}
                    </option>
                  ))}
                </select>
              )}
            </label>
          ))}
        </div>
      )}
    </Modal>
  );
}
