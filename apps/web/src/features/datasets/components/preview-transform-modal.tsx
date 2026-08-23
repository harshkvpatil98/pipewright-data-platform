"use client";

import { useMemo, useState } from "react";

import type { TransformationPreviewResponse, TransformationStep } from "@platform/shared-types";
import { Button, FormField, Modal, Textarea } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";

type PreviewTransformModalProps = {
  open: boolean;
  onClose: () => void;
  projectId: string;
  datasetId: string;
};

const DEFAULT_STEPS_TEXT = JSON.stringify(
  [
    {
      step_type: "rename_columns",
      config: {
        mappings: {
          old_name: "new_name",
        },
      },
    },
  ],
  null,
  2,
);

function parseStepsJson(rawValue: string): TransformationStep[] {
  const parsed = JSON.parse(rawValue) as unknown;

  if (!Array.isArray(parsed)) {
    throw new Error("Steps JSON must be a JSON array.");
  }

  return parsed as TransformationStep[];
}

function SchemaBlock({ title, schema }: { title: string; schema: TransformationPreviewResponse["schema_after"] }) {
  return (
    <div className="rounded-2xl border border-line bg-sunken p-4">
      <div className="text-xs uppercase tracking-[0.18em] text-muted">{title}</div>
      <div className="mt-3 max-h-40 overflow-y-auto">
        <table className="min-w-full text-left text-xs text-ink-2">
          <thead className="text-muted">
            <tr>
              <th className="py-1 pr-3 font-medium">Column</th>
              <th className="py-1 font-medium">Inferred type</th>
            </tr>
          </thead>
          <tbody>
            {schema.columns.map((column) => (
              <tr key={column.name}>
                <td className="py-1 pr-3 align-top text-ink">{column.name}</td>
                <td className="py-1 align-top">{column.inferred_type}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function PreviewTransformModal({ open, onClose, projectId, datasetId }: PreviewTransformModalProps) {
  const [stepsJsonText, setStepsJsonText] = useState(DEFAULT_STEPS_TEXT);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<TransformationPreviewResponse | null>(null);

  const hasResult = useMemo(() => result !== null, [result]);

  const handleClose = () => {
    setStepsJsonText(DEFAULT_STEPS_TEXT);
    setError(null);
    setLoading(false);
    setResult(null);
    onClose();
  };

  const handlePreview = async () => {
    setError(null);
    let steps: TransformationStep[];
    try {
      steps = parseStepsJson(stepsJsonText);
    } catch (parseError) {
      setError(extractErrorMessage(parseError));
      return;
    }

    try {
      setLoading(true);
      const response = await apiFetch<TransformationPreviewResponse>(
        `/projects/${projectId}/datasets/${datasetId}/pipelines/preview`,
        {
          method: "POST",
          body: JSON.stringify({ steps }),
        },
      );
      setResult(response);
    } catch (previewError) {
      setError(extractErrorMessage(previewError));
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Preview transformation"
      description="Run ad hoc transformation steps against this dataset in memory. Nothing is saved."
      widthClassName="max-w-5xl"
      footer={
        <div className="flex items-center justify-end gap-3">
          <Button variant="secondary" onClick={handleClose} disabled={loading}>
            Close
          </Button>
          <Button type="button" onClick={handlePreview} disabled={loading}>
            {loading ? "Running preview…" : "Preview"}
          </Button>
        </div>
      }
    >
      <div className="grid gap-6 lg:grid-cols-[1fr_1.1fr]">
        <div className="space-y-5">
          <FormField
            label="Steps JSON"
            htmlFor="preview-steps-json"
            description="Ordered array of { step_type, config } objects. Validated against the dataset before each step."
          >
            <Textarea
              id="preview-steps-json"
              value={stepsJsonText}
              onChange={(event) => setStepsJsonText(event.target.value)}
              className="min-h-[280px] font-mono text-[13px]"
            />
          </FormField>
          {error ? (
            <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
              {error}
            </div>
          ) : null}
        </div>

        <div className="space-y-4">
          {!hasResult && !loading ? (
            <div className="rounded-2xl border border-dashed border-line-strong bg-sunken px-4 py-10 text-center text-sm text-ink-3">
              Run a preview to see row counts, schema changes, and sample rows.
            </div>
          ) : null}

          {loading ? (
            <div className="rounded-2xl border border-line bg-sunken px-4 py-8 text-center text-sm text-ink-2">
              Loading preview…
            </div>
          ) : null}

          {result && !loading ? (
            <>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-2xl border border-line bg-sunken px-4 py-3">
                  <div className="text-xs uppercase tracking-[0.18em] text-muted">Rows before</div>
                  <div className="mt-1 font-semibold text-ink">{result.row_count_before}</div>
                </div>
                <div className="rounded-2xl border border-line bg-sunken px-4 py-3">
                  <div className="text-xs uppercase tracking-[0.18em] text-muted">Rows after</div>
                  <div className="mt-1 font-semibold text-ink">{result.row_count_after}</div>
                </div>
                <div className="rounded-2xl border border-line bg-sunken px-4 py-3">
                  <div className="text-xs uppercase tracking-[0.18em] text-muted">Columns before</div>
                  <div className="mt-1 font-semibold text-ink">{result.column_count_before}</div>
                </div>
                <div className="rounded-2xl border border-line bg-sunken px-4 py-3">
                  <div className="text-xs uppercase tracking-[0.18em] text-muted">Columns after</div>
                  <div className="mt-1 font-semibold text-ink">{result.column_count_after}</div>
                </div>
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <SchemaBlock title="Schema before" schema={result.schema_before} />
                <SchemaBlock title="Schema after" schema={result.schema_after} />
              </div>

              {result.warnings.length > 0 ? (
                <div className="rounded-2xl border border-warning-line bg-warning-soft px-4 py-3 text-sm text-warning">
                  <div className="text-xs uppercase tracking-[0.18em] text-warning">Warnings</div>
                  <ul className="mt-2 list-disc space-y-1 pl-5">
                    {result.warnings.map((warning, index) => (
                      <li key={`${index}-${warning.slice(0, 48)}`}>{warning}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              <div className="overflow-hidden rounded-[20px] border border-line bg-sunken">
                <div className="border-b border-line px-4 py-3 text-xs uppercase tracking-[0.18em] text-muted">
                  Preview rows
                </div>
                <div className="max-h-[320px] overflow-auto">
                  <table className="min-w-full divide-y divide-line text-left text-xs">
                    <thead className="sticky top-0 bg-surface text-ink-3">
                      <tr>
                        {result.preview_columns.map((column) => (
                          <th key={column} className="cell-pad font-medium">
                            {column}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line text-ink">
                      {result.preview_rows.map((row, rowIndex) => (
                        <tr key={rowIndex} className="hover:bg-surface">
                          {result.preview_columns.map((column) => (
                            <td key={`${rowIndex}-${column}`} className="cell-pad align-top">
                              {row[column] === null || row[column] === undefined ? "" : String(row[column])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          ) : null}
        </div>
      </div>
    </Modal>
  );
}
