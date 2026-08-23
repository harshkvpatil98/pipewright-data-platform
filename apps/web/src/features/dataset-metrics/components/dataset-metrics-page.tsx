"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import type {
  Anomaly,
  AnomalyScan,
  AnomalySensitivity,
  AuthUser,
  FreshnessPolicy,
  FreshnessPolicyListResponse,
  IncidentSeverity,
  MetricHistory,
  MetricSeries,
} from "@platform/shared-types";
import { Button, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";

import { CHART_HEIGHT, CHART_WIDTH, buildSparkline, formatMetric } from "../sparkline";

type DatasetMetricsPageProps = {
  currentUser: AuthUser;
  projectId: string;
  datasetId: string;
  initialHistory: MetricHistory;
  initialAnomalies: AnomalyScan;
};

const SEVERITY_TONE: Record<IncidentSeverity, string> = {
  critical: "border-danger-line bg-danger-soft text-danger",
  high: "border-warning-line bg-warning-soft text-warning",
  medium: "border-warning-line bg-warning-soft text-warning",
  low: "border-line bg-surface-2 text-ink-3",
};

const SENSITIVITIES: AnomalySensitivity[] = ["low", "medium", "high"];

const AGE_PRESETS = [
  { label: "1 hour", minutes: 60 },
  { label: "6 hours", minutes: 360 },
  { label: "1 day", minutes: 1440 },
  { label: "1 week", minutes: 10080 },
];

export function DatasetMetricsPageView({
  currentUser,
  projectId,
  datasetId,
  initialHistory,
  initialAnomalies,
}: DatasetMetricsPageProps) {
  const [history, setHistory] = useState(initialHistory);
  const [scan, setScan] = useState(initialAnomalies);
  const [sensitivity, setSensitivity] = useState<AnomalySensitivity>(initialAnomalies.sensitivity);
  const [policy, setPolicy] = useState<FreshnessPolicy | null>(null);
  // A ref, not the loaded flag: putting that in the effect's dependencies would
  // make the effect cancel the very request that resolves it.
  const policyRequested = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(
    async (nextSensitivity: AnomalySensitivity = sensitivity) => {
      setError(null);
      try {
        const [nextHistory, nextScan] = await Promise.all([
          apiFetch<MetricHistory>(`/projects/${projectId}/datasets/${datasetId}/metrics`),
          apiFetch<AnomalyScan>(
            `/projects/${projectId}/datasets/${datasetId}/anomalies?sensitivity=${nextSensitivity}`,
          ),
        ]);
        setHistory(nextHistory);
        setScan(nextScan);
      } catch (caught) {
        setError(extractErrorMessage(caught));
      }
    },
    [projectId, datasetId, sensitivity],
  );

  const capture = useCallback(async () => {
    setBusy("capture");
    setError(null);
    try {
      await apiFetch(`/projects/${projectId}/datasets/${datasetId}/metrics/capture`, {
        method: "POST",
      });
      await refresh();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(null);
    }
  }, [projectId, datasetId, refresh]);

  const loadPolicy = useCallback(async () => {
    try {
      const response = await apiFetch<FreshnessPolicyListResponse>(
        `/projects/${projectId}/freshness-policies`,
      );
      setPolicy(response.items.find((item) => item.dataset_id === datasetId) ?? null);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    }
  }, [projectId, datasetId]);

  useEffect(() => {
    if (policyRequested.current) return;
    policyRequested.current = true;
    void loadPolicy();
  }, [loadPolicy]);

  const savePolicy = useCallback(
    async (minutes: number) => {
      setBusy("policy");
      setError(null);
      try {
        if (policy) {
          setPolicy(
            await apiFetch<FreshnessPolicy>(
              `/projects/${projectId}/freshness-policies/${policy.id}`,
              { method: "PATCH", body: JSON.stringify({ max_age_minutes: minutes }) },
            ),
          );
        } else {
          setPolicy(
            await apiFetch<FreshnessPolicy>(`/projects/${projectId}/freshness-policies`, {
              method: "POST",
              body: JSON.stringify({ dataset_id: datasetId, max_age_minutes: minutes }),
            }),
          );
        }
      } catch (caught) {
        setError(extractErrorMessage(caught));
      } finally {
        setBusy(null);
      }
    },
    [projectId, datasetId, policy],
  );

  const flagged = scan.anomalies.filter((item) => item.status === "anomalous");

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Trust"
      title={`Metrics · ${scan.dataset_name}`}
      subtitle="Row counts, null rates, and completeness tracked across every run, with a baseline learned from the dataset's own history rather than a threshold somebody guessed."
    >
      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <Link
          href={`/projects/${projectId}/datasets/${datasetId}`}
          className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1.5 text-[12px] text-ink-2 transition hover:bg-surface-2"
        >
          <Icon name="chevronLeft" size={12} />
          Dataset
        </Link>
        <Link
          href={`/projects/${projectId}/datasets/${datasetId}/lineage`}
          className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1.5 text-[12px] text-ink-2 transition hover:bg-surface-2"
        >
          <Icon name="merge" size={12} />
          Lineage
        </Link>
      </div>

      <SectionPanel
        title="Is this run normal?"
        description={scan.summary}
        actions={
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg border border-line p-0.5">
              {SENSITIVITIES.map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => {
                    setSensitivity(value);
                    void refresh(value);
                  }}
                  className={cx(
                    "rounded-md px-2 py-1 text-[11.5px] capitalize transition",
                    sensitivity === value
                      ? "bg-[color:var(--accent)] text-accent-ink"
                      : "text-ink-3 hover:text-ink",
                  )}
                >
                  {value}
                </button>
              ))}
            </div>
            <Button variant="secondary" onClick={capture} disabled={busy !== null}>
              {busy === "capture" ? "Recording…" : "Record now"}
            </Button>
          </div>
        }
      >
        {flagged.length === 0 ? (
          <p className="rounded-lg border border-line px-3 py-2.5 text-[12.5px] text-ink-3">
            Nothing is outside its usual range.
          </p>
        ) : (
          <ul className="space-y-2">
            {flagged.map((anomaly) => (
              <AnomalyRow key={`${anomaly.metric_key}-${anomaly.column_name ?? ""}`} anomaly={anomaly} />
            ))}
          </ul>
        )}
      </SectionPanel>

      <SectionPanel
        title="History"
        description="Each point is one recorded run. Backfilled runs are plotted at the slot they stand for."
      >
        {history.series.length === 0 ? (
          <p className="text-[12.5px] text-muted">
            No measurements yet. Metrics are recorded automatically whenever a workflow produces
            this dataset, or you can record the current profile now.
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {history.series.map((series) => (
              <MetricCard key={`${series.metric_key}-${series.column_name ?? ""}`} series={series} />
            ))}
          </div>
        )}
      </SectionPanel>

      <SectionPanel
        title="Freshness"
        description="Staleness is the failure that reports nothing: yesterday's numbers keep being served as though they were today's."
      >
        <div className="flex flex-wrap items-center gap-2">
          {AGE_PRESETS.map((preset) => (
            <button
              key={preset.minutes}
              type="button"
              disabled={busy !== null}
              onClick={() => void savePolicy(preset.minutes)}
              className={cx(
                "rounded-lg border px-2.5 py-1.5 text-[12px] transition",
                policy?.max_age_minutes === preset.minutes
                  ? "border-[color:var(--accent)] bg-[color:var(--accent-soft)] text-ink"
                  : "border-line text-ink-3 hover:text-ink",
              )}
            >
              Under {preset.label}
            </button>
          ))}
        </div>
        {policy ? (
          <p className="mt-3 text-[12px] text-ink-3">
            {policy.last_status
              ? `Last checked: ${policy.last_status}${
                  policy.last_age_minutes !== null
                    ? ` (${Math.round(policy.last_age_minutes)} minutes old)`
                    : ""
                }.`
              : "Not checked yet — run a freshness check from the incidents page."}
          </p>
        ) : (
          <p className="mt-3 text-[12px] text-muted">
            No promise set. Pick a limit and a breach will open an incident.
          </p>
        )}
      </SectionPanel>
    </AppShell>
  );
}

