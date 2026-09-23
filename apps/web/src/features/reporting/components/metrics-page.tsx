"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import type {
  AggregationName,
  AuthUser,
  ChartFilter,
  DatasetRecord,
  Metric,
  MetricCreatePayload,
  MetricPreviewResponse,
  MetricSqlResponse,
  MetricUsageResponse,
} from "@platform/shared-types";
import { Button, EmptyState, SectionPanel, StatCard } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { DeleteRowButton } from "@/components/ui/delete-row-button";
import { Icon } from "@/components/ui/icon";
import { Modal } from "@/components/ui/modal";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { cx } from "@/lib/utils";

import { describeFilter, parseFilterValue } from "../dashboard-layout";

type MetricsPageProps = {
  currentUser: AuthUser;
  projectId: string;
  initial: Metric[];
  datasets: DatasetRecord[];
};

const AGGREGATIONS: AggregationName[] = ["sum", "avg", "min", "max", "count", "count_distinct", "median"];
const OPERATORS = ["equals", "not_equals", "greater_than", "greater_or_equal", "less_than", "less_or_equal", "contains", "in", "is_null", "not_null"];
const DIALECTS = ["postgres", "mysql", "sqlite", "duckdb"];

const inputClass =
  "h-9 w-full rounded-lg border border-line bg-sunken px-2.5 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)]";

type FilterRow = { column: string; operator: string; value: string };

type Draft = {
  id: string | null;
  dataset_id: string;
  name: string;
  description: string;
  owner_username: string;
  aggregation: AggregationName;
  mode: "column" | "formula";
  column: string;
  formula: string;
  filters: FilterRow[];
  dimensions: string;
};

const EMPTY_DRAFT = (datasetId: string): Draft => ({
  id: null,
  dataset_id: datasetId,
  name: "",
  description: "",
  owner_username: "",
  aggregation: "sum",
  mode: "column",
  column: "",
  formula: "",
  filters: [],
  dimensions: "",
});

/**
 * The semantic layer: every metric defined once, with an owner and a
 * description, resolved by every chart that names it. Define, preview it cut
 * by a dimension, see what uses it before changing it, and copy its SQL for a
 * warehouse -- rendered from the same IR that computes it here.
 */
