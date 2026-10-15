"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useMemo, useState } from "react";

import type {
  AuthUser,
  DataQualityEvaluationResponse,
  DataQualityRule,
  DatasetRecord,
  RuleSeverity,
  RuleTypeInfo,
} from "@platform/shared-types";
import { Badge, Button, FormField, Input, Modal, SectionPanel, Select, StatusBadge, Table, TableBody, TableCell, TableHead, TableHeaderCell, TableRow } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import {
  describeCheckSettings,
  ruleTypeLabel,
  severityShortLabel,
} from "@/lib/labels";
import { DATA_QUALITY_TOUR_ID, dataQualityTour } from "@/components/tour/tours";
import { useTour } from "@/components/tour/tour-provider";
import { cx } from "@/lib/utils";
import { countOf } from "@/lib/format";

type DataQualityPageProps = {
  currentUser: AuthUser;
  projectId: string;
  initialRules: DataQualityRule[];
  ruleTypes: RuleTypeInfo[];
  datasets: DatasetRecord[];
};

/**
 * Each rule type needs different config keys. Rather than one generic JSON box,
 * the form renders the fields that rule type actually uses.
 */
const CONFIG_FIELDS: Record<
  string,
  { key: string; label: string; placeholder: string }[]
> = {
  not_null: [{ key: "column", label: "Column", placeholder: "email" }],
  unique: [{ key: "column", label: "Column", placeholder: "id" }],
  allowed_values: [
    { key: "column", label: "Column", placeholder: "status" },
    {
      key: "allowed_values",
      label: "Allowed values (comma separated)",
      placeholder: "active, archived",
    },
  ],
  range: [
    { key: "column", label: "Column", placeholder: "amount" },
    { key: "min", label: "Minimum", placeholder: "0" },
    { key: "max", label: "Maximum", placeholder: "1000" },
  ],
  regex_match: [
    { key: "column", label: "Column", placeholder: "email" },
    {
      key: "pattern",
      label: "Pattern",
      placeholder: "[^@\\s]+@[^@\\s]+\\.[a-z]{2,}",
    },
  ],
  expression: [
    {
      key: "expression",
      label: "Expression must be true for every row",
      placeholder: "total >= 0",
    },
  ],
  row_count: [
    { key: "min", label: "Minimum rows", placeholder: "1" },
    { key: "max", label: "Maximum rows", placeholder: "1000000" },
  ],
  freshness: [
    { key: "column", label: "Timestamp column", placeholder: "updated_at" },
    { key: "max_age_hours", label: "Max age (hours)", placeholder: "24" },
  ],
};

const NUMERIC_KEYS = new Set(["min", "max", "max_age_hours"]);

function buildConfig(
  ruleType: string,
  values: Record<string, string>,
): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  for (const field of CONFIG_FIELDS[ruleType] ?? []) {
    const raw = (values[field.key] ?? "").trim();
    if (!raw) continue;
    if (field.key === "allowed_values") {
      config[field.key] = raw
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean);
    } else if (NUMERIC_KEYS.has(field.key)) {
      const parsed = Number(raw);
      if (!Number.isNaN(parsed)) config[field.key] = parsed;
    } else {
      config[field.key] = raw;
    }
  }
  return config;
}

