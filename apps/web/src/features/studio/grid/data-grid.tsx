"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { cx } from "@/lib/utils";
import {
  DEFAULT_COLUMN_WIDTH,
  ROW_HEADER_WIDTH,
  autofitWidth,
  cellAtPoint,
  cellRect,
  contentSize,
  layoutColumns,
  resizedWidth,
  scrollToShow,
  visibleColumns,
  visibleRows,
  type CellAddress,
  type LayoutColumn,
  type Viewport,
} from "@/features/studio/grid/grid-geometry";
import {
  clamp,
  extendTo,
  isSelected,
  jump,
  page,
  selectAll,
  selectCell,
  selectColumn,
  selectRow,
  selectionSize,
  step,
  tabTarget,
  type Direction,
  type Selection,
} from "@/features/studio/grid/grid-selection";
import { fromTsv, pasteWrites, squareOff, toTsv } from "@/features/studio/grid/grid-clipboard";
import {
  describeProfile,
  profileColumn,
  qualityBands,
  type ColumnProfile,
} from "@/features/studio/grid/column-profile";
import {
  cycleSort,
  moveColumn,
  orderColumns,
  toggleFreeze,
  type ColumnState,
  type SortDirection,
} from "@/features/studio/grid/column-state";
import {
  fitText,
  formatCell,
  isNumericType,
  readPalette,
  typeGlyph,
  type GridPalette,
} from "@/features/studio/grid/grid-theme";

export type GridColumn = {
  name: string;
  /**
   * The column's type, used for the header glyph and numeric alignment.
   * Prefers the canonical type where the API supplies one -- `decimal(18,2)`
   * says more than `float` does.
   */
  type?: string;
};

export type DataGridProps = {
  columns: GridColumn[];
  rows: Record<string, unknown>[];
  rowHeight?: number;
  className?: string;
  /**
   * Called when a cell is committed.
   *
   * Absent means the grid is read-only, which is still the Studio's state: a
   * dataset preview is a replayable recipe, so changing one cell there would
   * have to become a step that rewrites every matching value, and that would
   * surprise people badly. The Table editor supplies this handler, because a
   * live table has row identity and can say WHICH row changed.
   */
  onEditCell?: (address: CellAddress, value: string) => void;
  /** The column the data is sorted by, read from the pipeline's steps. */
  sort?: { column: string; direction: SortDirection } | null;
  /**
   * Called when a header is clicked. Sorting is a STEP, not a view operation:
   * the grid holds a page of rows, so sorting what is loaded would order a
   * sample and present it as the order of the table.
   */
  onSortChange?: (sort: { column: string; direction: SortDirection } | null) => void;
  /**
   * True when the rows no longer reflect the current steps -- the last request
   * failed and this is the previous result. Shown rather than hidden: a grid
   * that quietly displays stale data is worse than one that says so.
   */
  stale?: boolean;
  emptyMessage?: string;
  /**
   * Called with the focused cell whenever it moves.
   *
   * The grid owns its selection, so a page that wants to act on "the current
   * row" -- delete it, undo it -- would otherwise have to keep a second,
   * always-slightly-wrong copy of where the cursor is.
   */
  onFocusChange?: (address: CellAddress) => void;
  /** Row indices to tint, keyed by what the caller wants to say about them. */
  rowStates?: Record<number, "edited" | "deleted" | "new">;
  /**
   * Right-click on a column header. The grid resolves which column was hit --
   * with virtualisation, frozen columns and reordering, nothing outside it can.
   */
  onColumnMenu?: (column: string, at: { x: number; y: number }) => void;
};

/** Rows read to build the header quality bar and the column profile. */
const PROFILE_SAMPLE = 1_000;
const HEADER_LABEL_HEIGHT = 30;
const QUALITY_BAR_HEIGHT = 4;
const HEADER_HEIGHT = HEADER_LABEL_HEIGHT + QUALITY_BAR_HEIGHT;
const FONT = '13px ui-sans-serif, -apple-system, "Segoe UI", sans-serif';
const HEADER_FONT = '600 11px ui-sans-serif, -apple-system, "Segoe UI", sans-serif';

