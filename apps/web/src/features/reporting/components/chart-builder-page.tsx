"use client";

import { useCallback, useEffect, useState } from "react";

import type {
  AggregationName,
  AuthUser,
  ChartCatalogResponse,
  ChartData,
  ChartListResponse,
  ChartTypeName,
  DatasetRecord,
  LineageColumnListResponse,
} from "@platform/shared-types";
import { Button, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { DeleteRowButton } from "@/components/ui/delete-row-button";
import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";

import { ChartView } from "./chart-view";

type ChartBuilderPageProps = {
  currentUser: AuthUser;
  projectId: string;
  datasets: DatasetRecord[];
  charts: ChartListResponse;
};

const inputClass =
  "h-9 w-full rounded-lg border border-line bg-sunken px-2.5 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)]";

export function ChartBuilderPageView({
  currentUser,
  projectId,
  datasets,
  charts,
}: ChartBuilderPageProps) {
  const [saved, setSaved] = useState(charts.items);
  const [types, setTypes] = useState<ChartCatalogResponse | null>(null);
  const [datasetId, setDatasetId] = useState(datasets[0]?.id ?? "");
  const [chartType, setChartType] = useState<ChartTypeName>("bar");
  const [dimension, setDimension] = useState("");
  const [measureColumn, setMeasureColumn] = useState("");
  const [aggregation, setAggregation] = useState<AggregationName>("sum");
  const [name, setName] = useState("");
  const [data, setData] = useState<ChartData | null>(null);
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
    // Default the measure to something that can actually be summed. Picking the
    // second column regardless meant the first thing a user saw was an error
    // about summing text.
    const numeric = columns.filter((column) =>
      ["int", "float", "number", "integer", "double", "decimal"].includes(
        (columnTypes[column] ?? "").toLowerCase(),
      ),
    );
    const categorical = columns.filter((column) => !numeric.includes(column));

    setDimension((current) =>
      current && columns.includes(current) ? current : (categorical[0] ?? columns[0]),
    );
    setMeasureColumn((current) =>
      current && columns.includes(current) ? current : (numeric[0] ?? columns[0]),
    );
  }, [columns, columnTypes]);

  const spec = types?.items.find((item) => item.name === chartType);

  const preview = useCallback(async () => {
    if (!datasetId || !measureColumn) return;
    setError(null);
    try {
      setData(
        await apiFetch<ChartData>(`/projects/${projectId}/charts/preview`, {
          method: "POST",
          body: JSON.stringify({
            dataset_id: datasetId,
            chart_type: chartType,
            query: {
              dimensions: spec && spec.max_dimensions === 0 ? [] : [dimension],
              measures: [{ column: measureColumn, aggregation, label: "value" }],
            },
          }),
        }),
      );
    } catch (caught) {
      setData(null);
      setError(extractErrorMessage(caught));
    }
  }, [projectId, datasetId, chartType, dimension, measureColumn, aggregation, spec]);

  useEffect(() => {
    const timer = setTimeout(() => void preview(), 250);
    return () => clearTimeout(timer);
  }, [preview]);

  const save = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/projects/${projectId}/charts`, {
        method: "POST",
        body: JSON.stringify({
          dataset_id: datasetId,
          name: name.trim() || `${aggregation} of ${measureColumn}`,
          chart_type: chartType,
          query: {
            dimensions: spec && spec.max_dimensions === 0 ? [] : [dimension],
            measures: [{ column: measureColumn, aggregation, label: "value" }],
          },
        }),
      });
      setName("");
      setSaved((await apiFetch<ChartListResponse>(`/projects/${projectId}/charts`)).items);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }, [projectId, datasetId, name, chartType, dimension, measureColumn, aggregation, spec]);

  if (datasets.length === 0) {
    return (
      <AppShell
        currentUser={currentUser}
        eyebrow="Consumption"
        title="Charts"
        subtitle="Ask a question of any dataset without leaving the platform."
      >
        <SectionPanel title="Nothing to chart yet">
          <p className="text-[12.5px] text-ink-3">
            Load a dataset first — a chart is a question about data that is already here.
          </p>
        </SectionPanel>
      </AppShell>
    );
  }

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Consumption"
      title="Charts"
      subtitle="Pick a dataset, a grouping, and a number. The preview updates as you change it, and what you save is the question rather than a picture of an answer."
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
                    {dataset.name}
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
                      "rounded-md border px-1 py-1.5 text-[10.5px] capitalize transition",
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
                <p className="mt-1.5 text-[11px] leading-4 text-muted">{spec.description}</p>
              ) : null}
            </Field>

            {spec && spec.max_dimensions > 0 ? (
              <Field label="Group by">
                <select
                  value={dimension}
                  onChange={(event) => setDimension(event.target.value)}
                  className={inputClass}
                >
                  {columns.map((column) => (
                    <option key={column} value={column}>
                      {column}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}

            <Field label="Measure">
              <div className="flex gap-1.5">
                <select
                  value={aggregation}
                  onChange={(event) => setAggregation(event.target.value as AggregationName)}
                  className={cx(inputClass, "w-[110px] shrink-0")}
                >
                  {(types?.aggregations ?? ["sum"]).map((item) => (
                    <option key={item} value={item}>
                      {item.replace("_", " ")}
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

            <div className="border-t border-line pt-3">
              <Field label="Save as">
                <div className="flex gap-1.5">
                  <input
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder={`${aggregation} of ${measureColumn}`}
                    className={inputClass}
                  />
                  <Button onClick={save} disabled={busy || !data}>
                    Save
                  </Button>
                </div>
              </Field>
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
            <div className="flex h-[260px] items-center justify-center text-[12.5px] text-muted">
              Choose a dataset and a measure.
            </div>
          )}
          {data?.warnings.length ? (
            <ul className="mt-2 space-y-1">
              {data.warnings.map((warning) => (
                <li key={warning} className="flex items-start gap-1.5 text-[11.5px] text-warning">
                  <Icon name="info" size={11} className="mt-0.5 shrink-0" />
                  {warning}
                </li>
              ))}
            </ul>
          ) : null}
        </SectionPanel>
      </div>

      <SectionPanel title={`Saved charts (${saved.length})`} description="Drop these onto a dashboard.">
        {saved.length === 0 ? (
          <p className="text-[12.5px] text-muted">Nothing saved yet.</p>
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
                    <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] capitalize text-ink-3">
                      {chart.chart_type}
                    </span>
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
                <div className="mt-1 text-[11.5px] text-muted">
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
