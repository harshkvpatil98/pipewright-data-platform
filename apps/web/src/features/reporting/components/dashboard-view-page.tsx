"use client";

import Link from "next/link";
import { type CSSProperties, useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  AuthUser,
  ChartFilter,
  DashboardDataResponse,
  DashboardDetail,
  DashboardRefreshSeconds,
  DashboardTileData,
  SavedChart,
} from "@platform/shared-types";
import { DASHBOARD_REFRESH_CHOICES } from "@platform/shared-types";
import { Button, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { DiscussionPanel } from "@/features/team/components/discussion-panel";
import { Icon } from "@/components/ui/icon";
import { Modal } from "@/components/ui/modal";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";

import {
  type DraftTile,
  REFRESH_LABELS,
  TILE_WIDTHS,
  clampHeight,
  describeAge,
  describeFilter,
  describeRefresh,
  draftFromTiles,
  moveTile,
  parseFilterValue,
  tileMinHeightPx,
  toTilePayload,
} from "../dashboard-layout";
import { ChartView } from "./chart-view";

type DashboardViewPageProps = {
  currentUser: AuthUser;
  projectId: string;
  initialDashboard: DashboardDetail;
  charts: SavedChart[];
};

const FILTER_OPERATORS = [
  "equals",
  "not_equals",
  "greater_than",
  "greater_or_equal",
  "less_than",
  "less_or_equal",
  "contains",
  "in",
  "is_null",
  "not_null",
];

const inputClass =
  "h-9 w-full rounded-lg border border-line bg-sunken px-3 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)]";

/**
 * A dashboard as a page: every tile computed in one request with the global
 * filters applied, arranged on a twelve-column grid the owner can edit --
 * reorder by drag, resize, add a chart or a block of text, remove -- with an
 * auto-refresh cadence that is stored on the dashboard so everyone who opens
 * it agrees on how fresh the numbers are.
 *
 * Filters have two lives: the saved set (part of the dashboard, applied for
 * everyone including the share link) and an ad-hoc scope somebody applies
 * while looking (computed, never stored, until they choose "Save as default").
 */
export function DashboardViewPage({
  currentUser,
  projectId,
  initialDashboard,
  charts,
}: DashboardViewPageProps) {
  const [dashboard, setDashboard] = useState(initialDashboard);
  const [data, setData] = useState<DashboardDataResponse | null>(null);
  const [dataError, setDataError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  // The filters currently applied to the computation. Null = the saved ones.
  const [adHocFilters, setAdHocFilters] = useState<ChartFilter[] | null>(null);
  const activeFilters = adHocFilters ?? dashboard.filters;
  const filtersDiffer = adHocFilters !== null;

  const compute = useCallback(
    async (filters: ChartFilter[] | null) => {
      setLoading(true);
      setDataError(null);
      try {
        setData(
          await apiFetch<DashboardDataResponse>(
            `/projects/${projectId}/dashboards/${dashboard.id}/data`,
            {
              method: "POST",
              body: JSON.stringify(filters === null ? {} : { filters }),
            },
          ),
        );
      } catch (caught) {
        setDataError(extractErrorMessage(caught));
      } finally {
        setLoading(false);
      }
    },
    [projectId, dashboard.id],
  );

  useEffect(() => {
    // Recompute when the applied scope changes; the saved filters are part of
    // `dashboard`, which changes only through a save that already recomputes.
    void compute(adHocFilters);
  }, [adHocFilters, compute]);

  // Auto-refresh: a timer for the stored cadence, cleared on change/unmount.
  const latestFilters = useRef(adHocFilters);
  latestFilters.current = adHocFilters;
  useEffect(() => {
    if (!dashboard.refresh_seconds) return;
    const handle = window.setInterval(
      () => void compute(latestFilters.current),
      dashboard.refresh_seconds * 1000,
    );
    return () => window.clearInterval(handle);
  }, [dashboard.refresh_seconds, compute]);

  // A ticking "computed x ago" without recomputing anything.
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const handle = window.setInterval(() => setNow(new Date()), 15_000);
    return () => window.clearInterval(handle);
  }, []);

  // ---- layout editing ------------------------------------------------------
  const [editing, setEditing] = useState(false);
  const [drafts, setDrafts] = useState<DraftTile[]>([]);
  const [dragFrom, setDragFrom] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [addChartId, setAddChartId] = useState("");
  // key: null = a new tile; otherwise the draft being edited in place.
  const [textDraft, setTextDraft] = useState<{ key: string | null; title: string; body: string } | null>(null);

  const startEditing = () => {
    setDrafts(draftFromTiles(dashboard.tiles));
    setEditError(null);
    setAddChartId(charts[0]?.id ?? "");
    setEditing(true);
  };

  const saveLayout = async () => {
    setSaving(true);
    setEditError(null);
    try {
      const updated = await apiFetch<DashboardDetail>(
        `/projects/${projectId}/dashboards/${dashboard.id}`,
        { method: "PATCH", body: JSON.stringify({ tiles: toTilePayload(drafts) }) },
      );
      setDashboard(updated);
      setEditing(false);
      setFeedback("Layout saved.");
      void compute(adHocFilters);
    } catch (caught) {
      setEditError(extractErrorMessage(caught));
    } finally {
      setSaving(false);
    }
  };

  const chartById = useMemo(() => new Map(charts.map((chart) => [chart.id, chart])), [charts]);

  // ---- filters ---------------------------------------------------------------
  const [filterModal, setFilterModal] = useState(false);
  const [filterRows, setFilterRows] = useState<{ column: string; operator: string; value: string }[]>([]);
  const [filterBusy, setFilterBusy] = useState(false);
  const [filterError, setFilterError] = useState<string | null>(null);

  const openFilters = () => {
    setFilterRows(
      activeFilters.map((filter) => ({
        column: filter.column,
        operator: filter.operator,
        value: Array.isArray(filter.value)
          ? filter.value.map(String).join(", ")
          : filter.value === null || filter.value === undefined
            ? ""
            : String(filter.value),
      })),
    );
    setFilterError(null);
    setFilterModal(true);
  };

  const buildFilters = (): ChartFilter[] =>
    filterRows
      .filter((row) => row.column.trim())
      .map((row) => ({
        column: row.column.trim(),
        operator: row.operator,
        value: parseFilterValue(row.operator, row.value),
      }));

  const applyFilters = () => {
    setAdHocFilters(buildFilters());
    setFilterModal(false);
  };

  const saveFiltersAsDefault = async () => {
    setFilterBusy(true);
    setFilterError(null);
    try {
      const filters = buildFilters();
      const updated = await apiFetch<DashboardDetail>(
        `/projects/${projectId}/dashboards/${dashboard.id}`,
        { method: "PATCH", body: JSON.stringify({ filters }) },
      );
      setDashboard(updated);
      setAdHocFilters(null);
      setFilterModal(false);
      setFeedback(filters.length === 0 ? "Default filters cleared." : "Default filters saved.");
    } catch (caught) {
      setFilterError(extractErrorMessage(caught));
    } finally {
      setFilterBusy(false);
    }
  };

  // ---- refresh cadence -----------------------------------------------------
  const setRefresh = async (seconds: DashboardRefreshSeconds | null) => {
    try {
      const updated = await apiFetch<DashboardDetail>(
        `/projects/${projectId}/dashboards/${dashboard.id}`,
        { method: "PATCH", body: JSON.stringify({ refresh_seconds: seconds }) },
      );
      setDashboard(updated);
      setFeedback(`Auto-refresh: ${describeRefresh(updated.refresh_seconds)}.`);
    } catch (caught) {
      setDataError(extractErrorMessage(caught));
    }
  };

  // ---- sharing -------------------------------------------------------------
  const copyShareLink = async (token: string) => {
    const url = `${window.location.origin}/shared/dashboards/${token}`;
    try {
      await navigator.clipboard.writeText(url);
      setFeedback("Share link copied.");
    } catch {
      setFeedback(`Copy this link manually: ${url}`);
    }
  };

  const share = async () => {
    try {
      const updated = await apiFetch<DashboardDetail>(
        `/projects/${projectId}/dashboards/${dashboard.id}/share`,
        { method: "POST" },
      );
      setDashboard((current) => ({ ...current, ...updated }));
      if (updated.share_token) await copyShareLink(updated.share_token);
    } catch (caught) {
      setDataError(extractErrorMessage(caught));
    }
  };

  const tilesByKey = useMemo(
    () => new Map((data?.tiles ?? []).map((tile) => [tile.tile_id, tile])),
    [data],
  );

  return (
    <>
      <AppShell
        currentUser={currentUser}
        eyebrow="Dashboard"
        title={dashboard.name}
        subtitle={dashboard.description ?? "Saved charts arranged on one page."}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" size="sm" onClick={() => void compute(adHocFilters)} disabled={loading}>
              <Icon name="refresh" size={12} className={cx("mr-1", loading && "animate-spin")} />
              {loading ? "Refreshing…" : "Refresh"}
            </Button>
            <select
              aria-label="Auto-refresh"
              value={dashboard.refresh_seconds ?? ""}
              onChange={(event) =>
                void setRefresh(
                  event.target.value === "" ? null : (Number(event.target.value) as DashboardRefreshSeconds),
                )
              }
              className="h-8 rounded-lg border border-line bg-sunken px-2 text-[12px] text-ink outline-none"
            >
              <option value="">Manual refresh</option>
              {DASHBOARD_REFRESH_CHOICES.map((seconds) => (
                <option key={seconds} value={seconds}>
                  Refresh {REFRESH_LABELS[seconds]}
                </option>
              ))}
            </select>
            {dashboard.share_token ? (
              <Button variant="secondary" size="sm" onClick={() => void copyShareLink(dashboard.share_token as string)}>
                Copy share link
              </Button>
            ) : (
              <Button variant="secondary" size="sm" onClick={() => void share()}>
                Share
              </Button>
            )}
            {editing ? (
              <>
                <Button variant="ghost" size="sm" onClick={() => setEditing(false)} disabled={saving}>
                  Cancel
                </Button>
                <Button size="sm" onClick={() => void saveLayout()} disabled={saving}>
                  {saving ? "Saving…" : "Save layout"}
                </Button>
              </>
            ) : (
              <Button size="sm" onClick={startEditing}>
                Edit layout
              </Button>
            )}
            <Link
              href={`/projects/${projectId}/dashboards`}
              className="rounded-full border border-line bg-surface px-3 py-1.5 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-2 hover:border-line-strong"
            >
              All dashboards
            </Link>
          </div>
        }
      >
        {/* Global filter bar */}
        <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-line bg-[color:var(--panel)] px-4 py-3">
          <Icon name="filter" size={12} className="text-muted" />
          <span className="text-[11px] uppercase tracking-[0.16em] text-muted">Filters</span>
          {activeFilters.length === 0 ? (
            <span className="text-[12.5px] text-ink-3">None — every tile shows all of its data.</span>
          ) : (
            activeFilters.map((filter, index) => (
              <span
                key={`${filter.column}-${index}`}
                className="rounded-full border border-line bg-sunken px-2.5 py-1 text-[12px] text-ink"
              >
                {describeFilter(filter)}
              </span>
            ))
          )}
          {filtersDiffer ? (
            <span className="rounded-full border border-warning-line bg-warning-soft px-2 py-0.5 text-[10.5px] text-warning">
              applied here only — not saved
            </span>
          ) : null}
          <div className="ml-auto flex items-center gap-2">
            {filtersDiffer ? (
              <Button variant="ghost" size="sm" onClick={() => setAdHocFilters(null)}>
                Back to saved
              </Button>
            ) : null}
            <Button variant="secondary" size="sm" onClick={openFilters}>
              Edit filters
            </Button>
          </div>
        </div>

        {feedback ? <p className="text-[12.5px] text-accent">{feedback}</p> : null}
        {dataError ? (
          <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
            {dataError}
          </div>
        ) : null}

        {editing ? (
          <EditorToolbar
            charts={charts}
            addChartId={addChartId}
            onAddChartId={setAddChartId}
            onAddChart={() => {
              if (!addChartId) return;
              setDrafts((current) => [
                ...current,
                { key: `new-${Date.now()}`, kind: "chart", chart_id: addChartId, width: 6, height: 1 },
              ]);
            }}
            onAddText={() => setTextDraft({ key: null, title: "", body: "" })}
            error={editError}
          />
        ) : null}

        {editing ? (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-12">
            {drafts.map((draft, index) => (
              <section
                key={draft.key}
                draggable
                onDragStart={() => setDragFrom(index)}
                onDragOver={(event) => event.preventDefault()}
                onDrop={() => {
                  if (dragFrom !== null) setDrafts((current) => moveTile(current, dragFrom, index));
                  setDragFrom(null);
                }}
                className={cx(
                  "rounded-2xl border border-dashed border-line-strong bg-[color:var(--panel)] p-3 md:[grid-column:span_var(--tile-w)]",
                  dragFrom === index && "opacity-60",
                )}
                style={{ "--tile-w": draft.width, minHeight: 120 } as CSSProperties}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="cursor-grab select-none text-muted" title="Drag to reorder">
                    <Icon name="menu" size={12} />
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-ink">
                    {draft.kind === "text"
                      ? draft.title || "Text"
                      : (chartById.get(draft.chart_id ?? "")?.name ?? "Chart")}
                  </span>
                  <label className="flex items-center gap-1 text-[11px] text-muted">
                    Width
                    <select
                      value={draft.width}
                      onChange={(event) =>
                        setDrafts((current) =>
                          current.map((item, i) =>
                            i === index ? { ...item, width: Number(event.target.value) } : item,
                          ),
                        )
                      }
                      className="h-7 rounded-md border border-line bg-sunken px-1 text-[11px] text-ink"
                    >
                      {TILE_WIDTHS.map((width) => (
                        <option key={width} value={width}>
                          {width}/12
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex items-center gap-1 text-[11px] text-muted">
                    Height
                    <select
                      value={draft.height}
                      onChange={(event) =>
                        setDrafts((current) =>
                          current.map((item, i) =>
                            i === index ? { ...item, height: clampHeight(Number(event.target.value)) } : item,
                          ),
                        )
                      }
                      className="h-7 rounded-md border border-line bg-sunken px-1 text-[11px] text-ink"
                    >
                      {[1, 2, 3, 4].map((height) => (
                        <option key={height} value={height}>
                          {height} row{height === 1 ? "" : "s"}
                        </option>
                      ))}
                    </select>
                  </label>
                  {draft.kind === "text" ? (
                    <button
                      type="button"
                      className="text-[11px] text-accent"
                      onClick={() =>
                        setTextDraft({ key: draft.key, title: draft.title ?? "", body: draft.body ?? "" })
                      }
                    >
                      Edit text
                    </button>
                  ) : null}
                  <button
                    type="button"
                    aria-label="Remove tile"
                    onClick={() => setDrafts((current) => current.filter((_, i) => i !== index))}
                    className="rounded-lg border border-line p-1 text-muted transition hover:border-danger-line hover:text-danger"
                  >
                    <Icon name="trash" size={11} />
                  </button>
                </div>
                {draft.kind === "text" ? (
                  <p className="mt-2 line-clamp-3 whitespace-pre-line text-[12px] text-ink-2">{draft.body}</p>
                ) : null}
              </section>
            ))}
            {drafts.length === 0 ? (
              <p className="md:col-span-12 text-[12.5px] text-muted">No tiles. Add a chart or some text above.</p>
            ) : null}
          </div>
        ) : data === null && !dataError ? (
          <p className="text-[12.5px] text-muted">Computing tiles…</p>
        ) : dashboard.tiles.length === 0 ? (
          <SectionPanel title="Nothing here yet" description="Add charts or a note with Edit layout.">
            <p className="text-[12.5px] text-muted">
              Build charts in the{" "}
              <Link href={`/projects/${projectId}/charts`} className="text-accent">
                chart builder
              </Link>
              , then place them here.
            </p>
          </SectionPanel>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-12">
            {[...dashboard.tiles]
              .sort((a, b) => a.position - b.position)
              .map((tile) => (
                <TileCard key={tile.id} tile={tilesByKey.get(tile.id)} fallbackTitle={tile.title ?? tile.chart?.name ?? ""} width={tile.width} height={tile.height} />
              ))}
          </div>
        )}

        {data ? (
          <p className="text-[11px] text-muted">
            Computed {describeAge(data.computed_at, now)} · {describeRefresh(dashboard.refresh_seconds)}
            {data.tiles.some((tile) => tile.error) ? " · some tiles could not be computed (see the tile)" : ""}
          </p>
        ) : null}

        <DiscussionPanel
          projectId={projectId}
          targetType="dashboard"
          targetId={dashboard.id}
          currentUsername={currentUser.username}
          description="What this page is for, what changed, what looks wrong. Mention someone with @ and they are notified."
        />
      </AppShell>

      <Modal
        open={textDraft !== null}
        title="Text tile"
        description="A heading and a note. Use it to explain what the page shows, or to state a caveat next to the numbers."
        onClose={() => setTextDraft(null)}
        widthClassName="max-w-lg"
        footer={
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setTextDraft(null)}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={!textDraft || (!textDraft.title.trim() && !textDraft.body.trim())}
              onClick={() => {
                if (!textDraft) return;
                const title = textDraft.title.trim() || null;
                const body = textDraft.body.trim() || null;
                setDrafts((current) =>
                  textDraft.key === null
                    ? [...current, { key: `text-${Date.now()}`, kind: "text", title, body, width: 12, height: 1 }]
                    : current.map((item) => (item.key === textDraft.key ? { ...item, title, body } : item)),
                );
                setTextDraft(null);
              }}
            >
              {textDraft?.key === null ? "Add tile" : "Save text"}
            </Button>
          </div>
        }
      >
        {textDraft ? (
          <div className="space-y-3">
            <label className="block space-y-1">
              <span className="text-[11px] text-muted">Heading</span>
              <input
                value={textDraft.title}
                onChange={(event) => setTextDraft({ ...textDraft, title: event.target.value })}
                className={inputClass}
                placeholder="How to read this page"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-[11px] text-muted">Text</span>
              <textarea
                value={textDraft.body}
                onChange={(event) => setTextDraft({ ...textDraft, body: event.target.value })}
                rows={4}
                className="w-full rounded-lg border border-line bg-sunken px-3 py-2 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)]"
                placeholder="Figures are gross of refunds and refresh nightly."
              />
            </label>
          </div>
        ) : null}
      </Modal>

      <Modal
        open={filterModal}
        title="Dashboard filters"
        description="Applied on top of every chart's own query. Apply to look; save as default to make them part of the dashboard for everyone, share link included."
        onClose={() => setFilterModal(false)}
        widthClassName="max-w-2xl"
        footer={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setFilterModal(false)}>
              Cancel
            </Button>
            <Button variant="secondary" size="sm" onClick={() => void saveFiltersAsDefault()} disabled={filterBusy}>
              {filterBusy ? "Saving…" : "Save as default"}
            </Button>
            <Button size="sm" onClick={applyFilters} disabled={filterBusy}>
              Apply
            </Button>
          </div>
        }
      >
        <div className="space-y-2">
          {filterRows.map((row, index) => (
            <div key={index} className="grid grid-cols-[1fr_auto_1fr_auto] items-center gap-2">
              <input
                value={row.column}
                onChange={(event) =>
                  setFilterRows((current) =>
                    current.map((item, i) => (i === index ? { ...item, column: event.target.value } : item)),
                  )
                }
                placeholder="column"
                className={inputClass}
              />
              <select
                value={row.operator}
                onChange={(event) =>
                  setFilterRows((current) =>
                    current.map((item, i) => (i === index ? { ...item, operator: event.target.value } : item)),
                  )
                }
                className="h-9 rounded-lg border border-line bg-sunken px-2 text-[12.5px] text-ink"
              >
                {FILTER_OPERATORS.map((operator) => (
                  <option key={operator} value={operator}>
                    {operator.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
              <input
                value={row.value}
                disabled={row.operator === "is_null" || row.operator === "not_null"}
                onChange={(event) =>
                  setFilterRows((current) =>
                    current.map((item, i) => (i === index ? { ...item, value: event.target.value } : item)),
                  )
                }
                placeholder={row.operator === "in" ? "a, b, c" : "value"}
                className={inputClass}
              />
              <button
                type="button"
                aria-label="Remove filter"
                onClick={() => setFilterRows((current) => current.filter((_, i) => i !== index))}
                className="rounded-lg border border-line p-1.5 text-muted transition hover:border-danger-line hover:text-danger"
              >
                <Icon name="trash" size={11} />
              </button>
            </div>
          ))}
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setFilterRows((current) => [...current, { column: "", operator: "equals", value: "" }])}
          >
            <Icon name="plus" size={11} className="mr-1" />
            Add filter
          </Button>
          {filterError ? (
            <p role="alert" className="text-sm text-danger">
              {filterError}
            </p>
          ) : null}
        </div>
      </Modal>
    </>
  );
}

function EditorToolbar({
  charts,
  addChartId,
  onAddChartId,
  onAddChart,
  onAddText,
  error,
}: {
  charts: SavedChart[];
  addChartId: string;
  onAddChartId: (id: string) => void;
  onAddChart: () => void;
  onAddText: () => void;
  error: string | null;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-dashed border-line-strong bg-sunken px-4 py-3">
      <span className="text-[11px] uppercase tracking-[0.16em] text-muted">Editing</span>
      <span className="text-[12px] text-ink-3">Drag tiles to reorder, set width and height, then save.</span>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        <select
          value={addChartId}
          onChange={(event) => onAddChartId(event.target.value)}
          className="h-8 max-w-[240px] rounded-lg border border-line bg-surface px-2 text-[12px] text-ink"
          aria-label="Chart to add"
        >
          {charts.length === 0 ? <option value="">No saved charts</option> : null}
          {charts.map((chart) => (
            <option key={chart.id} value={chart.id}>
              {chart.name}
            </option>
          ))}
        </select>
        <Button variant="secondary" size="sm" onClick={onAddChart} disabled={!addChartId}>
          <Icon name="plus" size={11} className="mr-1" />
          Add chart
        </Button>
        <Button variant="secondary" size="sm" onClick={onAddText}>
          <Icon name="plus" size={11} className="mr-1" />
          Add text
        </Button>
      </div>
      {error ? (
        <p role="alert" className="w-full text-sm text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function TileCard({
  tile,
  fallbackTitle,
  width,
  height,
}: {
  tile: DashboardTileData | undefined;
  fallbackTitle: string;
  width: number;
  height: number;
}) {
  // A text tile is as tall as its words; only a chart tile reserves row height.
  const isText = tile?.kind === "text";
  const style = {
    "--tile-w": Math.min(Math.max(width, 2), 12),
    ...(isText ? {} : { minHeight: tileMinHeightPx(height) }),
  } as CSSProperties;
  if (!tile) {
    return (
      <section className="rounded-2xl border border-line bg-[color:var(--panel)] p-4 md:[grid-column:span_var(--tile-w)]" style={style}>
        <h2 className="text-[13.5px] font-semibold text-ink">{fallbackTitle}</h2>
        <p className="mt-2 text-[12px] text-muted">Computing…</p>
      </section>
    );
  }
  if (tile.kind === "text") {
    return (
      <section className="rounded-2xl border border-line bg-[color:var(--panel)] p-5 md:[grid-column:span_var(--tile-w)]" style={style}>
        {tile.title ? <h2 className="text-[15px] font-semibold text-ink">{tile.title}</h2> : null}
        {tile.body ? (
          <p className="mt-1.5 whitespace-pre-line text-[13px] leading-6 text-ink-2">{tile.body}</p>
        ) : null}
      </section>
    );
  }
  return (
    <section className="rounded-2xl border border-line bg-[color:var(--panel)] p-4 md:[grid-column:span_var(--tile-w)]" style={style}>
      <h2 className="text-[13.5px] font-semibold text-ink">{tile.chart_name ?? fallbackTitle}</h2>
      <div className="mt-3">
        {tile.error ? (
          <div className="flex h-[200px] items-center justify-center rounded-xl border border-danger-line bg-danger-soft px-4 text-center text-[12.5px] text-danger">
            {tile.error}
          </div>
        ) : tile.data ? (
          <ChartView data={tile.data} />
        ) : null}
      </div>
      {tile.data?.warnings.length ? (
        <p className="mt-2 text-[11px] text-muted">{tile.data.warnings.join(" ")}</p>
      ) : null}
    </section>
  );
}