export function DataGrid({
  columns,
  rows,
  rowHeight = 32,
  className,
  onEditCell,
  onFocusChange,
  rowStates,
  onColumnMenu,
  sort = null,
  onSortChange,
  stale = false,
  emptyMessage = "No rows to show.",
}: DataGridProps) {
  /* A callback ref rather than useRef: the grid renders an empty-state branch
     until the preview arrives, so the scroll container does not exist on first
     paint. With `useRef` plus `[]`-dependency effects, the measurement and the
     palette read both ran once against null and never again -- the canvas kept
     its default 300x150 and the grid rendered blank. Tracking the node in state
     re-runs them the moment it attaches. */
  const [scrollEl, setScrollEl] = useState<HTMLDivElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const attachScroll = useCallback((node: HTMLDivElement | null) => {
    scrollRef.current = node;
    setScrollEl(node);
  }, []);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [viewport, setViewport] = useState<Viewport>({
    width: 0,
    height: 0,
    scrollLeft: 0,
    scrollTop: 0,
  });
  const [columnState, setColumnState] = useState<ColumnState>({
    widths: {},
    order: [],
    frozenCount: 0,
    sort: null,
  });
  const [openProfile, setOpenProfile] = useState<string | null>(null);
  const widths = columnState.widths;
  const setWidths = useCallback(
    (update: (current: Record<string, number>) => Record<string, number>) =>
      setColumnState((current) => ({ ...current, widths: update(current.widths) })),
    []
  );
  const [selection, setSelection] = useState<Selection>(() => selectCell({ row: 0, column: 0 }));
  const [editing, setEditing] = useState<{ address: CellAddress; value: string } | null>(null);

  // Reported in an effect rather than from each handler: focus moves from
  // clicks, arrows, tab, paste and autofit, and one of those would be missed.
  useEffect(() => {
    onFocusChange?.(selection.focus);
  }, [onFocusChange, selection.focus]);
  const [palette, setPalette] = useState<GridPalette | null>(null);
  const [paletteFailed, setPaletteFailed] = useState(false);
  const dragRef = useRef<
    | { kind: "select" }
    | { kind: "resize"; column: number; startX: number; startWidth: number }
    | { kind: "reorder"; column: number; startX: number; moved: boolean }
    | null
  >(null);
  const [dropIndex, setDropIndex] = useState<number | null>(null);

  // Order is applied before layout so freezing and hit-testing both see the
  // columns in the order the user actually sees them.
  const visible = useMemo(
    () => orderColumns(columns, columnState.order),
    [columns, columnState.order]
  );

  const gridColumns: LayoutColumn[] = useMemo(
    () =>
      visible.map((column, index) => ({
        name: column.name,
        width: widths[column.name] ?? DEFAULT_COLUMN_WIDTH,
        frozen: index < columnState.frozenCount,
      })),
    [visible, widths, columnState.frozenCount]
  );

  /* Profiles are computed from the loaded rows and say so. Profiling the whole
     table means a round trip; profiling what is on screen is instant and
     usually enough to spot a column that is 40% null. */
  const profiles = useMemo(() => {
    // Capped at PROFILE_SAMPLE rows. Profiling the whole dataset for every
    // column is O(rows x columns) on every render -- at a million rows and 20
    // columns that is twenty million reads, and the header bar is not worth
    // that. `complete` records whether the sample was the whole thing, so the
    // popover can say "first 1,000 rows" rather than implying it saw them all.
    const sampled = rows.length > PROFILE_SAMPLE ? rows.slice(0, PROFILE_SAMPLE) : rows;
    const complete = sampled.length === rows.length;
    const result = new Map<string, ColumnProfile>();
    for (const column of visible) {
      result.set(
        column.name,
        profileColumn(
          column.name,
          sampled.map((row) => row[column.name]),
          { complete }
        )
      );
    }
    return result;
  }, [visible, rows]);
  const layout = useMemo(() => layoutColumns(gridColumns), [gridColumns]);
  const bounds = useMemo(
    () => ({ rows: rows.length, columns: visible.length }),
    [rows.length, visible.length]
  );

  const valueAt = useCallback(
    (address: CellAddress): unknown => {
      const row = rows[address.row];
      const column = visible[address.column];
      if (row === undefined || column === undefined) return undefined;
      return row[column.name];
    },
    [rows, visible]
  );

  const hasValue = useCallback(
    (address: CellAddress) => {
      const value = valueAt(address);
      return value !== null && value !== undefined && value !== "";
    },
    [valueAt]
  );

  /* The palette is read from the live CSS custom properties rather than
     hardcoded, so the canvas follows light/dark like everything else. It is
     re-read whenever the theme attribute changes. */
  useLayoutEffect(() => {
    const element = scrollEl;
    if (!element) return;
    const refresh = () => {
      const resolved = readPalette(element);
      setPalette(resolved);
      setPaletteFailed(resolved === null);
    };
    refresh();

    const observer = new MutationObserver(refresh);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme", "data-density"],
    });
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    media?.addEventListener("change", refresh);
    return () => {
      observer.disconnect();
      media?.removeEventListener("change", refresh);
    };
  }, [scrollEl]);

  useLayoutEffect(() => {
    const element = scrollEl;
    if (!element) return;
    const measure = () =>
      setViewport((current) => ({
        ...current,
        width: element.clientWidth,
        height: element.clientHeight - HEADER_HEIGHT,
      }));
    measure();
    // Guarded: an environment without ResizeObserver should lose auto-resizing,
    // not the whole page. A throw inside a layout effect unmounts everything
    // above it.
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [scrollEl]);

  /* -- drawing ---------------------------------------------------------- */

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !palette || viewport.width === 0) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    // Draw at device resolution or the text is blurry on any retina display.
    const ratio = window.devicePixelRatio || 1;
    const width = viewport.width;
    const height = viewport.height + HEADER_HEIGHT;
    if (canvas.width !== width * ratio || canvas.height !== height * ratio) {
      canvas.width = width * ratio;
      canvas.height = height * ratio;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
    }
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);

    context.fillStyle = palette.surface;
    context.fillRect(0, 0, width, height);

    const rowWindow = visibleRows(viewport, rowHeight, rows.length);
    const columnWindow = visibleColumns(layout, viewport);
    const drawable = [...columnWindow.frozen, ...columnWindow.scrolling];
    const bodyTop = HEADER_HEIGHT;

    context.save();
    context.beginPath();
    context.rect(0, bodyTop, width, height - bodyTop);
    context.clip();
    context.font = FONT;
    context.textBaseline = "middle";

    for (let row = rowWindow.start; row < rowWindow.end; row += 1) {
      const y = bodyTop + row * rowHeight - viewport.scrollTop;
      if (y > height || y + rowHeight < bodyTop) continue;

      // Banded rows: a 200-column table without them is unreadable.
      if (row % 2 === 1) {
        context.fillStyle = palette.surfaceAlt;
        context.fillRect(0, y, width, rowHeight);
      }

      // A staged row is tinted across its full width, so the state is visible
      // even when the changed column is scrolled out of view.
      const state = rowStates?.[row];
      if (state) {
        context.fillStyle =
          state === "deleted"
            ? palette.deletedFill
            : state === "new"
              ? palette.newFill
              : palette.editedFill;
        context.fillRect(0, y, width, rowHeight);
      }

      for (const column of drawable) {
        const rect = cellRect(layout, viewport, rowHeight, { row, column });
        const x = rect.x + ROW_HEADER_WIDTH;
        if (x > width || x + rect.width < ROW_HEADER_WIDTH) continue;

        const selected = isSelected(selection, { row, column });
        if (selected) {
          context.fillStyle = palette.selectionFill;
          context.fillRect(x, y, rect.width, rowHeight);
        }

        const style = formatCell(valueAt({ row, column }));
        context.fillStyle = style.muted ? palette.inkMuted : palette.ink;
        const padding = 9;
        const available = rect.width - padding * 2;
        const text = fitText(context, style.text, available);
        // Alignment follows the column's declared type, not each value's: a
        // numeric column containing one null would otherwise jump between
        // alignments row by row.
        const right = isNumericType(visible[column]?.type) || style.align === "right";
        context.textAlign = right ? "right" : "left";
        context.fillText(
          text,
          right ? x + rect.width - padding : x + padding,
          y + rowHeight / 2
        );

        context.strokeStyle = palette.line;
        context.lineWidth = 1;
        context.beginPath();
        context.moveTo(x + rect.width - 0.5, y);
        context.lineTo(x + rect.width - 0.5, y + rowHeight);
        context.stroke();
      }

      context.strokeStyle = palette.line;
      context.beginPath();
      context.moveTo(0, y + rowHeight - 0.5);
      context.lineTo(width, y + rowHeight - 0.5);
      context.stroke();

      // Row number gutter, drawn last so cells cannot overlap it.
      context.fillStyle = palette.header;
      context.fillRect(0, y, ROW_HEADER_WIDTH, rowHeight);
      context.fillStyle = palette.inkMuted;
      context.textAlign = "right";
      context.font = HEADER_FONT;
      context.fillText(String(row + 1), ROW_HEADER_WIDTH - 9, y + rowHeight / 2);
      context.font = FONT;
    }
    context.restore();

    // Header, drawn over the body so rows scroll beneath it.
    context.fillStyle = palette.header;
    context.fillRect(0, 0, width, HEADER_HEIGHT);
    context.font = HEADER_FONT;
    context.textBaseline = "middle";
    context.textAlign = "left";

    for (const column of drawable) {
      const rect = cellRect(layout, viewport, rowHeight, { row: 0, column });
      const x = rect.x + ROW_HEADER_WIDTH;
      if (x > width || x + rect.width < ROW_HEADER_WIDTH) continue;
      const name = visible[column]?.name ?? "";
      const midLabel = HEADER_LABEL_HEIGHT / 2;

      // Right-hand furniture first, so the label knows how much room is left.
      let reserved = 9;
      const sorted = sort && sort.column === name ? sort.direction : null;
      if (sorted) {
        context.fillStyle = palette.accent;
        context.textAlign = "right";
        context.fillText(sorted === "asc" ? "\u2191" : "\u2193", x + rect.width - reserved, midLabel);
        reserved += 12;
      }
      const glyph = typeGlyph(visible[column]?.type);
      if (glyph) {
        context.fillStyle = palette.inkMuted;
        context.textAlign = "right";
        context.fillText(glyph, x + rect.width - reserved, midLabel);
        reserved += context.measureText(glyph).width + 8;
      }

      context.textAlign = "left";
      context.fillStyle = sorted ? palette.accent : palette.ink;
      context.fillText(
        fitText(context, name, rect.width - 9 - reserved),
        x + 9,
        midLabel
      );

      /* The quality bar. A column that is 40% null should say so where somebody
         is already looking, rather than on a profiling page nobody opens. */
      const bands = qualityBands(profiles.get(name) ?? profileColumn(name, []));
      let barX = x;
      const barY = HEADER_LABEL_HEIGHT;
      for (const band of bands) {
        const bandWidth = band.share * rect.width;
        context.fillStyle =
          band.kind === "value" ? palette.accent
          : band.kind === "empty" ? palette.lineStrong
          : palette.danger;
        context.fillRect(barX, barY, Math.max(0, bandWidth), QUALITY_BAR_HEIGHT);
        barX += bandWidth;
      }

      context.strokeStyle = palette.lineStrong;
      context.beginPath();
      context.moveTo(x + rect.width - 0.5, 0);
      context.lineTo(x + rect.width - 0.5, HEADER_HEIGHT);
      context.stroke();
    }

    context.fillStyle = palette.header;
    context.fillRect(0, 0, ROW_HEADER_WIDTH, HEADER_HEIGHT);
    context.strokeStyle = palette.lineStrong;
    context.beginPath();
    context.moveTo(0, HEADER_HEIGHT - 0.5);
    context.lineTo(width, HEADER_HEIGHT - 0.5);
    context.moveTo(ROW_HEADER_WIDTH - 0.5, 0);
    context.lineTo(ROW_HEADER_WIDTH - 0.5, height);
    context.stroke();
  }, [palette, viewport, layout, rows, visible, rowHeight, selection, valueAt, sort, profiles, rowStates]);

  /* -- interaction ------------------------------------------------------ */

  const moveTo = useCallback(
    (address: CellAddress, extend: boolean) => {
      const target = clamp(address, bounds);
      setSelection((current) => (extend ? extendTo(current, target) : selectCell(target)));
      const element = scrollRef.current;
      if (!element) return;
      const next = scrollToShow(layout, viewport, rowHeight, target);
      element.scrollLeft = next.scrollLeft;
      element.scrollTop = next.scrollTop;
    },
    [bounds, layout, viewport, rowHeight]
  );

  const pointFor = (event: React.PointerEvent | React.MouseEvent) => {
    const element = scrollRef.current;
    if (!element) return null;
    const box = element.getBoundingClientRect();
    return {
      x: event.clientX - box.left - ROW_HEADER_WIDTH,
      y: event.clientY - box.top - HEADER_HEIGHT,
    };
  };

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    const point = pointFor(event);
    if (!point) return;

    // A drag within a few pixels of a header edge resizes that column.
    const box = scrollRef.current?.getBoundingClientRect();
    if (!box) return;
    if (event.clientY - box.top < HEADER_HEIGHT) {
      const edge = columnEdgeNear(point.x);
      if (edge !== null) {
        dragRef.current = {
          kind: "resize",
          column: edge,
          startX: event.clientX,
          startWidth: layout.widths[edge],
        };
        (event.target as Element).setPointerCapture?.(event.pointerId);
        return;
      }
      const column = cellAtPoint(layout, viewport, rowHeight, 1, { x: point.x, y: 0 })?.column;
      if (column === undefined) return;
      const name = visible[column]?.name;
      if (!name) return;

      // Alt-click freezes up to this column; plain click sorts; Ctrl/Cmd-click
      // selects it. Three gestures on one target, but each is the one people
      // already reach for.
      if (event.altKey) {
        setColumnState((current) => ({
          ...current,
          frozenCount: toggleFreeze(current.frozenCount, column),
        }));
        return;
      }
      if (event.ctrlKey || event.metaKey) {
        setSelection(selectColumn(column, bounds));
        return;
      }
      // The quality bar is the strip that makes people curious; clicking it
      // answers the question rather than sorting.
      if (event.clientY - box.top >= HEADER_LABEL_HEIGHT) {
        setOpenProfile((current) => (current === name ? null : name));
        return;
      }
      // Might be a click to sort, or the start of a drag to reorder. Which one
      // is decided by whether the pointer travels.
      dragRef.current = { kind: "reorder", column, startX: event.clientX, moved: false };
      (event.target as Element).setPointerCapture?.(event.pointerId);
      return;
    }

    // A negative x means the pointer is in the row-number gutter, which selects
    // the whole row -- the same gesture every spreadsheet uses.
    if (point.x < 0) {
      const row = Math.floor((point.y + viewport.scrollTop) / rowHeight);
      if (row >= 0 && row < rows.length) {
        setEditing(null);
        setSelection(selectRow(row, bounds));
      }
      return;
    }

    const address = cellAtPoint(layout, viewport, rowHeight, rows.length, point);
    if (!address) return;
    setEditing(null);
    const extend = event.shiftKey;
    setSelection((current) => (extend ? extendTo(current, address) : selectCell(address)));
    dragRef.current = { kind: "select" };
    (event.target as Element).setPointerCapture?.(event.pointerId);
  };

  const columnEdgeNear = (x: number): number | null => {
    const tolerance = 4;
    for (let index = 0; index < layout.widths.length; index += 1) {
      const right = layout.offsets[index] + layout.widths[index] - viewport.scrollLeft;
      if (Math.abs(x - right) <= tolerance) return index;
    }
    return null;
  };

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    if (drag.kind === "reorder") {
      if (Math.abs(event.clientX - drag.startX) > 4) {
        drag.moved = true;
        const point = pointFor(event);
        const target = point
          ? cellAtPoint(layout, viewport, rowHeight, 1, { x: point.x, y: 0 })?.column
          : undefined;
        setDropIndex(target ?? null);
      }
      return;
    }
    if (drag.kind === "resize") {
      const name = visible[drag.column]?.name;
      if (name) {
        const width = resizedWidth(drag.startWidth, event.clientX - drag.startX);
        setWidths((current) => ({ ...current, [name]: width }));
      }
      return;
    }
    const point = pointFor(event);
    if (!point) return;
    const address = cellAtPoint(layout, viewport, rowHeight, rows.length, point);
    if (address) setSelection((current) => extendTo(current, address));
  };

  const endDrag = () => {
    const drag = dragRef.current;
    if (drag?.kind === "reorder") {
      const name = visible[drag.column]?.name;
      if (drag.moved && dropIndex !== null && name) {
        setColumnState((current) => ({
          ...current,
          order: moveColumn(current.order, visible.map((c) => c.name), name, dropIndex),
        }));
      } else if (!drag.moved && name) {
        // It never travelled, so it was a click: sort.
        if (onSortChange) onSortChange(cycleSort(sort, name));
        else setSelection(selectColumn(drag.column, bounds));
      }
    }
    setDropIndex(null);
    dragRef.current = null;
  };

  const beginEdit = useCallback(() => {
    if (!onEditCell) return;
    const value = formatCell(valueAt(selection.focus)).text;
    setEditing({ address: selection.focus, value: value === "null" ? "" : value });
  }, [onEditCell, valueAt, selection.focus]);

  const onContextMenu = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!onColumnMenu) return;
    const point = pointFor(event);
    const box = scrollRef.current?.getBoundingClientRect();
    if (!point || !box || event.clientY - box.top >= HEADER_HEIGHT) return;
    const index = cellAtPoint(layout, viewport, rowHeight, 1, { x: point.x, y: 0 })?.column;
    if (index === undefined) return;
    const name = visible[index]?.name;
    if (!name) return;
    event.preventDefault();
    // Read the coordinates before the handler runs: React nullifies the
    // synthetic event, and a menu positioned from a nullified event lands at 0,0.
    onColumnMenu(name, { x: event.clientX, y: event.clientY });
  };

  const onDoubleClick = (event: React.MouseEvent<HTMLDivElement>) => {
    const point = pointFor(event);
    const box = scrollRef.current?.getBoundingClientRect();
    if (point && box && event.clientY - box.top < HEADER_HEIGHT) {
      const edge = columnEdgeNear(point.x);
      if (edge !== null) {
        const name = visible[edge]?.name;
        if (name) {
          const context = canvasRef.current?.getContext("2d");
          if (context) {
            context.font = FONT;
            // Measured from the loaded rows, not the whole table: autofitting
            // ten million rows would freeze the tab.
            const sample = rows.slice(0, 200).map((row) => formatCell(row[name]).text);
            const width = autofitWidth(name, sample, (text) => context.measureText(text).width);
            setWidths((current) => ({ ...current, [name]: width }));
          }
        }
        return;
      }
      return;
    }
    beginEdit();
  };

  const commitEdit = (value: string) => {
    if (editing && onEditCell) onEditCell(editing.address, value);
    setEditing(null);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (editing) return;
    const meta = event.ctrlKey || event.metaKey;
    const { focus } = selection;

    const arrows: Record<string, Direction> = {
      ArrowUp: "up",
      ArrowDown: "down",
      ArrowLeft: "left",
      ArrowRight: "right",
    };

    if (event.key in arrows) {
      event.preventDefault();
      const direction = arrows[event.key];
      const target = meta ? jump(focus, direction, bounds, hasValue) : step(focus, direction, bounds);
      moveTo(target, event.shiftKey);
      return;
    }

    if (event.key === "Tab") {
      event.preventDefault();
      moveTo(tabTarget(selection, event.shiftKey, bounds), false);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      if (onEditCell) beginEdit();
      else moveTo(step(focus, "down", bounds), false);
      return;
    }
    if (event.key === "PageDown" || event.key === "PageUp") {
      event.preventDefault();
      const perPage = Math.max(1, Math.floor(viewport.height / rowHeight) - 1);
      moveTo(page(focus, event.key === "PageDown" ? "down" : "up", perPage, bounds), event.shiftKey);
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      moveTo({ row: meta ? 0 : focus.row, column: 0 }, event.shiftKey);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      moveTo(
        { row: meta ? bounds.rows - 1 : focus.row, column: bounds.columns - 1 },
        event.shiftKey
      );
      return;
    }
    if (meta && event.key.toLowerCase() === "a") {
      event.preventDefault();
      setSelection(selectAll(bounds));
      return;
    }
    if (meta && event.key.toLowerCase() === "c") {
      event.preventDefault();
      copySelection();
      return;
    }
    if (onEditCell && event.key.length === 1 && !meta) {
      // Typing over a cell replaces it, as in every spreadsheet.
      setEditing({ address: focus, value: event.key });
    }
  };

  const copySelection = useCallback(() => {
    const range = selection.ranges.at(-1);
    if (!range) return;
    const block: unknown[][] = [];
    for (let row = range.top; row <= range.bottom; row += 1) {
      const line: unknown[] = [];
      for (let column = range.left; column <= range.right; column += 1) {
        line.push(valueAt({ row, column }));
      }
      block.push(line);
    }
    void navigator.clipboard?.writeText(toTsv(block)).catch(() => undefined);
  }, [selection, valueAt]);

  const onPaste = (event: React.ClipboardEvent<HTMLDivElement>) => {
    if (!onEditCell) return;
    const text = event.clipboardData.getData("text/plain");
    if (!text) return;
    event.preventDefault();
    const block = squareOff(fromTsv(text));
    const origin = selection.focus;
    const active = selection.ranges.at(-1);
    const target = active
      ? { rows: active.bottom - active.top + 1, columns: active.right - active.left + 1 }
      : { rows: block.length, columns: block[0]?.length ?? 0 };
    // Copying one cell and selecting a column fills the column, as in every
    // spreadsheet; anything that does not divide evenly pastes once.
    for (const write of pasteWrites(block, origin, target, bounds)) {
      onEditCell({ row: write.row, column: write.column }, write.value);
    }
  };

  const size = contentSize(layout, rowHeight, rows.length);
  const editorRect = editing ? cellRect(layout, viewport, rowHeight, editing.address) : null;
  const selectedCount = selectionSize(selection);

  if (paletteFailed) {
    // Loud rather than a plausible-looking grid in the wrong theme.
    return (
      <div className={cx("flex h-full items-center justify-center p-6 text-center text-[13px] text-danger", className)}>
        The grid could not read the design tokens, so it has not drawn anything rather
        than guess at the colours. This is a stylesheet problem, not a data one.
      </div>
    );
  }

  if (columns.length === 0) {
    return (
      <div className={cx("flex h-full items-center justify-center text-[13px] text-muted", className)}>
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className={cx("relative flex h-full flex-col", className)}>
      <div
        ref={attachScroll}
        tabIndex={0}
        role="grid"
        aria-rowcount={rows.length}
        aria-colcount={columns.length}
        aria-label="Data grid"
        onScroll={(event) => {
          // Read the offsets BEFORE calling setState. A state updater runs
          // later -- during React's reducer phase -- and by then the synthetic
          // event has been nullified, so `event.currentTarget` is null and the
          // whole grid unmounts mid-scroll. It only shows up when React defers
          // the update, which is why a wide table triggered it and a narrow one
          // did not.
          const { scrollLeft, scrollTop } = event.currentTarget;
          setViewport((current) => ({ ...current, scrollLeft, scrollTop }));
        }}
        onPointerDown={onPointerDown}
        onContextMenu={onContextMenu}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onDoubleClick={onDoubleClick}
        onKeyDown={onKeyDown}
        onPaste={onPaste}
        className="relative flex-1 overflow-auto outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--accent-soft)]"
      >
        {/* Spacer: gives the scrollbars something to measure. The canvas is
            pinned to the viewport and redrawn as this scrolls beneath it. */}
        <div
          style={{ width: size.width + ROW_HEADER_WIDTH, height: size.height + HEADER_HEIGHT }}
          aria-hidden
        />
        <canvas
          ref={canvasRef}
          className="pointer-events-none sticky left-0 top-0"
          style={{ marginTop: -(size.height + HEADER_HEIGHT) }}
          aria-hidden
        />
        {editing && editorRect ? (
          <input
            autoFocus
            value={editing.value}
            onChange={(event) => setEditing({ ...editing, value: event.target.value })}
            onBlur={(event) => commitEdit(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                commitEdit(editing.value);
                moveTo(step(editing.address, "down", bounds), false);
              }
              if (event.key === "Escape") {
                event.preventDefault();
                setEditing(null);
              }
              event.stopPropagation();
            }}
            className="absolute z-10 border-2 border-[color:var(--accent)] bg-surface px-2 text-[13px] text-ink outline-none"
            style={{
              left: editorRect.x + ROW_HEADER_WIDTH,
              top: editorRect.y + HEADER_HEIGHT,
              width: editorRect.width,
              height: rowHeight,
            }}
          />
        ) : null}
      </div>

      {openProfile ? (
        <ColumnProfileCard
          profile={profiles.get(openProfile) ?? profileColumn(openProfile, [])}
          onClose={() => setOpenProfile(null)}
        />
      ) : null}

      <div className="flex shrink-0 items-center gap-4 border-t border-line bg-surface px-3 py-1.5 text-[11px] text-muted">
        <span className="tabular">{rows.length.toLocaleString()} rows</span>
        <span className="tabular">{columns.length} columns</span>
        {selectedCount > 1 ? <span className="tabular">{selectedCount.toLocaleString()} selected</span> : null}
        {stale ? (
          <span className="rounded bg-warning-soft px-1.5 py-0.5 text-warning">
            Showing the last result that ran
          </span>
        ) : null}
        <span className="ml-auto tabular">
          R{selection.focus.row + 1} · C{selection.focus.column + 1}
        </span>
      </div>
    </div>
  );
}