function AnomalyRow({ anomaly }: { anomaly: Anomaly }) {
  return (
    <li className="flex items-start justify-between gap-3 rounded-lg border border-line bg-surface px-3 py-2.5">
      <div className="min-w-0">
        <div className="text-[13px] capitalize text-ink">{anomaly.label}</div>
        <p className="mt-0.5 text-[12px] text-ink-3">{anomaly.explanation}</p>
      </div>
      <span
        className={cx(
          "shrink-0 rounded-full border px-2 py-0.5 text-[10.5px] capitalize",
          SEVERITY_TONE[anomaly.severity],
        )}
      >
        {anomaly.severity}
      </span>
    </li>
  );
}

function MetricCard({ series }: { series: MetricSeries }) {
  const shape = buildSparkline(series.points.map((point) => point.value));
  const rising = (series.change_percentage ?? 0) > 0;

  return (
    <div className="rounded-xl border border-line bg-surface px-3 py-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-[11.5px] capitalize text-ink-3">{series.label}</span>
        {series.change_percentage !== null ? (
          <span
            className={cx(
              "shrink-0 text-[11px]",
              rising ? "text-success" : "text-danger",
            )}
          >
            {rising ? "+" : ""}
            {series.change_percentage.toFixed(1)}%
          </span>
        ) : null}
      </div>
      <div className="mt-0.5 text-[18px] font-semibold text-ink">
        {formatMetric(series.latest, series.unit)}
      </div>
      <svg
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        preserveAspectRatio="none"
        className="mt-2 h-8 w-full"
        role="img"
        aria-label={`${series.label} over the last ${series.points.length} runs`}
      >
        {shape.area ? (
          <path d={shape.area} className="fill-[color:var(--accent)] opacity-10" />
        ) : null}
        {shape.line ? (
          <path
            d={shape.line}
            fill="none"
            strokeWidth={1.5}
            vectorEffect="non-scaling-stroke"
            className="stroke-[color:var(--accent)]"
          />
        ) : null}
        {shape.last ? (
          <circle
            cx={shape.last.x}
            cy={shape.last.y}
            r={1.8}
            className="fill-[color:var(--accent)]"
          />
        ) : null}
      </svg>
      <div className="mt-1 text-[10.5px] text-muted">
        {series.points.length} run{series.points.length === 1 ? "" : "s"}
      </div>
    </div>
  );
}
