"use client";

import { SectionPanel } from "@platform/shared-ui";
import type { TransformationPreviewResponse } from "@platform/shared-types";

type PipelinePreviewPanelProps = {
  preview: TransformationPreviewResponse | null;
  loading: boolean;
  error: string | null;
};

export function PipelinePreviewPanel({ preview, loading, error }: PipelinePreviewPanelProps) {
  return (
    <SectionPanel
      title="Preview"
      description="Runs the saved or unsaved step draft against the base dataset in memory only."
    >
      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}
      {loading ? (
        <div className="rounded-2xl border border-line bg-sunken px-4 py-4 text-sm text-ink-2">
          Running preview...
        </div>
      ) : null}
      {!loading && !error && !preview ? (
        <div className="rounded-2xl border border-dashed border-line bg-surface px-5 py-9 text-sm leading-6 text-ink-3">
          Preview the current pipeline draft to inspect row changes, schema changes, and warnings.
        </div>
      ) : null}
      {preview ? (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-4">
            <MetricCard label="Rows before" value={preview.row_count_before} />
            <MetricCard label="Rows after" value={preview.row_count_after} />
            <MetricCard label="Columns before" value={preview.column_count_before} />
            <MetricCard label="Columns after" value={preview.column_count_after} />
          </div>

          {preview.warnings.length > 0 ? (
            <div className="rounded-2xl border border-warning-line bg-warning-soft px-4 py-3 text-sm text-warning">
              <div className="text-xs uppercase tracking-[0.18em] text-warning">Warnings</div>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                {preview.warnings.map((warning, index) => (
                  <li key={`${index}-${warning.slice(0, 24)}`}>{warning}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="grid gap-4 xl:grid-cols-2">
            <SchemaTable
              title="Schema before"
              columns={preview.schema_before.columns}
            />
            <SchemaTable
              title="Schema after"
              columns={preview.schema_after.columns}
            />
          </div>

          <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
            <div className="border-b border-line px-4 py-3 text-xs uppercase tracking-[0.18em] text-muted">
              Preview rows
            </div>
            <div className="max-h-[360px] overflow-auto">
              <table className="min-w-full divide-y divide-line text-left text-sm">
                <thead className="sticky top-0 bg-surface text-ink-3">
                  <tr>
                    {preview.preview_columns.map((column) => (
                      <th key={column} className="cell-pad font-medium">
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {preview.preview_rows.map((row, index) => (
                    <tr key={index} className="transition hover:bg-surface">
                      {preview.preview_columns.map((column) => (
                        <td key={`${index}-${column}`} className="cell-pad align-top text-ink">
                          {row[column] == null ? "" : String(row[column])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : null}
    </SectionPanel>
  );
}

function MetricCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-line bg-sunken px-4 py-4">
      <div className="text-xs uppercase tracking-[0.18em] text-muted">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-ink">{value}</div>
    </div>
  );
}

function SchemaTable({
  title,
  columns,
}: {
  title: string;
  columns: TransformationPreviewResponse["schema_after"]["columns"];
}) {
  return (
    <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
      <div className="border-b border-line px-4 py-3 text-xs uppercase tracking-[0.18em] text-muted">
        {title}
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-line text-left text-sm">
          <thead className="bg-surface text-ink-3">
            <tr>
              <th className="cell-pad font-medium">Column</th>
              <th className="cell-pad font-medium">Inferred type</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {columns.map((column) => (
              <tr key={`${title}-${column.name}`} className="transition hover:bg-surface">
                <td className="cell-pad text-ink">{column.name}</td>
                <td className="cell-pad text-ink-2">{column.inferred_type}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