/**
 * What a column contains, shown where somebody is already looking.
 *
 * Anchored to the grid rather than to the header cell: a popover pinned to a
 * column that can be scrolled away leaves an orphan floating over the data.
 */
function ColumnProfileCard({
  profile,
  onClose,
}: {
  profile: ColumnProfile;
  onClose: () => void;
}) {
  const percent = (count: number) =>
    profile.rowsProfiled === 0 ? "0%" : `${Math.round((count / profile.rowsProfiled) * 100)}%`;

  return (
    <div className="absolute bottom-10 right-3 z-20 w-72 rounded-xl border border-line bg-surface p-3 shadow-[var(--shadow-lg)]">
      <div className="mb-2 flex items-baseline gap-2">
        <span className="truncate text-[13px] font-semibold text-ink">{profile.column}</span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close column profile"
          className="ml-auto rounded px-1.5 text-[11px] text-muted transition hover:bg-surface-2 hover:text-ink"
        >
          Close
        </button>
      </div>

      <p className="mb-2.5 text-[11px] text-muted">{describeProfile(profile)}</p>

      <dl className="mb-2.5 grid grid-cols-2 gap-x-3 gap-y-1 text-[12px]">
        <dt className="text-ink-3">Values</dt>
        <dd className="tabular text-right text-ink">{profile.values.toLocaleString()}</dd>
        <dt className="text-ink-3">Empty</dt>
        <dd className="tabular text-right text-ink">{percent(profile.empties)}</dd>
        <dt className="text-ink-3">Null</dt>
        <dd className="tabular text-right text-ink">{percent(profile.nulls)}</dd>
        <dt className="text-ink-3">Distinct</dt>
        <dd className="tabular text-right text-ink">{profile.distinct.toLocaleString()}</dd>
        {profile.numeric ? (
          <>
            <dt className="text-ink-3">Min</dt>
            <dd className="tabular text-right text-ink">{profile.numeric.min}</dd>
            <dt className="text-ink-3">Max</dt>
            <dd className="tabular text-right text-ink">{profile.numeric.max}</dd>
            <dt className="text-ink-3">Mean</dt>
            <dd className="tabular text-right text-ink">
              {Number(profile.numeric.mean.toFixed(4))}
            </dd>
            <dt className="text-ink-3">Median</dt>
            <dd className="tabular text-right text-ink">{profile.numeric.median}</dd>
          </>
        ) : (
          <>
            <dt className="text-ink-3">Shortest</dt>
            <dd className="tabular text-right text-ink">{profile.shortest}</dd>
            <dt className="text-ink-3">Longest</dt>
            <dd className="tabular text-right text-ink">{profile.longest}</dd>
          </>
        )}
      </dl>

      {profile.top.length > 0 ? (
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-[0.14em] text-muted">
            Most common
          </div>
          <ul className="grid gap-1">
            {profile.top.slice(0, 5).map((entry) => (
              <li key={entry.value} className="flex items-center gap-2 text-[12px]">
                <span className="min-w-0 flex-1 truncate text-ink" title={entry.value}>
                  {entry.value === "" ? "(empty)" : entry.value}
                </span>
                {/* A bar as well as a number: the shape is the point. */}
                <span
                  aria-hidden
                  className="h-1.5 rounded-full bg-[color:var(--accent)]"
                  style={{ width: `${Math.max(4, entry.share * 56)}px` }}
                />
                <span className="tabular w-9 text-right text-muted">
                  {Math.round(entry.share * 100)}%
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

