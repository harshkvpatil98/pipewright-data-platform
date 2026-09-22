"use client";

import { useCallback, useEffect, useId, useMemo, useState } from "react";

import type {
  AuthUser,
  DataQualityEvaluationResponse,
  DataQualityRule,
  DatasetRecord,
  RuleSeverity,
  RuleTypeInfo,
} from "@platform/shared-types";
import { Button, FormField, Input, SectionPanel, Select, StatusBadge } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { ruleTypeLabel } from "@/lib/labels";
import { cx } from "@/lib/utils";

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
const CONFIG_FIELDS: Record<string, { key: string; label: string; placeholder: string }[]> = {
  not_null: [{ key: "column", label: "Column", placeholder: "email" }],
  unique: [{ key: "column", label: "Column", placeholder: "id" }],
  allowed_values: [
    { key: "column", label: "Column", placeholder: "status" },
    { key: "allowed_values", label: "Allowed values (comma separated)", placeholder: "active, archived" },
  ],
  range: [
    { key: "column", label: "Column", placeholder: "amount" },
    { key: "min", label: "Minimum", placeholder: "0" },
    { key: "max", label: "Maximum", placeholder: "1000" },
  ],
  regex_match: [
    { key: "column", label: "Column", placeholder: "email" },
    { key: "pattern", label: "Pattern", placeholder: "[^@\\s]+@[^@\\s]+\\.[a-z]{2,}" },
  ],
  expression: [
    { key: "expression", label: "Expression must be true for every row", placeholder: "total >= 0" },
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

function buildConfig(ruleType: string, values: Record<string, string>): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  for (const field of CONFIG_FIELDS[ruleType] ?? []) {
    const raw = (values[field.key] ?? "").trim();
    if (!raw) continue;
    if (field.key === "allowed_values") {
      config[field.key] = raw.split(",").map((value) => value.trim()).filter(Boolean);
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
  const [evaluation, setEvaluation] = useState<DataQualityEvaluationResponse | null>(null);

  const [ruleType, setRuleType] = useState<string>(ruleTypes[0]?.rule_type ?? "not_null");
  const [ruleName, setRuleName] = useState("");
  const [severity, setSeverity] = useState<RuleSeverity>("error");
  const [datasetId, setDatasetId] = useState<string>(datasets[0]?.id ?? "");
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
    apiFetch<{ columns: string[] }>(`/projects/${projectId}/datasets/${datasetId}/preview`)
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
    async <T,>(key: string, action: () => Promise<T>, successMessage?: string): Promise<T | null> => {
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
      "Rule saved.",
    );
    if (created) {
      setRules((current) => [created, ...current]);
      setRuleName("");
      setConfigValues({});
    }
  };

  const deleteRule = async (ruleId: string) => {
    const done = await run(
      `delete-${ruleId}`,
      () =>
        apiFetch<void>(`/projects/${projectId}/data-quality/rules/${ruleId}`, { method: "DELETE" }),
      "Rule deleted.",
    );
    if (done !== null) setRules((current) => current.filter((rule) => rule.id !== ruleId));
  };

  const evaluate = async () => {
    if (!datasetId) {
      setError("Choose a dataset to evaluate.");
      return;
    }
    const result = await run(
      "evaluate",
      () =>
        apiFetch<DataQualityEvaluationResponse>(
          `/projects/${projectId}/datasets/${datasetId}/data-quality/evaluate`,
          { method: "POST", body: JSON.stringify({ quarantine }) },
        ),
    );
    if (result) {
      setEvaluation(result);
      setFeedback(
        `${result.rules_evaluated} rule(s) evaluated · ${result.rules_failed} failed · ${result.rows_quarantined} row(s) quarantined.`,
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
      eyebrow="Govern"
      title="Data quality"
      subtitle="Assert what must be true about your data. Failing rows can be quarantined into their own dataset instead of flowing downstream."
    >
      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}
      {feedback ? (
        <div className="rounded-2xl border border-success-line bg-success-soft px-4 py-3 text-sm text-success">
          {feedback}
        </div>
      ) : null}

      <SectionPanel
        title="Define a rule"
        description={activeRuleType?.description ?? "Choose a rule type to begin."}
      >
        <div className="grid gap-4 lg:grid-cols-[minmax(0,380px)_1fr]">
          <div className="space-y-3 rounded-2xl border border-line bg-surface p-4">
            <FormField label="Rule name" htmlFor={`${fieldPrefix}-name`}>
              <Input
                id={`${fieldPrefix}-name`}
                value={ruleName}
                onChange={(event) => setRuleName(event.target.value)}
                placeholder="Email must be present"
              />
            </FormField>
            <FormField label="Rule type" htmlFor={`${fieldPrefix}-type`}>
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
                  ? "Failures quarantine rows and fail the evaluation."
                  : "Failures are reported but do not block anything."
              }
            >
              <Select
                id={`${fieldPrefix}-severity`}
                value={severity}
                onChange={(event) => setSeverity(event.target.value as RuleSeverity)}
              >
                <option value="error">Error — quarantine failing rows</option>
                <option value="warning">Warning — report only</option>
              </Select>
            </FormField>
            <FormField
              label="Dataset"
              htmlFor={`${fieldPrefix}-dataset`}
              description="Leave blank to apply the rule to every dataset in the project."
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
                      setConfigValues((values) => ({ ...values, [field.key]: event.target.value }))
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
                      setConfigValues((values) => ({ ...values, [field.key]: event.target.value }))
                    }
                    placeholder={field.placeholder}
                  />
                )}
              </FormField>
            ))}

            <Button
              className="w-full"
              onClick={createRule}
              disabled={busy === "create-rule" || !ruleName.trim()}
            >
              {busy === "create-rule" ? "Saving…" : "Save rule"}
            </Button>
          </div>

          <div className="space-y-3">
            {rules.length === 0 ? (
              <p className="rounded-2xl border border-dashed border-line px-4 py-8 text-center text-sm text-muted">
                No rules defined yet.
              </p>
            ) : (
              rules.map((rule) => (
                <article
                  key={rule.id}
                  className="flex flex-wrap items-start justify-between gap-3 rounded-2xl border border-line bg-surface px-4 py-4"
                >
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold text-ink">{rule.name}</h3>
                      <span className="rounded-full border border-line px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-ink-3">
                        {rule.rule_type}
                      </span>
                      <span
                        className={cx(
                          "rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-[0.16em]",
                          rule.severity === "error"
                            ? "border-danger-line bg-danger-soft text-danger"
                            : "border-warning-line bg-warning-soft text-warning",
                        )}
                      >
                        {rule.severity}
                      </span>
                      {rule.last_status ? (
                        <StatusBadge value={rule.last_status === "passed" ? "succeeded" : "failed"} />
                      ) : null}
                    </div>
                    <p className="mt-1 font-mono text-xs text-muted">
                      {JSON.stringify(rule.config_json)}
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
        </div>
      </SectionPanel>

      <SectionPanel
        title="Evaluate a dataset"
        description="Runs every enabled rule that applies to the selected dataset."
        actions={
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-ink-2">
              <input
                type="checkbox"
                checked={quarantine}
                onChange={(event) => setQuarantine(event.target.checked)}
                className="h-4 w-4 rounded border-line-strong bg-sunken"
              />
              Quarantine failing rows
            </label>
            <Button onClick={evaluate} disabled={busy === "evaluate" || !datasetId}>
              {busy === "evaluate" ? "Evaluating…" : "Run evaluation"}
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
              <strong className="uppercase tracking-[0.16em]">{evaluation.status}</strong> ·{" "}
              {evaluation.rows_passing} of {evaluation.rows_in} row(s) passed
              {evaluation.rows_quarantined > 0
                ? ` · ${evaluation.rows_quarantined} quarantined`
                : ""}
              {evaluation.quarantine_dataset_id ? (
                <span className="ml-1 opacity-80">
                  (quarantine dataset {evaluation.quarantine_dataset_id.slice(0, 8)}…)
                </span>
              ) : null}
            </div>

            <div className="overflow-x-auto rounded-2xl border border-line">
              <table className="w-full min-w-max text-left text-xs">
                <thead className="bg-surface text-ink-3">
                  <tr>
                    <th className="cell-pad font-medium">Rule</th>
                    <th className="cell-pad font-medium">Type</th>
                    <th className="cell-pad font-medium">Severity</th>
                    <th className="cell-pad font-medium">Status</th>
                    <th className="cell-pad font-medium">Failed</th>
                    <th className="cell-pad font-medium">Detail</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {evaluation.results.map((result) => (
                    <tr key={`${result.name}-${result.rule_type}`} className="text-ink-2">
                      <td className="cell-pad font-medium text-ink">{result.name}</td>
                      <td className="cell-pad">{result.rule_type}</td>
                      <td className="cell-pad">{result.severity}</td>
                      <td className="cell-pad">
                        <span
                          className={cx(
                            result.status === "passed" ? "text-success" : "text-danger",
                          )}
                        >
                          {result.status}
                        </span>
                      </td>
                      <td className="cell-pad tabular">
                        {result.failed_rows}
                        {result.failure_rate ? ` (${result.failure_rate}%)` : ""}
                      </td>
                      <td className="max-w-md cell-pad text-ink-3">{result.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {evaluation.warnings.length > 0 ? (
              <ul className="space-y-1 text-xs text-warning">
                {evaluation.warnings.map((warning) => (
                  <li key={warning}>• {warning}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : (
          <p className="rounded-2xl border border-dashed border-line px-4 py-8 text-center text-sm text-muted">
            Select a dataset above and run an evaluation to see results.
          </p>
        )}
      </SectionPanel>
    </AppShell>
  );
}
