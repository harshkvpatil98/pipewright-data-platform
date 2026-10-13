"use client";

import Link from "next/link";
import { useState } from "react";

import type {
  AuthUser,
  DatasetComparisonSummary,
  DatasetStatisticalTestResult,
  SavedStatisticalTestRead,
} from "@platform/shared-types";
import { Button, buttonClassName, Modal, SectionPanel, StatTile } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { AppShell } from "@/components/layout/app-shell";
import { formatNumber } from "@/lib/format";
import { typeLabel } from "@/lib/labels";
import { recipeHref } from "@/lib/navigation";

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

const TEST_LABELS: Record<string, string> = {
  welch_t_test: "Averages compared",
  proportion_z_test: "Shares compared",
  chi_square_distribution: "Categories compared",
};

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
      title="Compare two datasets"
      subtitle="Two datasets side by side: their rows, their columns and how complete they are."
      actions={
        <Link
          href={`/projects/${projectId}/tests/saved?left=${left_dataset.id}&right=${right_dataset.id}`}
          className={buttonClassName("secondary", "md")}
        >
          Saved comparisons
        </Link>
      }
      meta={
        <span className="text-[14px] text-ink-2">
          <Link href={`/projects/${projectId}/datasets/${left_dataset.id}`} className="text-accent hover:underline">
            {left_dataset.name}
          </Link>{" "}
          on the left,{" "}
          <Link href={`/projects/${projectId}/datasets/${right_dataset.id}`} className="text-accent hover:underline">
            {right_dataset.name}
          </Link>{" "}
          on the right
        </span>
      }
    >
      <section className="grid gap-4 md:grid-cols-4">
        <StatTile
          label="Rows, right minus left"
          value={formatDelta(comparison.row_count_delta)}
        />
        <StatTile
          label="Columns, right minus left"
          value={formatDelta(comparison.column_count_delta)}
        />
        <StatTile
          label="Rows on the left"
          value={formatNumber(left_dataset.row_count)}
          caption={left_dataset.name}
        />
        <StatTile
          label="Rows on the right"
          value={formatNumber(right_dataset.row_count)}
          caption={right_dataset.name}
        />
      </section>

      <SectionPanel
        title="Is the difference real?"
        description="Test whether a column differs between the two beyond chance. A test shows a difference, not its cause."
      >
        <div className="flex flex-col gap-4 md:flex-row md:flex-wrap md:items-end">
          <label className="flex min-w-[200px] flex-col gap-1 text-xs text-muted">
            What to compare
            <select
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={testType}
              onChange={(e) =>
                setTestType(e.target.value as "welch_t_test" | "proportion_z_test" | "chi_square_distribution")
              }
            >
              <option value="welch_t_test">Averages of a number column (Welch t-test)</option>
              <option value="proportion_z_test">Share of yes and no (two-proportion test)</option>
              <option value="chi_square_distribution">Mix of categories (chi-square test)</option>
            </select>
          </label>
          <label className="flex min-w-[200px] flex-1 flex-col gap-1 text-xs text-muted">
            Column
            <input
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={columnName}
              onChange={(e) => setColumnName(e.target.value)}
              placeholder="e.g. amount"
              autoComplete="off"
            />
          </label>
          <Button variant="secondary" disabled={testLoading} onClick={() => void onRunTest()}>
            {testLoading ? "Testing…" : "Run the test"}
          </Button>
          {testResult ? (
            <Button variant="secondary" disabled={saveBusy} onClick={() => setSaveOpen(true)}>
              Save this test
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
            <div className="flex flex-wrap gap-2 text-xs text-muted">
              <span>{TEST_LABELS[testResult.test_type] ?? testResult.test_type}</span>
              <span>·</span>
              <span className="font-mono text-ink-2">{testResult.column_name}</span>
            </div>
            <dl className="grid gap-2 md:grid-cols-2">
              <div>
                <dt className="text-xs text-muted">Test statistic</dt>
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
                <dt className="text-xs text-muted">Rows compared</dt>
                <dd>
                  {testResult.left_dataset.sample_size} on the left, {testResult.right_dataset.sample_size} on the right
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
        title="Save this test"
        description="Run it again later from Comparisons. It always tests the datasets as they are then."
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
          <label className="flex flex-col gap-1 text-xs text-muted">
            Name
            <input
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink"
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              placeholder="e.g. Weekly revenue mean check"
              autoComplete="off"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted">
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

      <SectionPanel title="What differs">
        {comparison.comparison_notes.length === 0 ? (
          <p className="text-sm text-ink-3">Nothing worth pointing out.</p>
        ) : (
          <ul className="list-inside list-disc space-y-1 text-sm text-ink">
            {comparison.comparison_notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </SectionPanel>

      <div className="grid gap-6 lg:grid-cols-2">
        <SectionPanel title="Columns">
          <dl className="space-y-3 text-sm">
            <div>
              <dt className="text-xs text-muted">Only on the right</dt>
              <dd className="mt-1 text-ink">
                {schema_delta.added_columns.length ? schema_delta.added_columns.join(", ") : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Only on the left</dt>
              <dd className="mt-1 text-ink">
                {schema_delta.removed_columns.length ? schema_delta.removed_columns.join(", ") : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">A different kind of value</dt>
              <dd className="mt-1 space-y-1">
                {schema_delta.changed_type_columns.length === 0 ? (
                  <span className="text-ink-3">—</span>
                ) : (
                  schema_delta.changed_type_columns.map((c) => (
                    <div key={c.column_name} className="font-mono text-xs text-ink-2">
                      {c.column_name}: {typeLabel(c.before_type)} on the left, {typeLabel(c.after_type)} on the right
                    </div>
                  ))
                )}
              </dd>
            </div>
          </dl>
        </SectionPanel>

        <SectionPanel title="How complete">
          <dl className="grid gap-3 text-sm md:grid-cols-2">
            <div>
              <dt className="text-xs text-muted">Repeated rows on the left</dt>
              <dd className="mt-1 text-ink">{formatNumber(profile_delta.duplicate_row_count_before)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Repeated rows on the right</dt>
              <dd className="mt-1 text-ink">{formatNumber(profile_delta.duplicate_row_count_after)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Filled in on the left</dt>
              <dd className="mt-1 text-ink">
                {profile_delta.completeness_score_before != null
                  ? `${profile_delta.completeness_score_before}%`
                  : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Filled in on the right</dt>
              <dd className="mt-1 text-ink">
                {profile_delta.completeness_score_after != null
                  ? `${profile_delta.completeness_score_after}%`
                  : "—"}
              </dd>
            </div>
          </dl>
        </SectionPanel>
      </div>

      <SectionPanel title="How they are related">
        <dl className="grid gap-3 text-sm md:grid-cols-2">
          <div>
            <dt className="text-xs text-muted">One was made from the other</dt>
            <dd className="mt-1 text-ink">{lineage_context.related_by_parent_child ? "Yes" : "No"}</dd>
          </div>
          {lineage_context.parent_dataset_id ? (
            <div>
              <dt className="text-xs text-muted">Made from</dt>
              <dd className="mt-1">
                <Link href={`/projects/${projectId}/datasets/${lineage_context.parent_dataset_id}`} className="text-accent hover:underline">
                  Open that dataset
                </Link>
              </dd>
            </div>
          ) : null}
          {lineage_context.created_from_pipeline_id ? (
            <div>
              <dt className="text-xs text-muted">Made by a recipe</dt>
              <dd className="mt-1">
                <Link href={recipeHref(projectId, lineage_context.created_from_pipeline_id)} className="text-accent hover:underline">
                  Open the recipe
                </Link>
              </dd>
            </div>
          ) : null}
          {lineage_context.related_run_id ? (
            <div>
              <dt className="text-xs text-muted">The run that made it</dt>
              <dd className="mt-1">
                <Link href={`/projects/${projectId}/runs/${lineage_context.related_run_id}/audit`} className="text-accent hover:underline">
                  Open the run
                </Link>
              </dd>
            </div>
          ) : null}
        </dl>
      </SectionPanel>
    </AppShell>
  );
}