export function MetricsPageView({ currentUser, projectId, initial, datasets }: MetricsPageProps) {
  const [metrics, setMetrics] = useState(initial);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [columnsByDataset, setColumnsByDataset] = useState<Record<string, string[]>>({});

  const [inspecting, setInspecting] = useState<Metric | null>(null);
  const [previewDimension, setPreviewDimension] = useState("");
  const [preview, setPreview] = useState<MetricPreviewResponse | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [usage, setUsage] = useState<MetricUsageResponse | null>(null);
  const [dialect, setDialect] = useState("postgres");
  const [sql, setSql] = useState<MetricSqlResponse | null>(null);

  const reload = useCallback(async () => {
    setMetrics((await apiFetch<{ items: Metric[] }>(`/projects/${projectId}/metrics`)).items);
  }, [projectId]);

  const loadColumns = useCallback(
    async (datasetId: string) => {
      if (!datasetId || columnsByDataset[datasetId]) return;
      try {
        const response = await apiFetch<{ columns: string[] }>(
          `/projects/${projectId}/datasets/${datasetId}/lineage/columns`,
        );
        setColumnsByDataset((current) => ({ ...current, [datasetId]: response.columns }));
      } catch {
        setColumnsByDataset((current) => ({ ...current, [datasetId]: [] }));
      }
    },
    [projectId, columnsByDataset],
  );

  useEffect(() => {
    if (draft?.dataset_id) void loadColumns(draft.dataset_id);
  }, [draft?.dataset_id, loadColumns]);

  const columns = draft ? (columnsByDataset[draft.dataset_id] ?? []) : [];

  const openNew = () => {
    setError(null);
    setDraft(EMPTY_DRAFT(datasets[0]?.id ?? ""));
  };

  const openEdit = (metric: Metric) => {
    setError(null);
    setDraft({
      id: metric.id,
      dataset_id: metric.dataset_id,
      name: metric.name,
      description: metric.description ?? "",
      owner_username: metric.owner_username ?? "",
      aggregation: metric.aggregation,
      mode: metric.formula ? "formula" : "column",
      column: metric.column ?? "",
      formula: metric.formula ?? "",
      filters: metric.filters.map((filter) => ({
        column: filter.column,
        operator: filter.operator,
        value: Array.isArray(filter.value)
          ? filter.value.map(String).join(", ")
          : filter.value === null || filter.value === undefined
            ? ""
            : String(filter.value),
      })),
      dimensions: metric.dimensions.join(", "),
    });
  };

  const save = async () => {
    if (!draft) return;
    setBusy(true);
    setError(null);
    const filters: ChartFilter[] = draft.filters
      .filter((row) => row.column.trim())
      .map((row) => ({ column: row.column.trim(), operator: row.operator, value: parseFilterValue(row.operator, row.value) }));
    const dimensions = draft.dimensions.split(",").map((item) => item.trim()).filter(Boolean);
    const payload: MetricCreatePayload = {
      dataset_id: draft.dataset_id,
      name: draft.name.trim(),
      description: draft.description.trim() || null,
      owner_username: draft.owner_username.trim() || null,
      aggregation: draft.aggregation,
      column: draft.mode === "column" ? draft.column.trim() || null : null,
      formula: draft.mode === "formula" ? draft.formula.trim() || null : null,
      filters,
      dimensions,
    };
    try {
      if (draft.id) {
        const { dataset_id: _ignored, ...update } = payload;
        void _ignored;
        await apiFetch<Metric>(`/projects/${projectId}/metrics/${draft.id}`, {
          method: "PATCH",
          body: JSON.stringify({ ...update, owner_username: draft.owner_username.trim() }),
        });
        setFeedback(`${payload.name} saved. Every chart that names it now follows the new definition.`);
      } else {
        await apiFetch<Metric>(`/projects/${projectId}/metrics`, { method: "POST", body: JSON.stringify(payload) });
        setFeedback(`${payload.name} defined.`);
      }
      setDraft(null);
      await reload();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const inspect = useCallback(
    async (metric: Metric, dimension: string, chosenDialect: string) => {
      setInspecting(metric);
      setPreview(null);
      setPreviewError(null);
      setUsage(null);
      setSql(null);
      const dims = dimension ? [dimension] : [];
      const [previewResult, usageResult, sqlResult] = await Promise.allSettled([
        apiFetch<MetricPreviewResponse>(`/projects/${projectId}/metrics/${metric.id}/preview`, {
          method: "POST",
          body: JSON.stringify({ dimensions: dims, limit: 50 }),
        }),
        apiFetch<MetricUsageResponse>(`/projects/${projectId}/metrics/${metric.id}/usage`),
        apiFetch<MetricSqlResponse>(
          `/projects/${projectId}/metrics/${metric.id}/sql?dialect=${chosenDialect}&dimensions=${encodeURIComponent(dims.join(","))}`,
        ),
      ]);
      if (previewResult.status === "fulfilled") setPreview(previewResult.value);
      else setPreviewError(extractErrorMessage(previewResult.reason));
      if (usageResult.status === "fulfilled") setUsage(usageResult.value);
      if (sqlResult.status === "fulfilled") setSql(sqlResult.value);
    },
    [projectId],
  );

  const usedTotal = useMemo(() => metrics.reduce((sum, metric) => sum + metric.used_by_charts, 0), [metrics]);

  return (
    <>
      <AppShell
        currentUser={currentUser}
        eyebrow="Semantic layer"
        title="Metrics"
        subtitle="One definition of each number, with an owner. Charts name a metric instead of restating it, so changing the definition changes them all at once — and says what will move first."
        actions={
          <Button onClick={openNew} disabled={datasets.length === 0}>
            Define a metric
          </Button>
        }
      >
        <section className="grid gap-4 md:grid-cols-3">
          <StatCard label="Metrics" value={String(metrics.length)} caption="Definitions in this project." />
          <StatCard label="Charts resolving through them" value={String(usedTotal)} caption="What moves when a definition changes." />
          <StatCard
            label="With an owner"
            value={String(metrics.filter((metric) => metric.owner_username).length)}
            caption="Somebody to ask about the number."
          />
        </section>

        {feedback ? <p className="text-[12.5px] text-accent">{feedback}</p> : null}
        {error && !draft ? (
          <div role="alert" className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
            {error}
          </div>
        ) : null}

        <SectionPanel
          title="Definitions"
          description="Each metric is an aggregation over a column or a row-level formula, with the filters that belong to it and the dimensions it may honestly be cut by. A definition change is a new version."
        >
          {datasets.length === 0 ? (
            <EmptyState title="No datasets yet" description="A metric is defined on a dataset; add data first." />
          ) : metrics.length === 0 ? (
            <EmptyState
              title="No metrics yet"
              description="Start with the number people argue about most — active customers, net revenue — and give it one definition."
              action={<Button onClick={openNew}>Define a metric</Button>}
            />
          ) : (
            <ul className="space-y-2">
              {metrics.map((metric) => (
                <li key={metric.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface px-3.5 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <button type="button" onClick={() => void inspect(metric, "", dialect)} className="text-[13.5px] font-medium text-ink hover:text-accent">
                        {metric.name}
                      </button>
                      <span className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-ink-3">v{metric.version_number}</span>
                      <span className="rounded-full border border-line bg-sunken px-2 py-0.5 text-[10.5px] text-ink-3">
                        {metric.aggregation.replace("_", " ")} of {metric.formula ? metric.formula : metric.column}
                      </span>
                      {metric.filters.map((filter, index) => (
                        <span key={index} className="rounded-full border border-line px-2 py-0.5 text-[10.5px] text-muted">
                          {describeFilter(filter)}
                        </span>
                      ))}
                    </div>
                    <div className="mt-0.5 text-[11.5px] text-muted">
                      on {metric.dataset_name ?? "a dataset"}
                      {metric.owner_username ? ` · owned by ${metric.owner_username}` : " · no owner"}
                      {metric.dimensions.length > 0 ? ` · by ${metric.dimensions.join(", ")}` : " · any dimension"}
                      {` · ${metric.used_by_charts} chart${metric.used_by_charts === 1 ? "" : "s"}`}
                      {` · updated ${formatDate(metric.updated_at)}`}
                    </div>
                    {metric.description ? <p className="mt-1 text-[12px] text-ink-2">{metric.description}</p> : null}
                  </div>
                  <div className="flex items-center gap-2">
                    <Button variant="secondary" size="sm" onClick={() => void inspect(metric, "", dialect)}>
                      Inspect
                    </Button>
                    <Button variant="secondary" size="sm" onClick={() => openEdit(metric)}>
                      Edit
                    </Button>
                    <DeleteRowButton
                      path={`/projects/${projectId}/metrics/${metric.id}`}
                      name={metric.name}
                      kind="metric"
                      consequences={[
                        metric.used_by_charts > 0
                          ? `${metric.used_by_charts} chart(s) resolve through it; the API will refuse until they are re-pointed.`
                          : "No chart resolves through it.",
                      ]}
                      onDeleted={() => setMetrics((current) => current.filter((item) => item.id !== metric.id))}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </SectionPanel>
      </AppShell>

      <Modal
        open={draft !== null}
        title={draft?.id ? `Edit ${draft.name || "metric"}` : "Define a metric"}
        description="Say what the number means once. A chart that names this metric takes the measure and these filters from it; it may add filters of its own but cannot loosen these."
        onClose={() => setDraft(null)}
        widthClassName="max-w-2xl"
        footer={
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setDraft(null)} disabled={busy}>
              Cancel
            </Button>
            <Button size="sm" onClick={() => void save()} disabled={busy || !draft?.name.trim()}>
              {busy ? "Saving…" : draft?.id ? "Save definition" : "Define"}
            </Button>
          </div>
        }
      >
        {draft ? (
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block space-y-1">
                <span className="text-[11px] text-muted">Name</span>
                <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="Net revenue" className={inputClass} />
              </label>
              <label className="block space-y-1">
                <span className="text-[11px] text-muted">Owner (username)</span>
                <input value={draft.owner_username} onChange={(e) => setDraft({ ...draft, owner_username: e.target.value })} placeholder="who to ask" className={inputClass} />
              </label>
            </div>
            <label className="block space-y-1">
              <span className="text-[11px] text-muted">Description</span>
              <textarea value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} rows={2} placeholder="Gross less discount, paid orders only." className="w-full rounded-lg border border-line bg-sunken px-2.5 py-2 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)]" />
            </label>
            <label className="block space-y-1">
              <span className="text-[11px] text-muted">Dataset</span>
              <select value={draft.dataset_id} disabled={draft.id !== null} onChange={(e) => setDraft({ ...draft, dataset_id: e.target.value, column: "", filters: [] })} className={inputClass}>
                {datasets.map((dataset) => (
                  <option key={dataset.id} value={dataset.id}>{dataset.name}</option>
                ))}
              </select>
            </label>
            <div className="grid gap-3 sm:grid-cols-[140px_1fr]">
              <label className="block space-y-1">
                <span className="text-[11px] text-muted">Aggregation</span>
                <select value={draft.aggregation} onChange={(e) => setDraft({ ...draft, aggregation: e.target.value as AggregationName })} className={inputClass}>
                  {AGGREGATIONS.map((item) => (
                    <option key={item} value={item}>{item.replace("_", " ")}</option>
                  ))}
                </select>
              </label>
              <div className="space-y-1">
                <div className="flex items-center gap-2 text-[11px] text-muted">
                  <span>of</span>
                  <div className="flex rounded-md border border-line p-0.5">
                    {(["column", "formula"] as const).map((mode) => (
                      <button key={mode} type="button" onClick={() => setDraft({ ...draft, mode })} className={cx("rounded px-2 py-0.5 text-[11px]", draft.mode === mode ? "bg-[color:var(--accent)] text-accent-ink" : "text-ink-3")}>
                        {mode === "column" ? "a column" : "a formula"}
                      </button>
                    ))}
                  </div>
                </div>
                {draft.mode === "column" ? (
                  <select value={draft.column} onChange={(e) => setDraft({ ...draft, column: e.target.value })} className={inputClass}>
                    <option value="">Choose a column…</option>
                    {columns.map((column) => (
                      <option key={column} value={column}>{column}</option>
                    ))}
                  </select>
                ) : (
                  <input value={draft.formula} onChange={(e) => setDraft({ ...draft, formula: e.target.value })} placeholder="[gross] - [discount]" className={cx(inputClass, "font-mono")} />
                )}
              </div>
            </div>
            <div className="space-y-1">
              <span className="text-[11px] text-muted">Filters that are part of the definition</span>
              {draft.filters.map((row, index) => (
                <div key={index} className="grid grid-cols-[1fr_auto_1fr_auto] items-center gap-2">
                  <select value={row.column} onChange={(e) => setDraft({ ...draft, filters: draft.filters.map((f, i) => (i === index ? { ...f, column: e.target.value } : f)) })} className={inputClass}>
                    <option value="">column…</option>
                    {columns.map((column) => (
                      <option key={column} value={column}>{column}</option>
                    ))}
                  </select>
                  <select value={row.operator} onChange={(e) => setDraft({ ...draft, filters: draft.filters.map((f, i) => (i === index ? { ...f, operator: e.target.value } : f)) })} className="h-9 rounded-lg border border-line bg-sunken px-2 text-[12.5px] text-ink">
                    {OPERATORS.map((op) => (
                      <option key={op} value={op}>{op.replace(/_/g, " ")}</option>
                    ))}
                  </select>
                  <input value={row.value} disabled={row.operator === "is_null" || row.operator === "not_null"} onChange={(e) => setDraft({ ...draft, filters: draft.filters.map((f, i) => (i === index ? { ...f, value: e.target.value } : f)) })} placeholder="value" className={inputClass} />
                  <button type="button" aria-label="Remove filter" onClick={() => setDraft({ ...draft, filters: draft.filters.filter((_, i) => i !== index) })} className="rounded-lg border border-line p-1.5 text-muted hover:border-danger-line hover:text-danger">
                    <Icon name="trash" size={11} />
                  </button>
                </div>
              ))}
              <Button variant="secondary" size="sm" onClick={() => setDraft({ ...draft, filters: [...draft.filters, { column: "", operator: "equals", value: "" }] })}>
                <Icon name="plus" size={11} className="mr-1" />
                Add filter
              </Button>
            </div>
            <label className="block space-y-1">
              <span className="text-[11px] text-muted">Dimensions it may be cut by (comma-separated; empty = any)</span>
              <input value={draft.dimensions} onChange={(e) => setDraft({ ...draft, dimensions: e.target.value })} placeholder="region, plan_tier" className={inputClass} />
            </label>
            {error ? (
              <p role="alert" className="text-sm text-danger">{error}</p>
            ) : null}
          </div>
        ) : null}
      </Modal>

      <Modal
        open={inspecting !== null}
        title={inspecting ? `${inspecting.name} · v${inspecting.version_number}` : "Metric"}
        description="The number now, what resolves through it, and its definition as SQL — rendered from the same IR that computes it here."
        onClose={() => setInspecting(null)}
        widthClassName="max-w-3xl"
        footer={
          <Button variant="secondary" size="sm" onClick={() => setInspecting(null)}>
            Close
          </Button>
        }
      >
        {inspecting ? (
          <div className="space-y-4 text-sm">
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex-1 space-y-1">
                <span className="text-[11px] text-muted">Cut by</span>
                <select value={previewDimension} onChange={(e) => { setPreviewDimension(e.target.value); void inspect(inspecting, e.target.value, dialect); }} className={inputClass}>
                  <option value="">Total only</option>
                  {(inspecting.dimensions.length > 0 ? inspecting.dimensions : (columnsByDataset[inspecting.dataset_id] ?? [])).map((column) => (
                    <option key={column} value={column}>{column}</option>
                  ))}
                </select>
              </label>
              <label className="space-y-1">
                <span className="text-[11px] text-muted">SQL dialect</span>
                <select value={dialect} onChange={(e) => { setDialect(e.target.value); void inspect(inspecting, previewDimension, e.target.value); }} className={inputClass}>
                  {DIALECTS.map((item) => (
                    <option key={item} value={item}>{item}</option>
                  ))}
                </select>
              </label>
            </div>
            {previewError ? (
              <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">{previewError}</div>
            ) : preview === null ? (
              <p className="text-[12.5px] text-muted">Computing…</p>
            ) : (
              <div className="overflow-x-auto rounded-2xl border border-line">
                <table className="min-w-full divide-y divide-line text-left text-[12.5px]">
                  <thead className="bg-surface text-ink-3">
                    <tr>{preview.columns.map((column) => <th key={column} className="cell-pad font-medium">{column}</th>)}</tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {preview.rows.map((row, index) => (
                      <tr key={index}>{preview.columns.map((column) => <td key={column} className="cell-pad text-ink-2">{row[column] === null || row[column] === undefined ? "null" : String(row[column])}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
                {preview.warnings.length > 0 ? <p className="px-3 py-2 text-[11px] text-muted">{preview.warnings.join(" ")}</p> : null}
              </div>
            )}
            <div>
              <div className="text-[11px] uppercase tracking-[0.14em] text-muted">Resolves through it</div>
              {usage === null ? (
                <p className="mt-1 text-[12px] text-muted">Loading…</p>
              ) : usage.charts.length === 0 ? (
                <p className="mt-1 text-[12px] text-muted">No chart names this metric yet — <Link href={`/projects/${projectId}/charts`} className="text-accent">build one</Link>.</p>
              ) : (
                <ul className="mt-1 space-y-1 text-[12.5px]">
                  {usage.charts.map((chart) => (
                    <li key={chart.chart_id} className="text-ink-2">
                      {chart.chart_name} <span className="text-muted">({chart.chart_type})</span>
                      {chart.dashboards.length > 0 ? <span className="text-muted"> · on {chart.dashboards.join(", ")}</span> : null}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-[0.14em] text-muted">As SQL ({dialect})</div>
              {sql === null ? (
                <p className="mt-1 text-[12px] text-muted">Rendering…</p>
              ) : sql.sql ? (
                <pre className="mt-1 overflow-x-auto rounded-xl border border-line bg-sunken p-3 font-mono text-[11.5px] text-ink-2">{sql.sql}</pre>
              ) : (
                <p className="mt-1 text-[12px] text-warning">{sql.reason}</p>
              )}
              {sql?.sql ? (
                <p className="mt-1 text-[10.5px] text-muted">
                  Reads from <code className="font-mono">{sql.source_placeholder}</code>; replace it with the table that holds this data in your warehouse.
                </p>
              ) : null}
            </div>
          </div>
        ) : null}
      </Modal>
    </>
  );
}
