"use client";

import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";

import { toConfig, type Tool } from "./tool-catalogue";

type Preview = { columns: string[]; rows: Record<string, unknown>[]; warnings: string[] };

/** How many of the loaded rows to send. Enough to see the shape, few enough to be instant. */
const SAMPLE = 5;

/** Wait this long after the last keystroke before asking the server. */
const SETTLE_MS = 250;

/**
 * What this tool would do to the rows already on screen.
 *
 * Sent from the rows the Studio has loaded rather than re-read from storage:
 * this runs on every keystroke in the settings, and a file read per keystroke
 * is the difference between a preview people watch and one they turn off.
 */
export function ToolPreview({
  tool,
  column,
  into,
  values,
  rows,
}: {
  tool: Tool;
  column: string | null;
  into: string;
  values: Record<string, unknown>;
  rows: Record<string, unknown>[];
}) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const sample = rows.slice(0, SAMPLE);
  const config = toConfig(tool, column, into, values);
  // Serialised so the effect re-runs on a real change rather than on every
  // render, which is what a fresh object identity would cause.
  const key = JSON.stringify({ config, sample });

  useEffect(() => {
    if (sample.length === 0 || (tool.column_scoped && !column)) {
      setPreview(null);
      setProblem(null);
      return;
    }
    let cancelled = false;
    setPending(true);
    const timer = setTimeout(() => {
      const { tool: name, column: target, into: destination, ...params } = config;
      apiFetch<Preview>("/transformations/tools/preview", {
        method: "POST",
        body: JSON.stringify({
          tool: name,
          column: target ?? null,
          into: destination ?? null,
          params,
          rows: sample,
        }),
      })
        .then((response) => {
          if (cancelled) return;
          setPreview(response);
          setProblem(null);
        })
        .catch((error) => {
          if (cancelled) return;
          setPreview(null);
          // A half-filled form is the normal state while somebody is typing, so
          // the message is shown quietly rather than as a failure.
          setProblem(extractErrorMessage(error));
        })
        .finally(() => {
          if (!cancelled) setPending(false);
        });
    }, SETTLE_MS);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // Keyed on the serialised request rather than its parts: `config` and
    // `sample` are fresh objects every render, so listing them would re-fire
    // the effect -- and cancel the in-flight request -- on every keystroke
    // anywhere on the page.
  }, [key]);

  if (sample.length === 0) return null;

  const target = into.trim() || column;

  return (
    <section className="mt-5" aria-live="polite">
      <h3 className="mb-2 text-xs uppercase tracking-[0.14em] text-muted">
        On your data {pending ? "· working…" : ""}
      </h3>
      {problem ? (
        <p className="rounded-lg border border-line bg-sunken px-3 py-2 text-xs text-muted">
          {problem}
        </p>
      ) : preview && !tool.column_scoped ? (
        // A filter or a dedupe has no "before and after" cell; what it does is
        // change how many rows there are, so that is what gets shown.
        <p className="rounded-lg border border-line bg-sunken px-3 py-2 text-xs text-ink">
          {preview.rows.length} of the {sample.length} rows shown would remain
          {preview.columns.length !== Object.keys(sample[0] ?? {}).length
            ? `, with ${preview.columns.length} column${preview.columns.length === 1 ? "" : "s"}`
            : ""}
          .
        </p>
      ) : preview && target ? (
        <>
          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-line text-left text-muted">
                  <th className="cell-pad font-normal">{column}</th>
                  <th className="cell-pad font-normal">{target}</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row, index) => (
                  <tr key={index} className="border-b border-line last:border-0">
                    <td className="cell-pad font-mono text-ink-2">
                      {render(sample[index]?.[column ?? ""])}
                    </td>
                    <td className="cell-pad font-mono text-ink">{render(row[target])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {preview.warnings.map((warning) => (
            <p key={warning} className="mt-2 text-xs text-[color:var(--warning)]">
              {warning}
            </p>
          ))}
        </>
      ) : null}
    </section>
  );
}

function render(value: unknown): string {
  if (value === null || value === undefined) return "empty";
  if (value === "") return "blank";
  return String(value);
}
