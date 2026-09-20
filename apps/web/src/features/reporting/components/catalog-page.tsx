"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import type {
  AuthUser,
  CatalogSearchResponse,
  GlossaryTerm,
  TermListResponse,
} from "@platform/shared-types";
import { SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { DeleteRowButton } from "@/components/ui/delete-row-button";
import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";

type CatalogPageProps = {
  currentUser: AuthUser;
  projectId: string;
  initial: CatalogSearchResponse;
  terms: TermListResponse;
};

export function CatalogPageView({
  currentUser,
  projectId,
  initial,
  terms: initialTerms,
}: CatalogPageProps) {
  // Local so a deleted term leaves the list without a reload.
  const [terms, setTerms] = useState(initialTerms);
  const [query, setQuery] = useState("");
  const [certifiedOnly, setCertifiedOnly] = useState(false);
  const [tag, setTag] = useState<string | null>(null);
  const [results, setResults] = useState(initial);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const params = new URLSearchParams();
      if (query.trim()) params.set("q", query.trim());
      if (certifiedOnly) params.set("certified_only", "true");
      if (tag) params.set("tag", tag);
      setResults(
        await apiFetch<CatalogSearchResponse>(
          `/projects/${projectId}/catalog?${params.toString()}`,
        ),
      );
    } catch (caught) {
      setError(extractErrorMessage(caught));
    }
  }, [projectId, query, certifiedOnly, tag]);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 200);
    return () => clearTimeout(timer);
  }, [load]);

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Consumption"
      title="Catalog"
      subtitle="Search across every dataset by name, column, tag, or what somebody wrote about it — because people remember a column far more often than they remember what a table was called."
    >
      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-3">
        <Stat value={results.total_datasets} label="Datasets" />
        <Stat value={results.certified_count} label="Certified" tone="text-success" />
        <Stat value={terms.items.length} label="Glossary terms" tone="text-accent" />
      </div>

      <SectionPanel title="Find something">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[240px] flex-1">
            <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted">
              <Icon name="search" size={13} />
            </span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="orders, email, revenue…"
              className="h-9 w-full rounded-lg border border-line bg-sunken pl-8 pr-3 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)]"
            />
          </div>
          <button
            type="button"
            onClick={() => setCertifiedOnly((current) => !current)}
            className={cx(
              "rounded-lg px-2.5 py-1.5 text-[12px] transition",
              certifiedOnly
                ? "bg-[color:var(--accent)] text-accent-ink"
                : "border border-line text-ink-3 hover:text-ink",
            )}
          >
            Certified only
          </button>
        </div>

        {results.tags.length > 0 ? (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {results.tags.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setTag((current) => (current === item ? null : item))}
                className={cx(
                  "rounded px-2 py-0.5 text-[11px] transition",
                  tag === item
                    ? "bg-[color:var(--accent)] text-accent-ink"
                    : "bg-surface-2 text-ink-3 hover:text-ink",
                )}
              >
                {item}
              </button>
            ))}
          </div>
        ) : null}

        <ul className="mt-3 space-y-2">
          {results.items.length === 0 ? (
            <li className="rounded-xl border border-line px-4 py-8 text-center text-[12.5px] text-muted">
              Nothing matched. Try a column name.
            </li>
          ) : (
            results.items.map((hit) => (
              <li
                key={hit.dataset_id}
                className="relative rounded-xl border border-line bg-surface px-3.5 py-3 transition hover:border-line-strong"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <Link
                      href={`/projects/${projectId}/datasets/${hit.dataset_id}`}
                      className="text-[13.5px] font-medium text-ink after:absolute after:inset-0 after:content-['']"
                    >
                      {hit.name}
                    </Link>
                    {hit.description ? (
                      <p className="mt-0.5 line-clamp-2 text-[12px] text-ink-3">
                        {hit.description}
                      </p>
                    ) : null}
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
                      {hit.reasons.slice(0, 3).map((reason) => (
                        <span key={reason} className="rounded bg-surface px-1.5 py-0.5">
                          {reason}
                        </span>
                      ))}
                      {hit.row_count !== null ? (
                        <span>{hit.row_count.toLocaleString()} rows</span>
                      ) : null}
                    </div>
                    {hit.matched_columns.length > 0 ? (
                      <div className="mt-1 font-mono text-[10.5px] text-muted">
                        {hit.matched_columns.join(", ")}
                      </div>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    {hit.certified ? (
                      <span className="inline-flex items-center gap-1 rounded-full border border-success-line bg-success-soft px-2 py-0.5 text-[10.5px] text-success">
                        <Icon name="check" size={10} />
                        certified
                      </span>
                    ) : null}
                    {hit.owner ? (
                      <span className="text-[11px] text-muted">{hit.owner}</span>
                    ) : null}
                  </div>
                </div>
              </li>
            ))
          )}
        </ul>
      </SectionPanel>

      <SectionPanel
        title="Glossary"
        description="What a word means here, bound to the columns that hold it — so 'revenue' means one thing."
      >
        {terms.items.length === 0 ? (
          <p className="text-[12.5px] text-muted">
            No terms defined yet. A glossary earns its keep the first time two people disagree
            about a number.
          </p>
        ) : (
          <ul className="space-y-2">
            {terms.items.map((term) => (
              <TermRow
                key={term.id}
                projectId={projectId}
                term={term}
                onDeleted={() =>
                  setTerms((current) => ({
                    ...current,
                    items: current.items.filter((item) => item.id !== term.id),
                  }))
                }
              />
            ))}
          </ul>
        )}
      </SectionPanel>
    </AppShell>
  );
}

function TermRow({
  projectId,
  term,
  onDeleted,
}: {
  projectId: string;
  term: GlossaryTerm;
  onDeleted: () => void;
}) {
  return (
    <li className="rounded-xl border border-line bg-surface px-3.5 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-[13.5px] font-medium text-ink">{term.term}</span>
        <div className="flex items-center gap-2">
          {term.owner_username ? (
            <span className="text-[11px] text-muted">{term.owner_username}</span>
          ) : null}
          <DeleteRowButton
            path={`/projects/${projectId}/glossary/${term.id}`}
            name={term.term}
            kind="glossary term"
            consequences={["Columns bound to it keep their data; they stop being described by it."]}
            onDeleted={onDeleted}
            className="rounded-lg p-1 text-muted transition hover:text-danger"
          />
        </div>
      </div>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">{term.definition}</p>
      {term.bindings.length > 0 ? (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {term.bindings.map((binding) => (
            <span
              key={`${binding.dataset_id}-${binding.column}`}
              className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[10.5px] text-ink-3"
            >
              {binding.column}
            </span>
          ))}
        </div>
      ) : null}
      {term.synonyms.length > 0 ? (
        <div className="mt-1 text-[11px] text-muted">
          also called {term.synonyms.join(", ")}
        </div>
      ) : null}
    </li>
  );
}

function Stat({ value, label, tone }: { value: number; label: string; tone?: string }) {
  return (
    <div className="rounded-2xl border border-line bg-surface px-4 py-3">
      <div className={cx("text-2xl font-semibold", tone ?? "text-ink")}>{value}</div>
      <div className="mt-0.5 text-[12px] text-muted">{label}</div>
    </div>
  );
}
