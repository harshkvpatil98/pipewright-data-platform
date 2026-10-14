"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import type {
  MetricAlert,
  MetricAlertCondition,
  MetricAlertListResponse,
  MetricSeries,
} from "@platform/shared-types";
import { Badge, Button, FormField, Input, SectionPanel, Select } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";

import { formatMetric } from "../sparkline";

/** The measures every dataset has, offered before any has been recorded. */
const DATASET_MEASURES: Pick<MetricSeries, "metric_key" | "column_name" | "label" | "unit">[] = [
  { metric_key: "row_count", column_name: null, label: "row count", unit: null },
  { metric_key: "completeness_score", column_name: null, label: "completeness", unit: "%" },
  { metric_key: "duplicate_row_percentage", column_name: null, label: "duplicate rows", unit: "%" },
  { metric_key: "column_count", column_name: null, label: "column count", unit: null },
];

const CONDITION_WORDS: Record<MetricAlertCondition, string> = {
  above: "is above",
  below: "is below",
  changes_by: "changes by more than",
};

export const measureKey = (measure: Pick<MetricSeries, "metric_key" | "column_name">) =>
  `${measure.metric_key}|${measure.column_name ?? ""}`;

/** The measures to choose from: those recorded, else the ones every dataset has. */
export function measureChoices(series: MetricSeries[]) {
  const recorded = series.map(({ metric_key, column_name, label, unit }) => ({ metric_key, column_name, label, unit }));
  const seen = new Set(recorded.map(measureKey));
  return [...recorded, ...DATASET_MEASURES.filter((measure) => !seen.has(measureKey(measure)))];
}

/** "Past its line", "Within", "Off". */
export function alertState(alert: Pick<MetricAlert, "enabled" | "state">): { word: string; tone: "warning" | "success" | "neutral" } {
  if (!alert.enabled) return { word: "Off", tone: "neutral" };
  return alert.state === "crossed" ? { word: "Past its line", tone: "warning" } : { word: "Within", tone: "success" };
}

/**
 * Alerts on this dataset's measures (A8, Y5): a line a measure should not
 * cross, checked whenever the dataset gets new data, sent to the project's
 * people and its alert targets.
 */
export function MetricAlertsPanel({
  projectId,
  datasetId,
  series,
}: {
  projectId: string;
  datasetId: string;
  series: MetricSeries[];
}) {
  const base = `/projects/${projectId}/datasets/${datasetId}/metric-alerts`;
  const choices = measureChoices(series);
  const [data, setData] = useState<MetricAlertListResponse | null>(null);
  const [measure, setMeasure] = useState(measureKey(choices[0]));
  const [condition, setCondition] = useState<MetricAlertCondition>("above");
  const [threshold, setThreshold] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requested = useRef(false);

  const load = useCallback(async () => {
    try {
      setData(await apiFetch<MetricAlertListResponse>(base));
    } catch (caught) {
      setError(extractErrorMessage(caught));
    }
  }, [base]);

  useEffect(() => {
    if (requested.current) return;
    requested.current = true;
    void load();
  }, [load]);

  const chosen = choices.find((item) => measureKey(item) === measure) ?? choices[0];
  const percent = condition === "changes_by" || chosen.unit === "%";

  const add = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiFetch(base, {
        method: "POST",
        body: JSON.stringify({
          metric_key: chosen.metric_key,
          column_name: chosen.column_name,
          condition,
          threshold: Number(threshold),
        }),
      });
      setThreshold("");
      await load();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const change = async (alert: MetricAlert, request: RequestInit) => {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`${base}/${alert.id}`, request);
      await load();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SectionPanel
      title="Alerts"
      description="Be told when a measure crosses a line you choose. Checked whenever this dataset gets new data."
    >
      <form onSubmit={(event) => void add(event)} className="grid gap-3 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_140px_auto] md:items-end">
        <FormField label="Measure" htmlFor="alert-measure">
          <Select value={measure} onChange={(event) => setMeasure(event.target.value)}>
            {choices.map((item) => (
              <option key={measureKey(item)} value={measureKey(item)}>
                {item.label.charAt(0).toUpperCase() + item.label.slice(1)}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="When it" htmlFor="alert-condition">
          <Select value={condition} onChange={(event) => setCondition(event.target.value as MetricAlertCondition)}>
            {(Object.keys(CONDITION_WORDS) as MetricAlertCondition[]).map((value) => (
              <option key={value} value={value}>
                {CONDITION_WORDS[value]}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label={percent ? "Value (%)" : "Value"} htmlFor="alert-threshold">
          <Input
            type="number"
            inputMode="decimal"
            step="any"
            value={threshold}
            onChange={(event) => setThreshold(event.target.value)}
            placeholder={percent ? "20" : "1000"}
            required
          />
        </FormField>
        <Button type="submit" disabled={busy || threshold.trim() === ""} className="h-11">
          {busy ? "Saving…" : "Add alert"}
        </Button>
      </form>
      {error ? <p className="mt-3 text-[13px] text-danger">{error}</p> : null}

      {data === null ? (
        <p className="mt-4 text-[13px] text-ink-3">Loading…</p>
      ) : data.items.length === 0 ? (
        <p className="mt-4 text-[13px] text-ink-3">No alerts yet.</p>
      ) : (
        <ul className="mt-4 space-y-2">
          {data.items.map((alert) => {
            const state = alertState(alert);
            const unit = choices.find((item) => measureKey(item) === measureKey(alert))?.unit ?? null;
            return (
              <li
                key={alert.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface px-3 py-2.5"
              >
                <div className="min-w-0">
                  <div className="text-[13px] text-ink">{alert.sentence}</div>
                  <div className="mt-0.5 text-[12px] text-ink-3">
                    {alert.last_value === null ? "Not checked yet" : `Now ${formatMetric(alert.last_value, unit)}`}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Badge tone={state.tone}>{state.word}</Badge>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() =>
                      void change(alert, { method: "PATCH", body: JSON.stringify({ enabled: !alert.enabled }) })
                    }
                  >
                    {alert.enabled ? "Turn off" : "Turn on"}
                  </Button>
                  <Button variant="ghost" size="sm" disabled={busy} onClick={() => void change(alert, { method: "DELETE" })}>
                    Remove
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {data?.events.length ? (
        <div className="mt-5">
          <h3 className="text-[13px] font-medium text-ink">Recently</h3>
          <ul className="mt-2 space-y-1.5">
            {data.events.slice(0, 8).map((event) => (
              <li key={event.id} className="text-[12.5px] leading-5 text-ink-2">
                <span className="text-ink-3">{formatDateTime(event.created_at)}</span> · {event.message}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="mt-4 text-[12.5px] leading-5 text-ink-3">
        Alerts reach this project’s people, and the{" "}
        <Link href={`/projects/${projectId}/notification-targets`} className="underline">
          alert channels
        </Link>{" "}
        that include “A measure crossed its alert”.
      </p>
    </SectionPanel>
  );
}
