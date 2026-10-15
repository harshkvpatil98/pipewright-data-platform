"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import type {
  AggregationName,
  AuthUser,
  ChartCatalogResponse,
  ChartData,
  ChartListResponse,
  ChartTypeName,
  DatasetRecord,
  LineageColumnListResponse,
  Metric,
} from "@platform/shared-types";
import { CHART_ROW_LIMIT } from "@platform/shared-types";
import {
  Badge,
  Button,
  buttonClassName,
  EmptyState,
  Icon,
  SectionPanel,
} from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { DeleteRowButton } from "@/components/ui/delete-row-button";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatCount } from "@/lib/format";
import { cx } from "@/lib/utils";

import { AGGREGATION_LABELS, chartTitle, chooseChartDefaults } from "@/features/reporting/chart-defaults";

import { ChartView } from "./chart-view";
import { countOf } from "@/lib/format";
import { sentenceLabel } from "@/lib/labels";

type ChartBuilderPageProps = {
  currentUser: AuthUser;
  projectId: string;
  datasets: DatasetRecord[];
  charts: ChartListResponse;
  metrics: Metric[];
};

/** Whether a dataset has more rows than a chart reads. */
export function tooLargeToChart(dataset: Pick<DatasetRecord, "row_count">): boolean {
  return (dataset.row_count ?? 0) > CHART_ROW_LIMIT;
}

const inputClass =
  "h-9 w-full rounded-lg border border-line bg-sunken px-2.5 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)]";

