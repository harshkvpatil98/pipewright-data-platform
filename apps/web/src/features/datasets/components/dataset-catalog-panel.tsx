"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type {
  CatalogAnnotation,
  CatalogAnnotationUpdate,
  DatasetTermLink,
  GlossaryTerm,
  PiiScanResponse,
  TermListResponse,
} from "@platform/shared-types";
import { Button, SectionPanel } from "@platform/shared-ui";

import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";

type DatasetCatalogPanelProps = {
  projectId: string;
  datasetId: string;
  /** Column names offered when binding a glossary term to this dataset. */
  columns: string[];
};

/**
 * The catalog card as seen from a dataset's own page: a steward names the owner,
 * certifies the dataset, writes a description, and binds glossary terms to its
 * columns -- the governance metadata that turns a table into something a
 * stranger can trust, edited where the table actually lives.
 */
export function DatasetCatalogPanel({ projectId, datasetId, columns }: DatasetCatalogPanelProps) {
  const [annotation, setAnnotation] = useState<CatalogAnnotation | null>(null);
  const [linked, setLinked] = useState<GlossaryTerm[]>([]);
  const [allTerms, setAllTerms] = useState<GlossaryTerm[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Draft edits, kept apart from the saved annotation so an unsaved change is
  // never mistaken for the stored value.
  const [description, setDescription] = useState("");
  const [tagsText, setTagsText] = useState("");
  const [owner, setOwner] = useState("");
  const [certified, setCertified] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const [termId, setTermId] = useState("");
  const [column, setColumn] = useState(columns[0] ?? "");
  const [linkBusy, setLinkBusy] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);

  const [pii, setPii] = useState<PiiScanResponse | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);

  const applyAnnotation = useCallback((note: CatalogAnnotation) => {
    setAnnotation(note);
    setDescription(note.description ?? "");
    setTagsText(note.tags.join(", "));
    setOwner(note.owner_username ?? "");
    setCertified(note.certified);
  }, []);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const [note, datasetTerms, glossary] = await Promise.all([
        apiFetch<CatalogAnnotation>(`/projects/${projectId}/catalog/${datasetId}`),
        apiFetch<TermListResponse>(
          `/projects/${projectId}/datasets/${datasetId}/glossary-terms`,
        ),
        apiFetch<TermListResponse>(`/projects/${projectId}/glossary`),
      ]);
      applyAnnotation(note);
      setLinked(datasetTerms.items);
      setAllTerms(glossary.items);
    } catch (caught) {
      setLoadError(extractErrorMessage(caught));
    }
  }, [projectId, datasetId, applyAnnotation]);

  useEffect(() => {
    void load();
  }, [load]);

  const dirty = useMemo(() => {
    if (!annotation) return false;
    const tags = parseTags(tagsText);
    return (
      description !== (annotation.description ?? "") ||
      owner !== (annotation.owner_username ?? "") ||
      certified !== annotation.certified ||
      tags.join(",") !== annotation.tags.join(",")
    );
  }, [annotation, description, owner, certified, tagsText]);

  const save = useCallback(async () => {
    if (!annotation) return;
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    try {
      // owner_username: "" clears the steward; the field is always sent so a
      // cleared owner actually persists.
      const payload: CatalogAnnotationUpdate = {
        description: description.trim() ? description.trim() : null,
        tags: parseTags(tagsText),
        certified,
        owner_username: owner.trim(),
      };
      const note = await apiFetch<CatalogAnnotation>(
        `/projects/${projectId}/catalog/${datasetId}`,
        { method: "PATCH", body: JSON.stringify(payload) },
      );
      applyAnnotation(note);
      setSaved(true);
    } catch (caught) {
      setSaveError(extractErrorMessage(caught));
    } finally {
      setSaving(false);
    }
  }, [annotation, projectId, datasetId, description, tagsText, certified, owner, applyAnnotation]);

  const linkTerm = useCallback(async () => {
    if (!termId || !column) return;
    setLinkBusy(true);
    setLinkError(null);
    try {
      const payload: DatasetTermLink = { term_id: termId, column };
      const updated = await apiFetch<GlossaryTerm>(
        `/projects/${projectId}/datasets/${datasetId}/glossary-terms`,
        { method: "POST", body: JSON.stringify(payload) },
      );
      setLinked((current) => [
        updated,
        ...current.filter((item) => item.id !== updated.id),
      ]);
      setTermId("");
    } catch (caught) {
      setLinkError(extractErrorMessage(caught));
    } finally {
      setLinkBusy(false);
    }
  }, [termId, column, projectId, datasetId]);

  const unlink = useCallback(
    async (term: GlossaryTerm, boundColumn: string) => {
      setLinkError(null);
      try {
        const updated = await apiFetch<GlossaryTerm>(
          `/projects/${projectId}/datasets/${datasetId}/glossary-terms/${term.id}?column=${encodeURIComponent(boundColumn)}`,
          { method: "DELETE" },
        );
        const stillHere = updated.bindings.some((b) => b.dataset_id === datasetId);
        setLinked((current) =>
          stillHere
            ? current.map((item) => (item.id === updated.id ? updated : item))
            : current.filter((item) => item.id !== updated.id),
        );
      } catch (caught) {
        setLinkError(extractErrorMessage(caught));
      }
    },
    [projectId, datasetId],
  );

  const scan = useCallback(async () => {
    setScanning(true);
    setScanError(null);
    try {
      // Deterministic pattern/checksum detection -- no model call reaches the
      // product runtime -- so a suggested classification always shows its basis.
      setPii(
        await apiFetch<PiiScanResponse>(
          `/projects/${projectId}/datasets/${datasetId}/pii`,
        ),
      );
    } catch (caught) {
      setScanError(extractErrorMessage(caught));
    } finally {
      setScanning(false);
    }
  }, [projectId, datasetId]);

  // The classification tags a scan implies: a `pii` umbrella, the distinct kinds
  // found, and `sensitive` for the kinds that carry real harm if they leak.
  const suggestedTags = useMemo(() => {
    if (!pii || pii.findings.length === 0) return [];
    const sensitiveKinds = new Set(["credit_card", "national_id", "date_of_birth"]);
    const tags = new Set<string>(["pii"]);
    for (const finding of pii.findings) {
      tags.add(finding.kind.replace(/_/g, "-"));
      if (sensitiveKinds.has(finding.kind)) tags.add("sensitive");
    }
    return [...tags];
  }, [pii]);

  // Suggestions already present in the draft tags do not need offering again.
  const newSuggestedTags = useMemo(() => {
    const current = new Set(parseTags(tagsText));
    return suggestedTags.filter((tag) => !current.has(tag));
  }, [suggestedTags, tagsText]);

  const addSuggestedTags = useCallback(() => {
    const merged = [...parseTags(tagsText), ...newSuggestedTags];
    setTagsText([...new Set(merged)].join(", "));
  }, [tagsText, newSuggestedTags]);

  // Only terms not already linked to a column of this dataset are worth offering.
  const linkableTerms = useMemo(
    () => allTerms.filter((term) => !linked.some((item) => item.id === term.id)),
    [allTerms, linked],
  );

  return (
    <SectionPanel
      title="Catalog"
      description="Ownership, certification, and the business vocabulary bound to this dataset — the metadata that lets someone who did not build it decide whether to trust it."
    >
      {loadError ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {loadError}
        </div>
      ) : null}

      {annotation ? (
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="space-y-3">
            <Field label="Description">
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={3}
                placeholder="What this dataset holds, and what it is safe to use it for."
                className="w-full rounded-lg border border-line bg-sunken px-3 py-2 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)]"
              />
            </Field>
            <Field label="Steward (username)">
              <input
                value={owner}
                onChange={(event) => setOwner(event.target.value)}
                placeholder="Nobody assigned"
                className="h-9 w-full rounded-lg border border-line bg-sunken px-3 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)]"
              />
            </Field>
            <Field label="Tags (comma-separated)">
              <input
                value={tagsText}
                onChange={(event) => setTagsText(event.target.value)}
                placeholder="finance, pii, gold"
                className="h-9 w-full rounded-lg border border-line bg-sunken px-3 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)]"
              />
            </Field>

            <div className="rounded-xl border border-line bg-sunken px-3 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] uppercase tracking-[0.14em] text-muted">
                  Data classification
                </span>
                <button
                  type="button"
                  onClick={() => void scan()}
                  disabled={scanning}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1 text-[11.5px] text-ink-3 transition hover:text-ink disabled:opacity-60"
                >
                  <Icon name="search" size={11} />
                  {scanning ? "Scanning…" : pii ? "Rescan" : "Scan for PII"}
                </button>
              </div>
              {pii ? (
                pii.findings.length === 0 ? (
                  <p className="mt-2 text-[12px] text-muted">
                    No personal data detected in the sampled values.
                  </p>
                ) : (
                  <div className="mt-2 space-y-2">
                    <ul className="space-y-1">
                      {pii.findings.map((finding) => (
                        <li
                          key={`${finding.column}-${finding.kind}`}
                          className="flex items-center justify-between gap-2 text-[12px]"
                        >
                          <span className="font-mono text-[11px] text-ink-2">
                            {finding.column}
                          </span>
                          <span className="text-ink-3">
                            {finding.label}{" "}
                            <span className="text-muted">({finding.confidence})</span>
                          </span>
                        </li>
                      ))}
                    </ul>
                    <p className="text-[10.5px] text-muted">{pii.method}.</p>
                    {newSuggestedTags.length > 0 ? (
                      <div className="flex flex-wrap items-center gap-1.5">
                        {newSuggestedTags.map((tag) => (
                          <span
                            key={tag}
                            className="rounded bg-surface-2 px-1.5 py-0.5 text-[10.5px] text-ink-3"
                          >
                            {tag}
                          </span>
                        ))}
                        <button
                          type="button"
                          onClick={addSuggestedTags}
                          className="rounded-lg bg-[color:var(--accent)] px-2 py-0.5 text-[11px] text-accent-ink transition"
                        >
                          Add as tags
                        </button>
                      </div>
                    ) : (
                      <p className="text-[11px] text-success">
                        Classification tags already applied.
                      </p>
                    )}
                  </div>
                )
              ) : (
                <p className="mt-2 text-[12px] text-muted">
                  Detect personal data and turn it into classification tags a policy can act on.
                </p>
              )}
              {scanError ? (
                <p className="mt-1.5 text-[11.5px] text-danger">{scanError}</p>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <button
                type="button"
                onClick={() => setCertified((current) => !current)}
                className={cx(
                  "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12px] transition",
                  certified
                    ? "bg-success-soft text-success"
                    : "border border-line text-ink-3 hover:text-ink",
                )}
              >
                <Icon name="check" size={12} />
                {certified ? "Certified" : "Mark certified"}
              </button>
              <div className="flex items-center gap-2">
                {saved && !dirty ? (
                  <span className="text-[11.5px] text-success">Saved</span>
                ) : null}
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => void save()}
                  disabled={saving || !dirty}
                >
                  {saving ? "Saving…" : "Save catalog"}
                </Button>
              </div>
            </div>
            {annotation.certified && annotation.certified_by_username ? (
              <p className="text-[11px] text-muted">
                Certified by {annotation.certified_by_username}
                {annotation.certified_at
                  ? ` on ${new Date(annotation.certified_at).toLocaleDateString()}`
                  : ""}
                .
              </p>
            ) : null}
            {saveError ? (
              <p className="text-[11.5px] text-danger">{saveError}</p>
            ) : null}
          </div>

          <div className="space-y-3">
            <div className="text-xs uppercase tracking-[0.18em] text-muted">Glossary terms</div>
            {linked.length === 0 ? (
              <p className="text-[12.5px] text-muted">
                No terms bound here yet. Binding a term to a column is how a name in this table
                gets a single, agreed meaning.
              </p>
            ) : (
              <ul className="space-y-2">
                {linked.map((term) => (
                  <li
                    key={term.id}
                    className="rounded-xl border border-line bg-surface px-3 py-2.5"
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-[13px] font-medium text-ink">{term.term}</span>
                    </div>
                    <p className="mt-0.5 line-clamp-2 text-[12px] text-ink-3">{term.definition}</p>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {term.bindings
                        .filter((binding) => binding.dataset_id === datasetId)
                        .map((binding) => (
                          <span
                            key={binding.column}
                            className="inline-flex items-center gap-1 rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[10.5px] text-ink-3"
                          >
                            {binding.column}
                            <button
                              type="button"
                              onClick={() => void unlink(term, binding.column)}
                              aria-label={`Unlink ${term.term} from ${binding.column}`}
                              className="text-muted transition hover:text-danger"
                            >
                              <Icon name="close" size={10} />
                            </button>
                          </span>
                        ))}
                    </div>
                  </li>
                ))}
              </ul>
            )}

            {columns.length > 0 && linkableTerms.length > 0 ? (
              <div className="rounded-xl border border-line bg-sunken px-3 py-3">
                <div className="flex flex-wrap items-end gap-2">
                  <label className="flex-1 space-y-1">
                    <span className="text-[11px] text-muted">Term</span>
                    <select
                      value={termId}
                      onChange={(event) => setTermId(event.target.value)}
                      className="h-9 w-full rounded-lg border border-line bg-surface px-2 text-[12.5px] text-ink outline-none transition focus:border-[color:var(--accent)]"
                    >
                      <option value="">Choose a term…</option>
                      {linkableTerms.map((term) => (
                        <option key={term.id} value={term.id}>
                          {term.term}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex-1 space-y-1">
                    <span className="text-[11px] text-muted">Column</span>
                    <select
                      value={column}
                      onChange={(event) => setColumn(event.target.value)}
                      className="h-9 w-full rounded-lg border border-line bg-surface px-2 text-[12.5px] text-ink outline-none transition focus:border-[color:var(--accent)]"
                    >
                      {columns.map((name) => (
                        <option key={name} value={name}>
                          {name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => void linkTerm()}
                    disabled={linkBusy || !termId || !column}
                  >
                    Link
                  </Button>
                </div>
              </div>
            ) : null}
            {linkError ? <p className="text-[11.5px] text-danger">{linkError}</p> : null}
          </div>
        </div>
      ) : loadError ? null : (
        <p className="text-[12.5px] text-muted">Loading catalog…</p>
      )}
    </SectionPanel>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-[11px] uppercase tracking-[0.14em] text-muted">{label}</span>
      {children}
    </label>
  );
}

function parseTags(text: string): string[] {
  const seen = new Set<string>();
  for (const raw of text.split(",")) {
    const tag = raw.trim().toLowerCase();
    if (tag) seen.add(tag);
  }
  return [...seen];
}