export function DataQualityPageView({
  currentUser,
  projectId,
  initialRules,
  ruleTypes,
  datasets,
}: DataQualityPageProps) {
  const fieldPrefix = useId();
  const [rules, setRules] = useState(initialRules);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [evaluation, setEvaluation] =
    useState<DataQualityEvaluationResponse | null>(null);

  const { startIfUnseen } = useTour();
  useEffect(() => {
    const timer = setTimeout(
      () => startIfUnseen(dataQualityTour, DATA_QUALITY_TOUR_ID),
      900,
    );
    return () => clearTimeout(timer);
  }, [startIfUnseen]);

  const [ruleType, setRuleType] = useState<string>(
    ruleTypes[0]?.rule_type ?? "not_null",
  );
  const [ruleName, setRuleName] = useState("");
  const [severity, setSeverity] = useState<RuleSeverity>("error");
  // Open on a dataset that has checks, so "Run checks" has something to run.
  const [datasetId, setDatasetId] = useState<string>(
    () =>
      initialRules.find((rule) => datasets.some((dataset) => dataset.id === rule.dataset_id))?.dataset_id ??
      datasets[0]?.id ??
      "",
  );
  const [configValues, setConfigValues] = useState<Record<string, string>>({});
  const [quarantine, setQuarantine] = useState(false);

  // The chosen dataset's columns, so a `column` field is a pick, not a typo.
  const [datasetColumns, setDatasetColumns] = useState<string[]>([]);
  useEffect(() => {
    if (!datasetId) {
      setDatasetColumns([]);
      return;
    }
    let cancelled = false;
    apiFetch<{ columns: string[] }>(
      `/projects/${projectId}/datasets/${datasetId}/preview`,
    )
      .then((preview) => {
        if (!cancelled) setDatasetColumns(preview.columns ?? []);
      })
      .catch(() => {
        // No preview (never ingested): fall back to the free-text field.
        if (!cancelled) setDatasetColumns([]);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, datasetId]);

  const activeRuleType = useMemo(
    () => ruleTypes.find((item) => item.rule_type === ruleType),
    [ruleTypes, ruleType],
  );

  const run = useCallback(
    async <T,>(
      key: string,
      action: () => Promise<T>,
      successMessage?: string,
    ): Promise<T | null> => {
      setBusy(key);
      setError(null);
      setFeedback(null);
      try {
        const result = await action();
        if (successMessage) setFeedback(successMessage);
        return result;
      } catch (caught) {
        setError(extractErrorMessage(caught));
        return null;
      } finally {
        setBusy(null);
      }
    },
    [],
  );

  const [creating, setCreating] = useState(false);

  const createRule = async () => {
    const created = await run(
      "create-rule",
      () =>
        apiFetch<DataQualityRule>(`/projects/${projectId}/data-quality/rules`, {
          method: "POST",
          body: JSON.stringify({
            name: ruleName,
            rule_type: ruleType,
            severity,
            dataset_id: datasetId || null,
            config: buildConfig(ruleType, configValues),
          }),
        }),
      "Check saved. Run the checks below to see how the data does.",
    );
    if (created) {
      setRules((current) => [created, ...current]);
      setRuleName("");
      setConfigValues({});
      setCreating(false);
    }
  };

  const deleteRule = async (ruleId: string) => {
    const done = await run(
      `delete-${ruleId}`,
      () =>
        apiFetch<void>(`/projects/${projectId}/data-quality/rules/${ruleId}`, {
          method: "DELETE",
        }),
      "Check deleted.",
    );
    if (done !== null)
      setRules((current) => current.filter((rule) => rule.id !== ruleId));
  };

  const evaluate = async () => {
    if (!datasetId) {
      setError("Choose a dataset to check.");
      return;
    }
    const result = await run("evaluate", () =>
      apiFetch<DataQualityEvaluationResponse>(
        `/projects/${projectId}/datasets/${datasetId}/data-quality/evaluate`,
        { method: "POST", body: JSON.stringify({ quarantine }) },
      ),
    );
    if (result) {
      setEvaluation(result);
      setFeedback(
        `${countOf(result.rules_evaluated, "check")} run · ${result.rules_failed} failed · ${countOf(result.rows_quarantined, "row")} set aside.`,
      );
    }
  };

  const statusTone = (status: string) =>
    status === "passed"
      ? "border-success-line bg-success-soft text-success"
      : status === "warning"
        ? "border-warning-line bg-warning-soft text-warning"
        : "border-danger-line bg-danger-soft text-danger";

  return (
    <AppShell
      currentUser={currentUser}
      title="Checks"
      subtitle="Rules your data must pass, and what happened when they ran."
      actions={
        <span data-tour="dq-define">
          <Button onClick={() => setCreating(true)}>New check</Button>
        </span>
      }
    >
      {error ? (
        <div className="border-danger-line bg-danger-soft text-danger rounded-2xl border px-4 py-3 text-sm">
          {error}
        </div>
      ) : null}
      {feedback ? (
        <div className="border-success-line bg-success-soft text-success rounded-2xl border px-4 py-3 text-sm">
          {feedback}
        </div>
      ) : null}

      <SectionPanel
        title={
          rules.length === 0
            ? "Your checks"
            : `${rules.length} check${rules.length === 1 ? "" : "s"}`
        }
        description="Each check runs whenever its dataset is checked, by hand below or as part of a workflow."
      >
        <div className="space-y-3">
          {rules.length === 0 ? (
            <div className="border-line flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-dashed px-4 py-6">
              <p className="text-ink-3 text-[14px]">
                No checks yet. Start with the one that matters most, such as
                &quot;every order has an email&quot;.
              </p>
              <Button size="sm" onClick={() => setCreating(true)}>
                New check
              </Button>
            </div>
          ) : (
            rules.map((rule) => (
              <article
                key={rule.id}
                className="border-line bg-surface flex flex-wrap items-start justify-between gap-3 rounded-2xl border px-4 py-4"
              >
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-ink text-sm font-semibold">
                      {rule.name}
                    </h3>
                    <Badge>
                      {ruleTypeLabel(rule.rule_type)}
                    </Badge>
                    <Badge tone={rule.severity === "error" ? "danger" : "warning"}>
                      {severityShortLabel(rule.severity)}
                    </Badge>
                    {rule.last_status ? (
                      <StatusBadge
                        value={
                          rule.last_status === "passed" ? "passed" : "failed"
                        }
                      />
                    ) : null}
                  </div>
                  <p className="text-muted mt-1 text-[13px]">
                    {describeCheckSettings(rule.config_json)}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => deleteRule(rule.id)}
                  disabled={busy === `delete-${rule.id}`}
                >
                  Delete
                </Button>
              </article>
            ))
          )}
        </div>
      </SectionPanel>

      <div data-tour="dq-evaluate">
        <SectionPanel
          title="Run the checks"
          description="Checks one dataset against every check that applies to it."
          actions={
            <div className="flex flex-wrap items-center gap-3">
              <Select
                aria-label="Dataset to check"
                value={datasetId}
                onChange={(event) => setDatasetId(event.target.value)}
                className="w-56"
              >
                <option value="">Choose a dataset…</option>
                {datasets.map((dataset) => (
                  <option key={dataset.id} value={dataset.id}>
                    {dataset.name}
                  </option>
                ))}
              </Select>
              <label className="text-ink-2 flex items-center gap-2 text-[13px]">
                <input
                  type="checkbox"
                  checked={quarantine}
                  onChange={(event) => setQuarantine(event.target.checked)}
                  className="border-line-strong bg-sunken h-4 w-4 rounded"
                />
                Set failing rows aside
              </label>
              <Button onClick={evaluate} disabled={busy === "evaluate" || !datasetId}>
                {busy === "evaluate" ? "Checking…" : "Run checks"}
              </Button>
            </div>
          }
        >
          {evaluation ? (
            <div className="space-y-4">
              <div
                className={cx(
                  "rounded-2xl border px-4 py-3 text-sm",
                  statusTone(evaluation.status),
                )}
              >
                <strong>
                  {evaluation.status === "passed"
                    ? "Passed"
                    : evaluation.status === "warning"
                      ? "Passed with warnings"
                      : "Failed"}
                </strong>{" "}
                · {evaluation.rows_passing} of {countOf(evaluation.rows_in, "row")} passed
                {evaluation.rows_quarantined > 0
                  ? ` · ${evaluation.rows_quarantined} set aside`
                  : ""}
                {evaluation.quarantine_dataset_id ? (
                  <Link
                    href={`/projects/${projectId}/datasets/${evaluation.quarantine_dataset_id}`}
                    className="ml-2 font-medium underline underline-offset-4"
                  >
                    See the rows set aside
                  </Link>
                ) : null}
              </div>

              <div className="border-line overflow-x-auto rounded-2xl border">
                <Table edge="panel" className="min-w-max">
                  <TableHead>
                    <TableRow>
                      <TableHeaderCell>Check</TableHeaderCell>
                      <TableHeaderCell>Type</TableHeaderCell>
                      <TableHeaderCell>Severity</TableHeaderCell>
                      <TableHeaderCell>Status</TableHeaderCell>
                      <TableHeaderCell>Failed</TableHeaderCell>
                      <TableHeaderCell>Detail</TableHeaderCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {evaluation.results.map((result) => (
                      <TableRow
                        key={`${result.name}-${result.rule_type}`} className="text-ink-2"
                      >
                        <TableCell className="text-ink font-medium">
                          {result.name}
                        </TableCell>
                        <TableCell>
                          {ruleTypeLabel(result.rule_type)}
                        </TableCell>
                        <TableCell>
                          {severityShortLabel(result.severity)}
                        </TableCell>
                        <TableCell>
                          <span
                            className={cx(
                              result.status === "passed"
                                ? "text-success"
                                : "text-danger",
                            )}
                          >
                            {result.status === "passed" ? "Passed" : "Failed"}
                          </span>
                        </TableCell>
                        <TableCell className="tabular">
                          {result.failed_rows}
                          {result.failure_rate
                            ? ` (${result.failure_rate}%)`
                            : ""}
                        </TableCell>
                        <TableCell className="text-ink-3 max-w-md">
                          {result.message}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {evaluation.warnings.length > 0 ? (
                <ul className="text-warning space-y-1 text-xs">
                  {evaluation.warnings.map((warning) => (
                    <li key={warning}>• {warning}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : (
            <p className="border-line text-muted rounded-2xl border border-dashed px-4 py-8 text-center text-sm">
              Choose a dataset above and run its checks to see what passed.
            </p>
          )}
        </SectionPanel>
      </div>
      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title="New check"
        description={
          activeRuleType?.description ?? "Choose what the data must do."
        }
        widthClassName="max-w-lg"
        footer={
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setCreating(false)}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={createRule}
              disabled={busy === "create-rule" || !ruleName.trim()}
            >
              {busy === "create-rule" ? "Saving…" : "Save check"}
            </Button>
          </div>
        }
      >
        {error && creating ? (
          <p role="alert" className="text-danger mb-3 text-[13px]">
            {error}
          </p>
        ) : null}
        <div className="space-y-4">
          <FormField label="Name" htmlFor={`${fieldPrefix}-name`}>
            <Input
              id={`${fieldPrefix}-name`}
              value={ruleName}
              onChange={(event) => setRuleName(event.target.value)}
              placeholder="Email must be present"
            />
          </FormField>
          <FormField label="What it checks" htmlFor={`${fieldPrefix}-type`}>
            <Select
              id={`${fieldPrefix}-type`}
              value={ruleType}
              onChange={(event) => {
                setRuleType(event.target.value);
                setConfigValues({});
              }}
            >
              {ruleTypes.map((item) => (
                <option key={item.rule_type} value={item.rule_type}>
                  {ruleTypeLabel(item.rule_type)}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField
            label="Severity"
            htmlFor={`${fieldPrefix}-severity`}
            description={
              severity === "error"
                ? "Rows that fail are set aside, and the check counts as failed."
                : "Failures are reported; nothing is blocked."
            }
          >
            <Select
              id={`${fieldPrefix}-severity`}
              value={severity}
              onChange={(event) =>
                setSeverity(event.target.value as RuleSeverity)
              }
            >
              <option value="error">Error: set failing rows aside</option>
              <option value="warning">Warning: report only</option>
            </Select>
          </FormField>
          <FormField
            label="Dataset"
            htmlFor={`${fieldPrefix}-dataset`}
            description="Leave as All datasets to check every dataset in the project."
          >
            <Select
              id={`${fieldPrefix}-dataset`}
              value={datasetId}
              onChange={(event) => setDatasetId(event.target.value)}
            >
              <option value="">All datasets</option>
              {datasets.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.name}
                </option>
              ))}
            </Select>
          </FormField>

          {(CONFIG_FIELDS[ruleType] ?? []).map((field) => (
            <FormField
              key={field.key}
              label={field.label}
              htmlFor={`${fieldPrefix}-${field.key}`}
            >
              {field.key === "column" && datasetColumns.length > 0 ? (
                <Select
                  id={`${fieldPrefix}-${field.key}`}
                  value={configValues[field.key] ?? ""}
                  onChange={(event) =>
                    setConfigValues((values) => ({
                      ...values,
                      [field.key]: event.target.value,
                    }))
                  }
                >
                  <option value="">Choose a column…</option>
                  {datasetColumns.map((column) => (
                    <option key={column} value={column}>
                      {column}
                    </option>
                  ))}
                </Select>
              ) : (
                <Input
                  id={`${fieldPrefix}-${field.key}`}
                  value={configValues[field.key] ?? ""}
                  onChange={(event) =>
                    setConfigValues((values) => ({
                      ...values,
                      [field.key]: event.target.value,
                    }))
                  }
                  placeholder={field.placeholder}
                />
              )}
            </FormField>
          ))}
        </div>
      </Modal>
    </AppShell>
  );
}