export function ChartBuilderPageView({
  currentUser,
  projectId,
  datasets,
  charts,
  metrics,
}: ChartBuilderPageProps) {
  const [saved, setSaved] = useState(charts.items);
  const [types, setTypes] = useState<ChartCatalogResponse | null>(null);
  // Open on a dataset a chart can read; one too large waits to be chosen.
  const [datasetId, setDatasetId] = useState(
    (datasets.find((dataset) => !tooLargeToChart(dataset)) ?? datasets[0])?.id ?? "",
  );
  // A metric-backed chart: the measure and its filters come from the metric,
  // the chart chooses only how to cut it.
  const [metricId, setMetricId] = useState("");
  const metric = metrics.find((item) => item.id === metricId) ?? null;
  const [chartType, setChartType] = useState<ChartTypeName>("bar");
  const [dimension, setDimension] = useState("");
  const [measureColumn, setMeasureColumn] = useState("");
  // Read by the defaulting effect without re-running it on every pick.
  const measureRef = useRef(measureColumn);
  measureRef.current = measureColumn;
  const [aggregation, setAggregation] = useState<AggregationName>("sum");
  const [name, setName] = useState("");
  const [data, setData] = useState<ChartData | null>(null);
  // Two kinds of problem, shown in two places: a question the preview cannot
  // draw is explained beside the preview in a neutral voice, because it often
  // appears before the user has chosen anything; a failed save is an error.
  const [previewProblem, setPreviewProblem] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiFetch<ChartCatalogResponse>("/charts/types")
      .then(setTypes)
      .catch(() => setTypes(null));
  }, []);

  // The dataset *list* carries no schema -- only the detail does -- so columns
  // are fetched per selection rather than read off the row. Doing it the other
  // way silently produced an empty picker, which is the sort of failure that
  // looks like "the page is broken" rather than "a field is missing".
  const [columns, setColumns] = useState<string[]>([]);
  const [columnTypes, setColumnTypes] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!datasetId) {
      setColumns([]);
      return;
    }
    let cancelled = false;
    apiFetch<LineageColumnListResponse>(
      `/projects/${projectId}/datasets/${datasetId}/lineage/columns`,
    )
      .then((response) => {
        if (cancelled) return;
        setColumns(response.columns);
        setColumnTypes(response.types ?? {});
      })
      .catch(() => {
        if (cancelled) return;
        setColumns([]);
        setColumnTypes({});
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, datasetId]);

  useEffect(() => {
    if (columns.length === 0) return;
    const defaults = chooseChartDefaults(columns, columnTypes);
    setDimension((current) =>
      current && columns.includes(current) ? current : defaults.dimension,
    );
    const current = measureRef.current;
    if (!current || !columns.includes(current)) {
      setMeasureColumn(defaults.measure);
      setAggregation(defaults.aggregation);
    }
  }, [columns, columnTypes]);

  const spec = types?.items.find((item) => item.name === chartType);

  // KPI period comparison: which date column, and how wide a period. Only a
  // KPI has a "previous period" to speak of, so the option is offered there.
  const [compareColumn, setCompareColumn] = useState("");
  const [comparePeriod, setComparePeriod] = useState<"day" | "week" | "month" | "quarter" | "year">("month");
  const dateish = columns.filter((column) =>
    ["date", "datetime", "timestamp", "time"].some((kind) =>
      (columnTypes[column] ?? "").toLowerCase().includes(kind),
    ),
  );
  const options =
    chartType === "kpi" && compareColumn
      ? { compare: { date_column: compareColumn, period: comparePeriod } }
      : null;

  const chosen = datasets.find((dataset) => dataset.id === datasetId);
  const tooLarge = chosen ? tooLargeToChart(chosen) : false;

  const preview = useCallback(async () => {
    if (!datasetId || (!measureColumn && !metric)) return;
    setPreviewProblem(null);
    if (tooLarge && chosen) {
      // Said here, not by asking the API for a refusal it is known to give.
      setData(null);
      setPreviewProblem(
        `“${chosen.name}” has ${formatCount(chosen.row_count ?? 0)} rows, more than the ${formatCount(CHART_ROW_LIMIT)} a chart reads. Make a smaller dataset with a recipe first, for example one that groups or filters it.`,
      );
      return;
    }
    try {
      setData(
        await apiFetch<ChartData>(`/projects/${projectId}/charts/preview`, {
          method: "POST",
          body: JSON.stringify({
            dataset_id: datasetId,
            chart_type: chartType,
            query: {
              dimensions: spec && spec.max_dimensions === 0 ? [] : [dimension],
              measures: metric ? [] : [{ column: measureColumn, aggregation, label: "value" }],
            },
            options,
            metric_id: metric ? metric.id : null,
          }),
        }),
      );
    } catch (caught) {
      setData(null);
      setPreviewProblem(extractErrorMessage(caught));
    }
    // `options` is derived from compareColumn/comparePeriod, listed here.
  }, [projectId, datasetId, chartType, dimension, measureColumn, aggregation, spec, compareColumn, comparePeriod, metric, tooLarge, chosen]);

  useEffect(() => {
    const timer = setTimeout(() => void preview(), 250);
    return () => clearTimeout(timer);
  }, [preview]);

  const suggestedName = metric
    ? `${metric.name} by ${dimension}`
    : chartTitle(aggregation, measureColumn, spec && spec.max_dimensions === 0 ? null : dimension);
  // The chart just saved, offered straight onto a dashboard: going to
  // Dashboards, starting one and ticking this chart was four more clicks.
  const [justSaved, setJustSaved] = useState<{ id: string; name: string } | null>(null);
  const [placing, setPlacing] = useState(false);
  const router = useRouter();

  const putOnNewDashboard = useCallback(async () => {
    if (!justSaved) return;
    setPlacing(true);
    setError(null);
    try {
      const created = await apiFetch<{ id: string }>(`/projects/${projectId}/dashboards`, {
        method: "POST",
        body: JSON.stringify({
          name: justSaved.name,
          description: null,
          tiles: [{ chart_id: justSaved.id, position: 0 }],
        }),
      });
      router.push(`/projects/${projectId}/dashboards/${created.id}`);
    } catch (caught) {
      setError(extractErrorMessage(caught));
      setPlacing(false);
    }
  }, [justSaved, projectId, router]);

  const save = useCallback(async () => {
    setBusy(true);
    setError(null);
    setJustSaved(null);
    try {
      const chartName = name.trim() || suggestedName;
      const created = await apiFetch<{ id: string; name: string }>(`/projects/${projectId}/charts`, {
        method: "POST",
        body: JSON.stringify({
          dataset_id: datasetId,
          name: chartName,
          chart_type: chartType,
          query: {
            dimensions: spec && spec.max_dimensions === 0 ? [] : [dimension],
            measures: metric ? [] : [{ column: measureColumn, aggregation, label: "value" }],
          },
          options,
          metric_id: metric ? metric.id : null,
        }),
      });
      setName("");
      setJustSaved({ id: created.id, name: created.name ?? chartName });
      setSaved((await apiFetch<ChartListResponse>(`/projects/${projectId}/charts`)).items);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }, [projectId, datasetId, name, suggestedName, chartType, dimension, measureColumn, aggregation, spec, options, metric]);

  if (datasets.length === 0) {
    return (
      <AppShell
        currentUser={currentUser}
        title="Charts"
        subtitle="Ask a question of a dataset and save the answer as a chart."
      >
        <EmptyState
          title="Nothing to chart yet"
          description="A chart answers a question about data that is already here. Add some data first."
          action={
            <Link href={`/projects/${projectId}/sources`} className={buttonClassName("primary", "sm")}>
              Add data
            </Link>
          }
        />
      </AppShell>
    );
  }

  return (
    <AppShell
      currentUser={currentUser}
      title="Charts"
      subtitle="Ask a question of a dataset and save the answer as a chart."
    >
      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
        <SectionPanel title="Build it">
          <div className="space-y-3">
            <Field label="Dataset">
              <select
                value={datasetId}
                onChange={(event) => setDatasetId(event.target.value)}
                className={inputClass}
              >
                {datasets.map((dataset) => (
                  <option key={dataset.id} value={dataset.id}>
                    {tooLargeToChart(dataset) ? `${dataset.name} (too large to chart)` : dataset.name}
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Chart">
              <div className="grid grid-cols-4 gap-1">
                {(types?.items ?? []).map((item) => (
                  <button
                    key={item.name}
                    type="button"
                    title={item.description}
                    onClick={() => setChartType(item.name)}
                    className={cx(
                      "rounded-md border px-1 py-1.5 text-[12px] capitalize transition",
                      chartType === item.name
                        ? "border-[color:var(--accent)] bg-[color:var(--accent-faint)] text-ink"
                        : "border-line text-ink-3 hover:text-ink",
                    )}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
              {spec ? (
                <p className="mt-1.5 text-[12px] leading-4 text-muted">{spec.description}</p>
              ) : null}
            </Field>

            {spec && spec.max_dimensions > 0 ? (
              <Field label="Group by">
                <select
                  value={dimension}
                  onChange={(event) => setDimension(event.target.value)}
                  className={inputClass}
                >
                  {(metric && metric.dimensions.length > 0 ? metric.dimensions : columns).map((column) => (
                    <option key={column} value={column}>
                      {column}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}

            {metrics.length > 0 ? (
              <Field label="Metric">
                <select
                  value={metricId}
                  onChange={(event) => {
                    const next = metrics.find((item) => item.id === event.target.value) ?? null;
                    setMetricId(event.target.value);
                    if (next) {
                      setDatasetId(next.dataset_id);
                      if (next.dimensions.length > 0 && !next.dimensions.includes(dimension)) {
                        setDimension(next.dimensions[0]);
                      }
                    }
                  }}
                  className={inputClass}
                >
                  <option value="">None (measure a column directly)</option>
                  {metrics.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name} · v{item.version_number}
                    </option>
                  ))}
                </select>
                <p className="mt-1.5 text-[12px] leading-4 text-muted">
                  {metric
                    ? `${sentenceLabel(metric.aggregation)} of ${metric.formula ?? metric.column}${metric.filters.length ? `, ${countOf(metric.filters.length, "filter")} built in` : ""}. The chart follows the definition when it changes.`
                    : "Name a metric instead of restating a measure, so every chart agrees on the number."}
                </p>
              </Field>
            ) : null}

            {metric ? null : (
            <Field label="Measure">
              <div className="grid grid-cols-[minmax(0,110px)_minmax(0,1fr)] gap-1.5">
                <select
                  value={aggregation}
                  onChange={(event) => setAggregation(event.target.value as AggregationName)}
                  className={inputClass}
                >
                  {(types?.aggregations ?? ["sum"]).map((item) => (
                    <option key={item} value={item}>
                      {AGGREGATION_LABELS[item] ?? item.replace("_", " ")}
                    </option>
                  ))}
                </select>
                <select
                  value={measureColumn}
                  onChange={(event) => setMeasureColumn(event.target.value)}
                  className={inputClass}
                >
                  {columns.map((column) => (
                    <option key={column} value={column}>
                      {column}
                    </option>
                  ))}
                </select>
              </div>
            </Field>
            )}

            {chartType === "kpi" ? (
              <Field label="Compare with the previous period">
                <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,110px)] gap-1.5">
                  <select
                    value={compareColumn}
                    onChange={(event) => setCompareColumn(event.target.value)}
                    className={inputClass}
                  >
                    <option value="">No comparison</option>
                    {(dateish.length > 0 ? dateish : columns).map((column) => (
                      <option key={column} value={column}>
                        {column}
                      </option>
                    ))}
                  </select>
                  <select
                    value={comparePeriod}
                    onChange={(event) => setComparePeriod(event.target.value as typeof comparePeriod)}
                    disabled={!compareColumn}
                    className={inputClass}
                  >
                    {(["day", "week", "month", "quarter", "year"] as const).map((period) => (
                      <option key={period} value={period}>
                        {period}
                      </option>
                    ))}
                  </select>
                </div>
                <p className="mt-1.5 text-[12px] leading-4 text-muted">
                  {compareColumn
                    ? `The headline becomes the latest ${comparePeriod} in ${compareColumn}, with the change against the ${comparePeriod} before.`
                    : "Pick a date column to show the latest period against the one before it."}
                </p>
              </Field>
            ) : null}

            <div className="border-t border-line pt-3">
              <Field label="Save as">
                <div className="flex gap-1.5">
                  <input
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder={suggestedName}
                    className={inputClass}
                  />
                  <Button onClick={save} disabled={busy || !data}>
                    {busy ? "Saving…" : "Save"}
                  </Button>
                </div>
              </Field>
              {justSaved ? (
                <div
                  role="status"
                  className="mt-3 rounded-xl border border-success-line bg-success-soft p-3"
                >
                  <p className="flex items-center gap-1.5 text-[13px] font-medium text-success">
                    <Icon name="check" size={14} className="shrink-0" />
                    Saved as “{justSaved.name}”
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button size="sm" onClick={() => void putOnNewDashboard()} disabled={placing}>
                      {placing ? "Making the dashboard…" : "Put it on a new dashboard"}
                    </Button>
                    <Link
                      href={`/projects/${projectId}/dashboards`}
                      className={buttonClassName("ghost", "sm")}
                    >
                      Add to an existing one
                    </Link>
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </SectionPanel>

        <SectionPanel
          title="Preview"
          description={
            data?.truncated
              ? "Showing part of the result; add a filter to narrow it."
              : "Updates as you change the question."
          }
        >
          {data ? <ChartView data={data} /> : (
            <div className="flex h-[260px] flex-col items-center justify-center gap-2 px-6 text-center">
              {previewProblem ? (
                <>
                  <span className="text-[13px] font-medium text-ink">
                    This combination cannot be drawn yet
                  </span>
                  <span className="max-w-md text-[13px] text-ink-3">{previewProblem}</span>
                  {tooLarge ? null : (
                    <span className="text-[12px] text-muted">Try a different measure, or count rows instead.</span>
                  )}
                </>
              ) : (
                <span className="text-[13px] text-muted">Choose a dataset and a measure.</span>
              )}
            </div>
          )}
          {data?.warnings.length ? (
            <ul className="mt-2 space-y-1">
              {data.warnings.map((warning) => (
                <li key={warning} className="flex items-start gap-1.5 text-[12px] text-warning">
                  <Icon name="info" size={11} className="mt-0.5 shrink-0" />
                  {warning}
                </li>
              ))}
            </ul>
          ) : null}
        </SectionPanel>
      </div>

      <SectionPanel
        title={`Saved charts (${saved.length})`}
        description="Put them on a dashboard to share several together."
        actions={
          saved.length > 0 ? (
            <Link href={`/projects/${projectId}/dashboards`} className={buttonClassName("secondary", "sm")}>
              Go to dashboards
            </Link>
          ) : null
        }
      >
        {saved.length === 0 ? (
          <p className="text-[13px] text-muted">Nothing saved yet. Save the chart above and it appears here.</p>
        ) : (
          <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {saved.map((chart) => (
              <li
                key={chart.id}
                className="rounded-xl border border-line bg-surface px-3 py-2.5"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="text-[13px] text-ink">{chart.name}</span>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <Badge className="capitalize">
                      {chart.chart_type}
                      {chart.metric_name ? ` · ${chart.metric_name}` : ""}
                    </Badge>
                    <DeleteRowButton
                      path={`/projects/${projectId}/charts/${chart.id}`}
                      name={chart.name}
                      kind="chart"
                      consequences={[
                        "Any dashboard tile or scheduled report built on it stops having a subject.",
                      ]}
                      onDeleted={() =>
                        setSaved((current) => current.filter((row) => row.id !== chart.id))
                      }
                      className="rounded-lg p-1 text-muted transition hover:text-danger"
                    />
                  </div>
                </div>
                <div className="mt-1 text-[12px] text-muted">
                  {chart.dataset_name} · {chart.query.measures[0]?.aggregation} of{" "}
                  {chart.query.measures[0]?.column}
                </div>
              </li>
            ))}
          </ul>
        )}
      </SectionPanel>
    </AppShell>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <span className="mb-1.5 block text-[12px] font-medium text-ink">{label}</span>
      {children}
    </div>
  );
}

