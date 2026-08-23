"use client";

import Link from "next/link";
import { useCallback, useState } from "react";

import type {
  AuthUser,
  Confidence,
  DescribeResponse,
  DocumentationResponse,
  DuplicateResponse,
  PiiScanResponse,
  RuleSuggestionResponse,
} from "@platform/shared-types";
import { Button, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";

type AssistantPageProps = {
  currentUser: AuthUser;
  projectId: string;
  datasetId: string;
  datasetName: string;
  columns: string[];
  pii: PiiScanResponse | null;
  rules: RuleSuggestionResponse | null;
  documentation: DocumentationResponse | null;
};

const CONFIDENCE_TONE: Record<Confidence, string> = {
  high: "border-danger-line bg-danger-soft text-danger",
  medium: "border-warning-line bg-warning-soft text-warning",
  low: "border-line bg-surface-2 text-ink-3",
};

const inputClass =
  "h-9 w-full rounded-lg border border-line bg-sunken px-2.5 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)]";

export function AssistantPageView({
  currentUser,
  projectId,
  datasetId,
  datasetName,
  columns,
  pii,
  rules,
  documentation,
}: AssistantPageProps) {
  const [sentence, setSentence] = useState("");
  const [parsed, setParsed] = useState<DescribeResponse | null>(null);
  const [duplicateColumn, setDuplicateColumn] = useState(columns[0] ?? "");
  const [duplicates, setDuplicates] = useState<DuplicateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const describe = useCallback(async () => {
    if (!sentence.trim()) return;
    setBusy("describe");
    setError(null);
    try {
      setParsed(
        await apiFetch<DescribeResponse>(`/projects/${projectId}/describe`, {
          method: "POST",
          body: JSON.stringify({ dataset_id: datasetId, sentence: sentence.trim() }),
        }),
      );
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(null);
    }
  }, [projectId, datasetId, sentence]);

  const scanDuplicates = useCallback(async () => {
    if (!duplicateColumn) return;
    setBusy("duplicates");
    setError(null);
    try {
      setDuplicates(
        await apiFetch<DuplicateResponse>(
          `/projects/${projectId}/datasets/${datasetId}/duplicates`,
          { method: "POST", body: JSON.stringify({ column: duplicateColumn }) },
        ),
      );
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(null);
    }
  }, [projectId, datasetId, duplicateColumn]);

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Intelligence"
      title={`Assistant · ${datasetName}`}
      subtitle="Everything here is worked out from the data itself — patterns, overlap, similarity, and timing. There are no model calls, and each panel says what produced its answer."
    >
      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <Link
          href={`/projects/${projectId}/datasets/${datasetId}`}
          className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1.5 text-[12px] text-ink-2 transition hover:bg-surface-2"
        >
          <Icon name="chevronLeft" size={12} />
          Dataset
        </Link>
      </div>

      <SectionPanel
        title="Describe what you want"
        description="Type the change in words. It recognises a fixed set of phrasings and says plainly what it could not read, rather than guessing."
      >
        <div className="flex gap-2">
          <input
            value={sentence}
            onChange={(event) => setSentence(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void describe();
            }}
            placeholder="total amount by region, then sort by amount descending"
            className={inputClass}
          />
          <Button onClick={describe} disabled={busy !== null || !sentence.trim()}>
            {busy === "describe" ? "Reading…" : "Build"}
          </Button>
        </div>

        {parsed ? (
          <div className="mt-3">
            <p
              className={cx(
                "rounded-lg border px-3 py-2.5 text-[12.5px]",
                parsed.complete
                  ? "border-success-line bg-success-soft text-success"
                  : "border-warning-line bg-warning-soft text-warning",
              )}
            >
              {parsed.summary}
            </p>
            {parsed.understood.length > 0 ? (
              <ol className="mt-2 space-y-1.5">
                {parsed.understood.map((intent, index) => (
                  <li
                    key={`${intent.action}-${index}`}
                    className="rounded-lg border border-line px-2.5 py-2"
                  >
                    <div className="flex items-baseline gap-2">
                      <span className="text-[10.5px] uppercase tracking-wide text-muted">
                        {index + 1}
                      </span>
                      <span className="text-[12.5px] text-ink">{intent.explanation}</span>
                    </div>
                    <div className="mt-0.5 pl-5 font-mono text-[10.5px] text-muted">
                      {intent.action}
                    </div>
                  </li>
                ))}
              </ol>
            ) : null}
            <p className="mt-2 text-[11px] text-muted">{parsed.method}</p>
          </div>
        ) : (
          <p className="mt-2 text-[11.5px] text-muted">
            Try “keep only rows where channel is web”, “remove duplicates and drop notes”, or
            “average amount by region”.
          </p>
        )}
      </SectionPanel>

      <div className="grid gap-4 lg:grid-cols-2">
        <SectionPanel
          title="Personal data"
          description={pii?.summary ?? "Not scanned."}
        >
          {!pii || pii.findings.length === 0 ? (
            <p className="text-[12.5px] text-muted">
              Nothing here looks like personal data. Known formats only — an unusual national
              ID format would be missed.
            </p>
          ) : (
            <ul className="space-y-2">
              {pii.findings.map((finding) => (
                <li
                  key={finding.column}
                  className="rounded-lg border border-line bg-surface px-3 py-2.5"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <span className="font-mono text-[12.5px] text-ink">{finding.column}</span>
                      <span className="ml-2 text-[12px] text-ink-3">{finding.label}</span>
                    </div>
                    <span
                      className={cx(
                        "shrink-0 rounded-full border px-2 py-0.5 text-[10.5px]",
                        CONFIDENCE_TONE[finding.confidence],
                      )}
                    >
                      {finding.confidence}
                    </span>
                  </div>
                  <p className="mt-1 text-[11.5px] text-ink-3">{finding.reason}</p>
                  <p className="mt-1 text-[11px] text-muted">
                    Suggested: {finding.suggested_strategy} — {finding.guidance}
                  </p>
                </li>
              ))}
            </ul>
          )}
          {pii ? <p className="mt-2 text-[11px] text-muted">{pii.method}</p> : null}
        </SectionPanel>

        <SectionPanel
          title="Quality rules worth adding"
          description={rules?.summary ?? "Not analysed."}
        >
          {!rules || rules.items.length === 0 ? (
            <p className="text-[12.5px] text-muted">
              Nothing in this profile is a strong enough pattern to assert on yet.
            </p>
          ) : (
            <ul className="space-y-2">
              {rules.items.map((rule) => (
                <li
                  key={rule.name}
                  className="rounded-lg border border-line bg-surface px-3 py-2.5"
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-[12.5px] text-ink">{rule.name}</span>
                    <span
                      className={cx(
                        "shrink-0 rounded-full border px-2 py-0.5 text-[10.5px]",
                        CONFIDENCE_TONE[rule.confidence],
                      )}
                    >
                      {rule.confidence}
                    </span>
                  </div>
                  <p className="mt-1 text-[11.5px] leading-4 text-ink-3">{rule.rationale}</p>
                </li>
              ))}
            </ul>
          )}
        </SectionPanel>
      </div>

      <SectionPanel
        title="The same thing written differently"
        description="Fuzzy matching over one column. Nothing is merged; these are candidates for someone to confirm."
        actions={
          <div className="flex items-center gap-2">
            <select
              value={duplicateColumn}
              onChange={(event) => setDuplicateColumn(event.target.value)}
              className={cx(inputClass, "w-[180px]")}
            >
              {columns.map((column) => (
                <option key={column} value={column}>
                  {column}
                </option>
              ))}
            </select>
            <Button variant="secondary" onClick={scanDuplicates} disabled={busy !== null}>
              {busy === "duplicates" ? "Looking…" : "Look"}
            </Button>
          </div>
        }
      >
        {!duplicates ? (
          <p className="text-[12.5px] text-muted">
            Pick a column of names or codes and look for variants.
          </p>
        ) : (
          <>
            <p className="rounded-lg border border-line bg-surface px-3 py-2.5 text-[12.5px] text-ink">
              {duplicates.summary}
            </p>
            {duplicates.candidates.length > 0 ? (
              <ul className="mt-2 space-y-1.5">
                {duplicates.candidates.map((candidate, index) => (
                  <li
                    key={`${candidate.left_value}-${index}`}
                    className="flex flex-wrap items-center gap-2 rounded-lg border border-line px-2.5 py-2 text-[12px]"
                  >
                    <span className="text-ink">{candidate.left_value}</span>
                    <span className="text-muted">≈</span>
                    <span className="text-ink">{candidate.right_value}</span>
                    <span className="ml-auto text-[10.5px] text-muted">
                      {candidate.reason}
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}
            <p className="mt-2 text-[11px] text-muted">
              {duplicates.comparisons} comparison(s) after blocking.
            </p>
          </>
        )}
      </SectionPanel>

      {documentation ? (
        <SectionPanel
          title="A description, drafted"
          description="Assembled from facts already recorded. Edit it before accepting — a generated description presented as authoritative is how a catalog fills with confidently wrong text."
        >
          <p className="rounded-lg border border-line bg-surface px-3 py-2.5 text-[12.5px] leading-5 text-ink">
            {documentation.dataset.text}
          </p>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {documentation.dataset.facts_used.map((fact) => (
              <span key={fact} className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-muted">
                from {fact}
              </span>
            ))}
          </div>

          {documentation.columns.length > 0 ? (
            <ul className="mt-3 space-y-1.5">
              {documentation.columns.slice(0, 12).map((column) => (
                <li key={column.subject} className="rounded-lg border border-line px-2.5 py-2">
                  <span className="font-mono text-[12px] text-ink">{column.subject}</span>
                  <p className="mt-0.5 text-[11.5px] leading-4 text-ink-3">{column.text}</p>
                </li>
              ))}
            </ul>
          ) : null}
        </SectionPanel>
      ) : null}
    </AppShell>
  );
}
