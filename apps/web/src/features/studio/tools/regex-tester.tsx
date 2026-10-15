"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { countOf } from "@/lib/format";
import { cx } from "@/lib/utils";

/** Values of a column of the source, to try a pattern on (E1). */
type Samples = (column: string | null) => string[];

const SamplesContext = createContext<Samples>(() => []);

export function SampleValuesProvider({ samples, children }: { samples: Samples; children: React.ReactNode }) {
  return <SamplesContext.Provider value={samples}>{children}</SamplesContext.Provider>;
}

type Result = { value: string; matched: boolean; spans: number[][]; groups: string[]; replaced: string | null };
type Response = { valid: boolean; error: string | null; results: Result[] };

/**
 * Try a pattern on sample values before the step runs. The server answers,
 * with the same regular expressions a run uses (Python's), which differ from
 * a browser's in places.
 */
export function RegexTester({
  pattern,
  replacement,
  column,
}: {
  pattern: string;
  /** For a replacing tool: what each match becomes. */
  replacement?: string | null;
  column: string | null;
}) {
  const samples = useContext(SamplesContext);
  const [open, setOpen] = useState(false);
  const offered = useMemo(() => samples(column).slice(0, 8), [samples, column]);
  const [values, setValues] = useState<string | null>(null);
  const [answer, setAnswer] = useState<Response | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const text = values ?? offered.join("\n");

  useEffect(() => {
    if (!open || !pattern) {
      setAnswer(null);
      return;
    }
    const lines = text.split("\n").filter((line) => line !== "");
    let cancelled = false;
    const timer = setTimeout(() => {
      apiFetch<Response>("/transformations/tools/regex/test", {
        method: "POST",
        body: JSON.stringify({ pattern, values: lines.slice(0, 50), replacement: replacement ?? null }),
      })
        .then((response) => {
          if (cancelled) return;
          setAnswer(response);
          setProblem(null);
        })
        .catch((caught) => {
          if (!cancelled) setProblem(extractErrorMessage(caught));
        });
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [open, pattern, replacement, text]);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="self-start text-[12.5px] text-[color:var(--accent-muted)] hover:underline"
      >
        Try the pattern on some values
      </button>
    );
  }
  const matched = answer?.results.filter((result) => result.matched).length ?? 0;
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-line bg-surface p-2.5">
      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted">
          Values to try, one per line{offered.length && values === null ? ", from the source" : ""}
        </span>
        <textarea
          value={text}
          onChange={(event) => setValues(event.target.value)}
          rows={3}
          spellCheck={false}
          className="w-full rounded-lg border border-line bg-sunken px-2.5 py-1.5 font-mono text-[12px] text-ink outline-none focus:border-[color:var(--accent)]"
        />
      </label>
      {problem ? <p className="text-[12.5px] text-danger">{problem}</p> : null}
      {!pattern ? (
        <p className="text-[12.5px] text-muted">Write a pattern to try it.</p>
      ) : answer && !answer.valid ? (
        <p className="text-[12.5px] text-danger">{answer.error}</p>
      ) : answer ? (
        <>
          <p className="text-[12.5px] text-ink-3">
            Matches {matched} of {countOf(answer.results.length, "value")}.
          </p>
          <ul className="space-y-1">
            {answer.results.map((result, index) => (
              <li key={index} className="font-mono text-[12px] leading-5">
                <Marked value={result.value} spans={result.spans} />
                {result.replaced !== null && result.replaced !== result.value ? (
                  <span className="text-ink-3"> → {result.replaced || "(empty)"}</span>
                ) : null}
                {result.groups.length ? (
                  <span className="text-ink-3"> · groups: {result.groups.map((group) => group || "(empty)").join(", ")}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <button type="button" onClick={() => setOpen(false)} className="self-start text-[12px] text-ink-3 hover:text-ink">
        Close the tester
      </button>
    </div>
  );
}

/** A value with what the pattern matched highlighted. */
function Marked({ value, spans }: { value: string; spans: number[][] }) {
  const parts: { text: string; hit: boolean }[] = [];
  let at = 0;
  for (const [start, end] of spans) {
    if (start > at) parts.push({ text: value.slice(at, start), hit: false });
    // An empty match marks a place, not text.
    if (end > start) parts.push({ text: value.slice(start, end), hit: true });
    at = Math.max(at, end);
  }
  if (at < value.length) parts.push({ text: value.slice(at), hit: false });
  return (
    <span className="text-ink">
      {parts.map((part, index) => (
        <span key={index} className={cx(part.hit ? "rounded bg-[color:var(--accent-soft)] px-0.5" : null)}>
          {part.text}
        </span>
      ))}
    </span>
  );
}

/** A column's type, in the words a schema check takes. */
export function schemaWord(type: string | undefined): string {
  const lowered = (type ?? "").toLowerCase();
  if (/^(u?int\d*|integer|bigint|smallint|float\d*|double|decimal|numeric|number|real)\b/.test(lowered)) return "number";
  // As the schema check counts them: an interval is temporal too.
  if (/^(date|time|interval)/.test(lowered)) return "date";
  if (/^bool/.test(lowered)) return "true or false";
  return "text";
}
