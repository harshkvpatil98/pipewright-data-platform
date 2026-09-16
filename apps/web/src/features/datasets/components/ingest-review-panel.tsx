"use client";

import type {
  AnalyseUploadResponse,
  IngestFinding,
  IngestSpec,
} from "@platform/shared-types";
import { Select } from "@platform/shared-ui";

import {
  CERTAINTY_LABEL,
  CERTAINTY_TONE,
  COLUMN_TYPES,
  answerQuestion,
  blockingQuestions,
  columnOf,
  confidenceLabel,
  editColumn,
  reviewableFindings,
  settledFindings,
  stageLabel,
} from "@/features/datasets/ingest-review";
import { cx } from "@/lib/utils";

type Props = {
  analysis: AnalyseUploadResponse;
  spec: IngestSpec;
  onSpecChange: (spec: IngestSpec) => void;
};

/**
 * What the file turned out to be, before any of it is stored.
 *
 * The ordering is the argument: the questions the file cannot answer come
 * first and are unmissable, the guesses worth a glance come second, and the
 * things it worked out for certain are last and collapsed. A panel that listed
 * all three the same way would train people to skim past the one that matters.
 */
export function IngestReviewPanel({ analysis, spec, onSpecChange }: Props) {
  const questions = blockingQuestions(analysis);
  const worthAGlance = reviewableFindings(analysis);
  const settled = settledFindings(analysis);

  return (
    <div className="space-y-4">
      {analysis.matched_spec ? (
        <div className="rounded-2xl border border-info-line bg-info-soft px-4 py-3 text-sm text-info">
          Read the way <strong>{analysis.matched_spec.label}</strong> says to — a saved
          setting used {analysis.matched_spec.use_count} time
          {analysis.matched_spec.use_count === 1 ? "" : "s"} before. Change anything below
          and it applies to this file only unless you save it again.
        </div>
      ) : null}

      {questions.length > 0 ? (
        <section className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3">
          <h4 className="text-sm font-semibold text-danger">
            {questions.length} question{questions.length === 1 ? "" : "s"} only you can answer
          </h4>
          <p className="mt-1 text-[12.5px] leading-5 text-danger">
            The file genuinely does not say. Nothing is imported until these are settled —
            guessing would produce a table that looks right and is not.
          </p>
          <ul className="mt-3 space-y-3">
            {questions.map((question, index) => (
              <li key={`${question.stage}-${index}`} className="rounded-xl bg-surface px-3 py-3">
                <div className="text-[12.5px] leading-5 text-ink">{question.reason}</div>
                {question.evidence.length > 0 ? (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {question.evidence.slice(0, 5).map((value) => (
                      <code
                        key={value}
                        className="rounded border border-line bg-sunken px-1.5 py-0.5 text-[11px] text-ink-2"
                      >
                        {value}
                      </code>
                    ))}
                  </div>
                ) : null}
                {question.candidates.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {question.candidates.map((candidate) => (
                      <button
                        key={String(candidate.value)}
                        type="button"
                        onClick={() =>
                          onSpecChange(answerQuestion(spec, question, candidate.value))
                        }
                        className="rounded-lg border border-line bg-surface px-2.5 py-1 text-[12px] text-ink transition hover:border-line-strong hover:bg-surface-2"
                      >
                        {candidate.reason}
                      </button>
                    ))}
                  </div>
                ) : null}
                {columnOf(question) ? (
                  <p className="mt-1.5 text-[11px] text-muted">
                    Answering sets the type of <code>{columnOf(question)}</code> below.
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {worthAGlance.length > 0 ? (
        <section className="rounded-2xl border border-line bg-surface px-4 py-3">
          <h4 className="text-sm font-semibold text-ink">Worth a look</h4>
          <ul className="mt-2 space-y-2">
            {worthAGlance.map((item, index) => (
              <li key={`${item.stage}-${index}`} className="text-[12.5px] leading-5 text-ink-2">
                <Badge finding={item} /> {item.reason}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <details className="rounded-2xl border border-line bg-surface px-4 py-3">
        <summary className="cursor-pointer text-sm font-semibold text-ink">
          What it worked out ({settled.length})
        </summary>
        <ul className="mt-2 space-y-1.5">
          {settled.map((item, index) => (
            <li key={`${item.stage}-${index}`} className="text-[12.5px] leading-5 text-ink-3">
              <span className="text-ink-2">{stageLabel(item.stage)}:</span> {item.reason}
            </li>
          ))}
        </ul>
      </details>

      <section>
        <h4 className="mb-2 text-sm font-semibold text-ink">Columns</h4>
        <p className="mb-2 text-[12px] text-ink-3">
          Every type here is a decision you can change before anything is stored.
        </p>
        <div className="overflow-x-auto rounded-2xl border border-line">
          <table className="w-full text-left text-[12.5px]">
            <thead className="bg-surface-2 text-[11px] uppercase tracking-[0.14em] text-muted">
              <tr>
                <th className="cell-pad">Include</th>
                <th className="cell-pad">Column</th>
                <th className="cell-pad">Read as</th>
                <th className="cell-pad">Why</th>
              </tr>
            </thead>
            <tbody className="text-ink-2">
              {spec.columns.map((column) => {
                const detail = analysis.analysis.columns.find(
                  (item) => item.name === column.name,
                );
                return (
                  <tr key={column.name} className="border-t border-line align-top">
                    <td className="cell-pad">
                      <input
                        type="checkbox"
                        checked={column.include}
                        aria-label={`Include ${column.name}`}
                        onChange={(event) =>
                          onSpecChange(
                            editColumn(spec, column.name, { include: event.target.checked }),
                          )
                        }
                      />
                    </td>
                    <td className="cell-pad text-ink">{column.name}</td>
                    <td className="cell-pad">
                      <Select
                        aria-label={`Type of ${column.name}`}
                        value={
                          COLUMN_TYPES.includes(column.type as (typeof COLUMN_TYPES)[number])
                            ? column.type
                            : "string"
                        }
                        onChange={(event) =>
                          onSpecChange(
                            editColumn(spec, column.name, { type: event.target.value }),
                          )
                        }
                      >
                        {COLUMN_TYPES.map((type) => (
                          <option key={type} value={type}>
                            {type}
                          </option>
                        ))}
                        {COLUMN_TYPES.includes(
                          column.type as (typeof COLUMN_TYPES)[number],
                        ) ? null : (
                          <option value={column.type}>{column.type}</option>
                        )}
                      </Select>
                    </td>
                    <td className="cell-pad">
                      {detail ? (
                        <>
                          <Badge finding={detail.finding} /> {detail.finding.reason}
                          {detail.rejected.length > 0 ? (
                            <div className="mt-1 text-[11.5px] text-warning">
                              Did not fit:{" "}
                              {detail.rejected
                                .slice(0, 3)
                                .map((item) => `${item.value} (${item.count})`)
                                .join(", ")}
                            </div>
                          ) : null}
                        </>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {analysis.conversion_notes.length > 0 ? (
        <section className="rounded-2xl border border-warning-line bg-warning-soft px-4 py-3">
          <h4 className="text-sm font-semibold text-warning">While converting the preview</h4>
          <ul className="mt-1.5 space-y-1">
            {analysis.conversion_notes.map((note) => (
              <li key={note} className="text-[12.5px] leading-5 text-warning">
                {note}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {analysis.analysis.warnings.length > 0 ? (
        <ul className="space-y-1">
          {analysis.analysis.warnings.map((warning) => (
            <li key={warning} className="text-[12.5px] leading-5 text-muted">
              {warning}
            </li>
          ))}
        </ul>
      ) : null}

      <section>
        <h4 className="mb-2 text-sm font-semibold text-ink">
          Preview — the first {analysis.preview.rows.length} row
          {analysis.preview.rows.length === 1 ? "" : "s"}, read the way above
        </h4>
        <div className="max-h-64 overflow-auto rounded-2xl border border-line">
          <table className="w-full text-left text-[12px]">
            <thead className="sticky top-0 bg-surface-2 text-[11px] uppercase tracking-[0.14em] text-muted">
              <tr>
                {analysis.preview.columns.map((name) => (
                  <th key={name} className="cell-pad whitespace-nowrap">
                    {name}
                    <span className="ml-1.5 normal-case tracking-normal text-ink-3">
                      {analysis.preview.dtypes[name]}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="text-ink-2">
              {analysis.preview.rows.slice(0, 50).map((row, index) => (
                <tr key={index} className="border-t border-line">
                  {analysis.preview.columns.map((name) => (
                    <td key={name} className="cell-pad whitespace-nowrap">
                      {row[name] === null || row[name] === undefined ? (
                        <span className="text-muted">—</span>
                      ) : (
                        String(row[name])
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function Badge({ finding }: { finding: IngestFinding }) {
  return (
    <span
      title={confidenceLabel(finding)}
      className={cx(
        "mr-1.5 inline-flex rounded-full border px-1.5 py-0.5 text-[10.5px]",
        CERTAINTY_TONE[finding.certainty],
      )}
    >
      {CERTAINTY_LABEL[finding.certainty]}
    </span>
  );
}
