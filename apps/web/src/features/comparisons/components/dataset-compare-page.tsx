"use client";

import Link from "next/link";
import { useState } from "react";

import type {
  AuthUser,
  DatasetComparisonSummary,
  DatasetStatisticalTestResult,
  SavedStatisticalTestRead,
} from "@platform/shared-types";
import { Button, Modal, SectionPanel, StatCard } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { AppShell } from "@/components/layout/app-shell";
import { formatNumber, titleCase } from "@/lib/format";

type DatasetComparePageProps = {
  currentUser: AuthUser;
  projectId: string;
  comparison: DatasetComparisonSummary;
};

function formatDelta(value: number | null): string {
  if (value === null) {
    return "—";
  }
  if (value > 0) {
    return `+${formatNumber(value)}`;
  }
  return formatNumber(value);
}

export function DatasetComparePageView({ currentUser, projectId, comparison }: DatasetComparePageProps) {
  const { left_dataset, right_dataset, schema_delta, profile_delta, lineage_context } = comparison;
  const [testType, setTestType] = useState<"welch_t_test" | "proportion_z_test" | "chi_square_distribution">(
    "welch_t_test",
  );
  const [columnName, setColumnName] = useState("");
  const [testLoading, setTestLoading] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<DatasetStatisticalTestResult | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [saveDescription, setSaveDescription] = useState("");
  const [saveBusy, setSaveBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  async function onRunTest() {
    setTestError(null);
    setTestResult(null);
    if (!columnName.trim()) {
      setTestError("Enter a column name.");
      return;
    }
    setTestLoading(true);
    try {
      const res = await apiFetch<DatasetStatisticalTestResult>(
        `/projects/${projectId}/datasets/${left_dataset.id}/tests/${right_dataset.id}`,
        {
          method: "POST",
          body: JSON.stringify({
            test_type: testType,
            column_name: columnName.trim(),
          }),
        },
      );
      setTestResult(res);
    } catch (error) {
      setTestError(extractErrorMessage(error));
    } finally {
      setTestLoading(false);
    }
  }

  async function onSaveTest() {
    setSaveError(null);
    if (!testResult) {
      return;
    }
    if (!saveName.trim()) {
      setSaveError("Enter a name for this saved test.");
      return;
    }
    setSaveBusy(true);
    try {
      await apiFetch<SavedStatisticalTestRead>(`/projects/${projectId}/tests/saved`, {
        method: "POST",
        body: JSON.stringify({
          name: saveName.trim(),
          description: saveDescription.trim() ? saveDescription.trim() : null,
          left_dataset_id: left_dataset.id,
          right_dataset_id: right_dataset.id,
          test_type: testType,
          column_name: testResult.column_name,
        }),
      });
      setSaveOpen(false);
      setSaveName("");
      setSaveDescription("");
    } catch (error) {
      setSaveError(extractErrorMessage(error));
    } finally {
      setSaveBusy(false);
    }
  }

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Testing lab"
      title="Dataset comparison"
      subtitle="Before/after style comparison using persisted row counts, schema_json, profile_json, and lineage fields only."
      actions={
        <div className="flex flex-wrap gap-2">
          <Link
            href={`/projects/${projectId}/tests/saved?left=${left_dataset.id}&right=${right_dataset.id}`}
            className="rounded-full border border-line bg-surface px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-ink hover:border-line-strong"
          >
            Saved tests
          </Link>
          <Link
            href={`/projects/${projectId}/datasets/${left_dataset.id}`}
            className="rounded-full border border-line bg-surface px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-ink hover:border-line-strong"
          >
            Left dataset
          </Link>
          <Link
            href={`/projects/${projectId}/datasets/${right_dataset.id}`}
            className="rounded-full border border-line bg-surface px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-ink hover:border-line-strong"
          >
            Right dataset
          </Link>
        </div>
      }
      meta={
        <>
          <span className="rounded-full border border-line bg-surface px-3 py-1 text-xs uppercase tracking-[0.18em] text-ink-2">
            {left_dataset.name} → {right_dataset.name}
          </span>
        </>
      }
    >
      <section className="grid gap-4 md:grid-cols-4">
        <StatCard
          label="Row delta (right − left)"
          value={formatDelta(comparison.row_count_delta)}
          caption="From dataset row_count fields."
        />
        <StatCard
          label="Column delta"
          value={formatDelta(comparison.column_count_delta)}
          caption="From dataset column_count fields."
        />
        <StatCard
          label="Left rows"
          value={formatNumber(left_dataset.row_count)}
          caption={left_dataset.name}
        />
        <StatCard
          label="Right rows"
          value={formatNumber(right_dataset.row_count)}
          caption={right_dataset.name}
        />
      </section>

      <SectionPanel
        title="Statistical test"
        description="Ad hoc Welch t-test, two-proportion z-test, or chi-square on this column pair. Save successful runs as reusable definitions; not causal inference."
      >
        <div className="flex flex-col gap-4 md:flex-row md:flex-wrap md:items-end">
          <label className="flex min-w-[200px] flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Test type
            <select
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={testType}
              onChange={(e) =>
                setTestType(e.target.value as "welch_t_test" | "proportion_z_test" | "chi_square_distribution")
              }
            >
              <option value="welch_t_test">Welch t-test (numeric)</option>
              <option value="proportion_z_test">Two-proportion z (binary)</option>
              <option value="chi_square_distribution">Chi-square (categorical)</option>
            </select>
          </label>
          <label className="flex min-w-[200px] flex-1 flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Column name
            <input
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={columnName}
              onChange={(e) => setColumnName(e.target.value)}
              placeholder="e.g. amount"
              autoComplete="off"
            />
          </label>
          <Button variant="secondary" disabled={testLoading} onClick={() => void onRunTest()}>
            {testLoading ? "Running…" : "Run test"}
          </Button>
          {testResult ? (
            <Button variant="secondary" disabled={saveBusy} onClick={() => setSaveOpen(true)}>
              Save test
            </Button>
          ) : null}
        </div>
        {testError ? (
          <p className="mt-3 text-sm text-danger" role="alert">
            {testError}
          </p>
        ) : null}
        {testResult ? (
          <div className="mt-5 space-y-3 rounded-2xl border border-line bg-surface px-4 py-4 text-sm text-ink">
            <div className="flex flex-wrap gap-2 text-xs uppercase tracking-[0.16em] text-muted">
              <span>{titleCase(testResult.test_type.replace(/_/g, " "))}</span>
              <span>·</span>
              <span className="font-mono text-ink-2">{testResult.column_name}</span>
            </div>
            <dl className="grid gap-2 md:grid-cols-2">
              <div>
                <dt className="text-xs text-muted">Statistic</dt>
                <dd className="font-mono text-ink">
                  {testResult.statistic != null && Number.isFinite(testResult.statistic)
                    ? String(testResult.statistic)
                    : "—"}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted">p-value</dt>
                <dd className="font-mono text-ink">
                  {testResult.p_value != null ? testResult.p_value.toExponential(4) : "—"}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted">Sample sizes</dt>
                <dd>
                  {testResult.left_dataset.sample_size} (left) · {testResult.right_dataset.sample_size} (right)
                </dd>
              </div>
            </dl>
            <p className="text-ink-2">{testResult.interpretation}</p>
            {testResult.warnings.length > 0 ? (
              <ul className="list-inside list-disc text-xs text-ink-3">
                {testResult.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </SectionPanel>

      <Modal
        open={saveOpen}
        title="Save statistical test"
        description="Store this configuration to rerun later from the saved tests list. Reruns use the current dataset files."
        onClose={() => {
          setSaveOpen(false);
          setSaveError(null);
        }}
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              variant="ghost"
              onClick={() => {
                setSaveOpen(false);
                setSaveError(null);
              }}
            >
              Cancel
            </Button>
            <Button disabled={saveBusy} onClick={() => void onSaveTest()}>
              {saveBusy ? "Saving…" : "Save"}
            </Button>
          </div>
        }
      >
        <div className="flex flex-col gap-4">
          {saveError ? (
            <p className="text-sm text-danger" role="alert">
              {saveError}
            </p>
          ) : null}
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Name
            <input
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              placeholder="e.g. Weekly revenue mean check"
              autoComplete="off"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.16em] text-muted">
            Description (optional)
            <textarea
              className="min-h-[88px] rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={saveDescription}
              onChange={(e) => setSaveDescription(e.target.value)}
              placeholder="Notes for your team"
            />
          </label>
        </div>
      </Modal>

      <SectionPanel title="Comparison notes" description="Deterministic notes from metadata deltas.">
        {comparison.comparison_notes.length === 0 ? (
          <p className="text-sm text-ink-3">No notes generated.</p>
        ) : (
          <ul className="list-inside list-disc space-y-1 text-sm text-ink">
            {comparison.comparison_notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </SectionPanel>

      <div className="grid gap-6 lg:grid-cols-2">
        <SectionPanel title="Schema changes" description="Diff of schema_json column names and inferred types.">
          <dl className="space-y-3 text-sm">
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Added columns</dt>
              <dd className="mt-1 text-ink">
                {schema_delta.added_columns.length ? schema_delta.added_columns.join(", ") : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Removed columns</dt>
              <dd className="mt-1 text-ink">
                {schema_delta.removed_columns.length ? schema_delta.removed_columns.join(", ") : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Inferred type changes</dt>
              <dd className="mt-1 space-y-1">
                {schema_delta.changed_type_columns.length === 0 ? (
                  <span className="text-ink-3">—</span>
                ) : (
                  schema_delta.changed_type_columns.map((c) => (
                    <div key={c.column_name} className="font-mono text-xs text-ink-2">
                      {c.column_name}: {titleCase(c.before_type)} → {titleCase(c.after_type)}
                    </div>
                  ))
                )}
              </dd>
            </div>
          </dl>
        </SectionPanel>

        <SectionPanel title="Profile / quality delta" description="From profile_json when present.">
          <dl className="grid gap-3 text-sm md:grid-cols-2">
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Duplicate rows (left)</dt>
              <dd className="mt-1 text-ink">{formatNumber(profile_delta.duplicate_row_count_before)}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Duplicate rows (right)</dt>
              <dd className="mt-1 text-ink">{formatNumber(profile_delta.duplicate_row_count_after)}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Completeness (left)</dt>
              <dd className="mt-1 text-ink">
                {profile_delta.completeness_score_before != null
                  ? `${profile_delta.completeness_score_before}%`
                  : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.18em] text-muted">Completeness (right)</dt>
              <dd className="mt-1 text-ink">
                {profile_delta.completeness_score_after != null
                  ? `${profile_delta.completeness_score_after}%`
                  : "—"}
              </dd>
            </div>
          </dl>
        </SectionPanel>
      </div>

      <SectionPanel title="Lineage context" description="Parent/child and pipeline links when detectable from dataset rows.">
        <dl className="grid gap-3 text-sm md:grid-cols-2">
          <div>
            <dt className="text-xs uppercase tracking-[0.18em] text-muted">Parent/child relationship</dt>
            <dd className="mt-1 text-ink">{lineage_context.related_by_parent_child ? "Yes" : "No"}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-[0.18em] text-muted">Parent dataset id</dt>
            <dd className="mt-1 font-mono text-xs text-ink-2">
              {lineage_context.parent_dataset_id ?? "—"}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-[0.18em] text-muted">Created from pipeline</dt>
            <dd className="mt-1 font-mono text-xs text-ink-2">
              {lineage_context.created_from_pipeline_id ?? "—"}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-[0.18em] text-muted">Related run id</dt>
            <dd className="mt-1 font-mono text-xs text-ink-2">{lineage_context.related_run_id ?? "—"}</dd>
          </div>
        </dl>
      </SectionPanel>
    </AppShell>
  );
}
