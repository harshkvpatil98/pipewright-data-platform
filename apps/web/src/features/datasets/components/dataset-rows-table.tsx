"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { CellAnchor, Comment, CommentListResponse } from "@platform/shared-types";
import {
  Badge,
  Button,
  FormField,
  Modal,
  SectionPanel,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@platform/shared-ui";

import { Composer, MentionedBody } from "@/features/team/components/discussion-panel";
import { anchorFor, anchorMatches, anchorWords } from "@/features/team/thread-words";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { countOf, formatDateTime } from "@/lib/format";
import { cx } from "@/lib/utils";

type Cell = { column: string; index: number };

/**
 * A dataset's first rows, with threads on its cells (C2): a cell someone
 * has commented on is marked, clicking any cell opens its threads, and
 * "Comment on a cell" lets someone choose the cell from the keyboard.
 */
export function DatasetRowsTable({
  projectId,
  datasetId,
  columns,
  rows,
  identifier,
  version,
  description,
  currentUsername,
  refreshKey,
  onChanged,
}: {
  projectId: string;
  datasetId: string;
  columns: string[];
  rows: Record<string, unknown>[];
  /** A column whose values name a row across versions, if the dataset has one. */
  identifier: string | null;
  /** The version these rows are from. */
  version: number | null;
  description: string;
  currentUsername: string;
  refreshKey: number;
  onChanged: () => void;
}) {
  const [threads, setThreads] = useState<Comment[]>([]);
  const [open, setOpen] = useState<Cell | null>(null);
  const [choosing, setChoosing] = useState(false);

  const load = useCallback(async () => {
    try {
      const list = await apiFetch<CommentListResponse>(
        `/projects/${projectId}/discussion?target_type=dataset&target_id=${datasetId}`,
      );
      setThreads(list.items.filter((item) => item.anchor !== null));
    } catch {
      /* the rows still show; their threads are under Discussion too */
    }
  }, [projectId, datasetId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const threadsAt = useCallback(
    (cell: Cell) =>
      threads.filter(
        (thread) =>
          thread.anchor &&
          anchorMatches(thread.anchor, { column: cell.column, row: rows[cell.index] ?? {}, index: cell.index, version }),
      ),
    [threads, rows, version],
  );

  const changed = async () => {
    await load();
    onChanged();
  };

  return (
    <SectionPanel
      title="Rows"
      description={description}
      actions={
        <Button size="sm" variant="secondary" onClick={() => setChoosing(true)} disabled={rows.length === 0}>
          Comment on a cell
        </Button>
      }
    >
      <div className="border-line bg-sunken overflow-hidden rounded-[24px] border">
        <Table edge="panel">
          <TableHead>
            <TableRow>
              {columns.map((column) => (
                <TableHeaderCell key={column}>{column}</TableHeaderCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row, index) => (
              <TableRow key={index}>
                {columns.map((column) => {
                  const here = threadsAt({ column, index });
                  const unresolved = here.filter((thread) => thread.resolved_at === null).length;
                  return (
                    <TableCell
                      key={`${index}-${column}`}
                      className={cx("relative cursor-pointer whitespace-nowrap text-ink", here.length > 0 && "pr-7")}
                      onClick={() => setOpen({ column, index })}
                    >
                      {row[column] === null || row[column] === undefined || row[column] === "" ? (
                        <span className="text-muted">—</span>
                      ) : (
                        String(row[column])
                      )}
                      {here.length ? (
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            setOpen({ column, index });
                          }}
                          aria-label={`${countOf(here.length, "thread")} on ${column}, row ${index + 1}`}
                          title={`${countOf(here.length, "thread")} here`}
                          className={cx(
                            "absolute right-1.5 top-1/2 flex h-5 min-w-5 -translate-y-1/2 items-center justify-center rounded-full px-1 text-[12px] font-semibold",
                            unresolved ? "bg-[color:var(--accent)] text-accent-ink" : "bg-surface-2 text-ink-3",
                          )}
                        >
                          {here.length}
                        </button>
                      ) : null}
                    </TableCell>
                  );
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <p className="mt-2 text-[13px] text-ink-3">
        Click a cell to comment on it.{" "}
        {identifier
          ? `Rows are named by ${identifier}, so a thread stays with its row in later versions.`
          : "This dataset has no identifier column, so a thread names its row by number in this version."}
      </p>

      <ChooseCell
        open={choosing}
        onClose={() => setChoosing(false)}
        columns={columns}
        rows={rows}
        identifier={identifier}
        onChoose={(cell) => {
          setChoosing(false);
          setOpen(cell);
        }}
      />
      {open ? (
        <CellThreads
          projectId={projectId}
          datasetId={datasetId}
          anchor={anchorFor({ column: open.column, row: rows[open.index] ?? {}, index: open.index, identifier, version })}
          value={rows[open.index]?.[open.column]}
          threads={threadsAt(open)}
          currentUsername={currentUsername}
          onClose={() => setOpen(null)}
          onChanged={changed}
        />
      ) : null}
    </SectionPanel>
  );
}

function ChooseCell({
  open,
  onClose,
  columns,
  rows,
  identifier,
  onChoose,
}: {
  open: boolean;
  onClose: () => void;
  columns: string[];
  rows: Record<string, unknown>[];
  identifier: string | null;
  onChoose: (cell: Cell) => void;
}) {
  const [column, setColumn] = useState(columns[0] ?? "");
  const [index, setIndex] = useState(0);
  const rowName = (row: Record<string, unknown>, at: number) =>
    identifier && row[identifier] !== null && row[identifier] !== undefined
      ? `${identifier} ${String(row[identifier])}`
      : `Row ${at + 1}`;
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Comment on a cell"
      description="Choose the column and the row."
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button size="sm" onClick={() => onChoose({ column: column || columns[0], index })}>
            Continue
          </Button>
        </div>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Column" htmlFor="cell-column">
          <Select id="cell-column" value={column} onChange={(event) => setColumn(event.target.value)}>
            {columns.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="Row" htmlFor="cell-row">
          <Select id="cell-row" value={String(index)} onChange={(event) => setIndex(Number(event.target.value))}>
            {rows.map((row, at) => (
              <option key={at} value={at}>
                {rowName(row, at)}
              </option>
            ))}
          </Select>
        </FormField>
      </div>
    </Modal>
  );
}

function CellThreads({
  projectId,
  datasetId,
  anchor,
  value,
  threads,
  currentUsername,
  onClose,
  onChanged,
}: {
  projectId: string;
  datasetId: string;
  anchor: CellAnchor;
  value: unknown;
  threads: Comment[];
  currentUsername: string;
  onClose: () => void;
  onChanged: () => Promise<void>;
}) {
  const [replyingTo, setReplyingTo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const shown = useMemo(() => (value === null || value === undefined || value === "" ? "empty" : String(value)), [value]);
  const who = (comment: Comment) => (comment.author_username === currentUsername ? "you" : (comment.author_username ?? "someone"));

  const act = async (comment: Comment, action: "resolve" | "reopen") => {
    setError(null);
    try {
      await apiFetch(`/projects/${projectId}/discussion/${comment.id}/${action}`, { method: "POST" });
      await onChanged();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    }
  };

  return (
    <Modal open onClose={onClose} title={anchorWords(anchor)} description={`The value here is ${shown}.`}>
      <div className="space-y-3">
        {error ? <p className="text-sm text-danger">{error}</p> : null}
        {threads.length === 0 ? <p className="text-sm text-ink-3">No threads on this cell yet.</p> : null}
        {threads.map((thread) => (
          <div key={thread.id} className={cx("rounded-xl border border-line bg-surface px-3.5 py-2.5", thread.resolved_at !== null && "opacity-70")}>
            {[thread, ...thread.replies].map((comment, at) => (
              <div key={comment.id} className={at > 0 ? "mt-2 border-l-2 border-line pl-3" : undefined}>
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-[12.5px] font-medium text-ink">{who(comment)}</span>
                  <span className="text-[12px] text-muted">{formatDateTime(comment.created_at)}</span>
                </div>
                <p className="whitespace-pre-wrap text-[13px] leading-5 text-ink-2">
                  <MentionedBody body={comment.body} />
                </p>
              </div>
            ))}
            <div className="mt-2 flex flex-wrap items-center gap-3">
              {thread.resolved_at ? (
                <>
                  <Badge>Resolved</Badge>
                  <button type="button" className="text-[12px] text-accent hover:underline" onClick={() => void act(thread, "reopen")}>
                    Reopen
                  </button>
                </>
              ) : (
                <button type="button" className="text-[12px] text-accent hover:underline" onClick={() => void act(thread, "resolve")}>
                  Resolve
                </button>
              )}
              {replyingTo !== thread.id ? (
                <button type="button" className="text-[12px] text-ink-3 hover:text-ink" onClick={() => setReplyingTo(thread.id)}>
                  Reply
                </button>
              ) : null}
            </div>
            {replyingTo === thread.id ? (
              <div className="mt-2">
                <Composer
                  projectId={projectId}
                  targetType="dataset"
                  targetId={datasetId}
                  parentId={thread.id}
                  label="Reply"
                  placeholder="Reply, or ask someone with @username…"
                  onPosted={async () => {
                    setReplyingTo(null);
                    await onChanged();
                  }}
                  onCancel={() => setReplyingTo(null)}
                  autoFocus
                />
              </div>
            ) : null}
          </div>
        ))}
        <div>
          <h3 className="mb-1 text-sm font-medium text-ink">Start a thread here</h3>
          <Composer
            projectId={projectId}
            targetType="dataset"
            targetId={datasetId}
            anchor={anchor}
            label="Comment"
            placeholder="Ask about this value, or mention someone with @username…"
            onPosted={onChanged}
          />
        </div>
        <p className="text-[12.5px] text-ink-3">
          {countOf(threads.length, "thread")} on this cell.
        </p>
      </div>
    </Modal>
  );
}
