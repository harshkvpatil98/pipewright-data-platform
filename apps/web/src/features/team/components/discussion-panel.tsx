"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { AuthUser, CellAnchor, Comment, CommentListResponse, CommentTargetType } from "@platform/shared-types";
import { Badge, Button, SectionPanel } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";
import { cx } from "@/lib/utils";

import { anchorWords } from "../thread-words";

type DiscussionPanelProps = {
  projectId: string;
  targetType: CommentTargetType;
  targetId: string;
  /** The current user's username, so their own comments read as "you". */
  currentUsername?: string;
  title?: string;
  description?: string;
  /** Label for the post button; "Request changes" on a review, "Comment" elsewhere. */
  composerLabel?: string;
  placeholder?: string;
  /** Render without the surrounding panel, for embedding inside another one. */
  bare?: boolean;
  /** Called after any change, so a page showing threads elsewhere (cells) can catch up. */
  onChanged?: () => void;
  /** A count that, when it changes, makes the panel read the threads again. */
  refreshKey?: number;
  /** On a recipe: the step a new thread is about, and how to talk about the whole recipe again (E1). */
  step?: { id: string; label: string; onClear: () => void } | null;
  /** On a recipe: each step's words by its id, to say which step a thread is about. */
  stepNames?: Record<string, string>;
};

/**
 * Threads on one thing -- a dataset, a recipe, a dashboard, a change request
 * -- with replies, @mentions that notify the person named, and, on a
 * dataset, the cell a thread is about (C2). A thread resolves as a whole;
 * replying to a resolved one opens it again.
 *
 * One component for every surface, so the thread on a dashboard and the
 * review discussion on a change request behave the same way and hit the same
 * API (`/discussion`).
 */
export function DiscussionPanel({
  projectId,
  targetType,
  targetId,
  currentUsername,
  title = "Discussion",
  description = "Notes and questions about this, kept with it. Mention someone with @ and they are notified.",
  composerLabel = "Comment",
  placeholder = "Leave a note, or ask someone with @username…",
  bare = false,
  onChanged,
  refreshKey = 0,
  step = null,
  stepNames,
}: DiscussionPanelProps) {
  const [thread, setThread] = useState<CommentListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showResolved, setShowResolved] = useState(false);
  const [replyingTo, setReplyingTo] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setThread(
        await apiFetch<CommentListResponse>(
          `/projects/${projectId}/discussion?target_type=${targetType}&target_id=${targetId}`,
        ),
      );
      setError(null);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    }
  }, [projectId, targetType, targetId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const changed = async () => {
    await load();
    onChanged?.();
  };

  const act = async (comment: Comment, action: "resolve" | "reopen") => {
    setError(null);
    try {
      await apiFetch<Comment>(`/projects/${projectId}/discussion/${comment.id}/${action}`, { method: "POST" });
      await changed();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    }
  };

  const items = thread?.items ?? [];
  const visible = showResolved ? items : items.filter((comment) => comment.resolved_at === null);
  const resolvedCount = items.length - items.filter((comment) => comment.resolved_at === null).length;
  const who = (comment: Comment) =>
    comment.author_username === currentUsername ? "you" : (comment.author_username ?? "someone");

  const content = (
    <div className="space-y-3">
      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}

      {thread === null && !error ? (
        <p className="text-[12.5px] text-muted">Loading…</p>
      ) : visible.length === 0 ? (
        <p className="text-[12.5px] text-muted">{items.length === 0 ? "No comments yet." : "No open threads."}</p>
      ) : (
        <ul className="space-y-2">
          {visible.map((comment) => (
            <li
              key={comment.id}
              className={cx("rounded-xl border border-line bg-surface px-3.5 py-2.5", comment.resolved_at ? "opacity-70" : null)}
            >
              {comment.anchor ? (
                <div className="mb-1 text-[12px] font-medium text-ink-3">{anchorWords(comment.anchor)}</div>
              ) : comment.step_id ? (
                <div className="mb-1 text-[12px] font-medium text-ink-3">
                  {stepNames?.[comment.step_id] ? `On ${stepNames[comment.step_id]}` : "On a step since removed"}
                </div>
              ) : null}
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="text-[12.5px] font-medium text-ink">{who(comment)}</span>
                <span className="text-[12px] text-muted">{formatDateTime(comment.created_at)}</span>
                {comment.resolved_at ? (
                  <>
                    <Badge>Resolved{comment.resolved_by_username ? ` by ${comment.resolved_by_username}` : ""}</Badge>
                    <button
                      type="button"
                      onClick={() => void act(comment, "reopen")}
                      className="ml-auto text-[12px] text-accent hover:underline"
                    >
                      Reopen
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={() => void act(comment, "resolve")}
                    className="ml-auto text-[12px] text-accent hover:underline"
                  >
                    Resolve
                  </button>
                )}
              </div>
              <p className="mt-1 whitespace-pre-wrap text-[13px] leading-5 text-ink-2">
                <MentionedBody body={comment.body} />
              </p>
              {comment.replies.length ? (
                <ul className="mt-2 space-y-2 border-l-2 border-line pl-3">
                  {comment.replies.map((reply) => (
                    <li key={reply.id}>
                      <div className="flex flex-wrap items-baseline gap-x-2">
                        <span className="text-[12.5px] font-medium text-ink">{who(reply)}</span>
                        <span className="text-[12px] text-muted">{formatDateTime(reply.created_at)}</span>
                      </div>
                      <p className="whitespace-pre-wrap text-[13px] leading-5 text-ink-2">
                        <MentionedBody body={reply.body} />
                      </p>
                    </li>
                  ))}
                </ul>
              ) : null}
              {replyingTo === comment.id ? (
                <div className="mt-2">
                  <Composer
                    projectId={projectId}
                    targetType={targetType}
                    targetId={targetId}
                    parentId={comment.id}
                    label="Reply"
                    placeholder="Reply, or ask someone with @username…"
                    onPosted={async () => {
                      setReplyingTo(null);
                      await changed();
                    }}
                    onCancel={() => setReplyingTo(null)}
                    autoFocus
                  />
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setReplyingTo(comment.id)}
                  className="mt-1.5 text-[12px] text-ink-3 hover:text-ink"
                >
                  Reply
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {resolvedCount > 0 ? (
        <button
          type="button"
          onClick={() => setShowResolved((current) => !current)}
          className="text-[12px] text-muted hover:text-ink"
        >
          {showResolved ? "Hide" : "Show"} {resolvedCount} resolved
        </button>
      ) : null}

      {step ? (
        <p className="flex flex-wrap items-baseline gap-x-2 text-[12.5px] text-ink-2">
          <span>A new thread on {step.label}.</span>
          <button type="button" onClick={step.onClear} className="text-[12px] text-accent hover:underline">
            On the whole recipe instead
          </button>
        </p>
      ) : null}
      <Composer
        projectId={projectId}
        targetType={targetType}
        targetId={targetId}
        stepId={step?.id}
        label={composerLabel}
        placeholder={placeholder}
        onPosted={changed}
        autoFocus={Boolean(step)}
      />
    </div>
  );

  if (bare) return content;
  return (
    <SectionPanel
      title={thread && thread.open_count > 0 ? `${title} (${thread.open_count} open)` : title}
      description={description}
    >
      {content}
    </SectionPanel>
  );
}

/**
 * Writing a comment, a reply, or a new thread on a cell: a text box with
 * @mentions completed from the people who have accounts. The server parses
 * mentions again on save, so the list is a convenience.
 */
export function Composer({
  projectId,
  targetType,
  targetId,
  parentId,
  anchor,
  stepId,
  label,
  placeholder,
  onPosted,
  onCancel,
  autoFocus,
}: {
  projectId: string;
  targetType: CommentTargetType;
  targetId: string;
  parentId?: string;
  anchor?: CellAnchor;
  /** A new thread on one step of a recipe (E1). */
  stepId?: string;
  label: string;
  placeholder: string;
  onPosted: () => void | Promise<void>;
  onCancel?: () => void;
  autoFocus?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [people, setPeople] = useState<string[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (autoFocus) textareaRef.current?.focus();
  }, [autoFocus, stepId]);

  const loadPeople = useCallback(async () => {
    if (people.length > 0) return;
    try {
      const response = await apiFetch<{ items: AuthUser[] }>("/auth/users");
      setPeople(response.items.map((user) => user.username));
    } catch {
      // Autocomplete is a convenience; the server parses mentions regardless.
    }
  }, [people.length]);

  const mentionQuery = useMemo(() => {
    const match = /(?:^|\s)@([a-zA-Z0-9_.-]*)$/.exec(draft);
    return match ? match[1].toLowerCase() : null;
  }, [draft]);
  const suggestions = useMemo(
    () => (mentionQuery === null ? [] : people.filter((name) => name.toLowerCase().startsWith(mentionQuery)).slice(0, 6)),
    [mentionQuery, people],
  );

  useEffect(() => {
    if (mentionQuery !== null) void loadPeople();
  }, [mentionQuery, loadPeople]);

  const completeMention = (username: string) => {
    setDraft((current) => current.replace(/@([a-zA-Z0-9_.-]*)$/, `@${username} `));
    textareaRef.current?.focus();
  };

  const post = async () => {
    const body = draft.trim();
    if (!body) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch<Comment>(`/projects/${projectId}/discussion`, {
        method: "POST",
        body: JSON.stringify({
          target_type: targetType,
          target_id: targetId,
          body,
          parent_id: parentId ?? null,
          anchor: anchor ?? null,
          step_id: stepId ?? null,
        }),
      });
      setDraft("");
      await onPosted();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative space-y-2">
      <label className="sr-only" htmlFor={`composer-${parentId ?? anchor?.column ?? "new"}`}>
        {label}
      </label>
      <textarea
        id={`composer-${parentId ?? anchor?.column ?? "new"}`}
        ref={textareaRef}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
            event.preventDefault();
            void post();
          } else if (event.key === "Escape" && onCancel) {
            onCancel();
          }
        }}
        placeholder={placeholder}
        rows={2}
        className="w-full rounded-lg border border-line bg-sunken px-3 py-2 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)]"
      />
      {suggestions.length > 0 ? (
        <ul
          role="listbox"
          aria-label="People to mention"
          className="absolute left-0 top-full z-10 mt-1 w-56 overflow-hidden rounded-xl border border-line bg-[color:var(--panel-strong)] shadow-[var(--shadow-lg)]"
        >
          {suggestions.map((name) => (
            <li key={name}>
              <button
                type="button"
                role="option"
                aria-selected={false}
                onMouseDown={(event) => {
                  event.preventDefault();
                  completeMention(name);
                }}
                className="block w-full px-3 py-1.5 text-left text-[12.5px] text-ink hover:bg-surface"
              >
                @{name}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {error ? <p className="text-[12.5px] text-danger">{error}</p> : null}
      <div className="flex items-center justify-between gap-2">
        <span className="text-[12px] text-muted">Ctrl/⌘ + Enter to post</span>
        <span className="flex gap-1.5">
          {onCancel ? (
            <Button variant="ghost" size="sm" onClick={onCancel}>
              Cancel
            </Button>
          ) : null}
          <Button variant="secondary" size="sm" disabled={busy || !draft.trim()} onClick={() => void post()}>
            {busy ? "Posting…" : label}
          </Button>
        </span>
      </div>
    </div>
  );
}

/** Highlights @mentions in a comment body without turning it into markup. */
export function MentionedBody({ body }: { body: string }) {
  const parts = body.split(/(@[a-zA-Z0-9_.-]+)/g);
  return (
    <>
      {parts.map((part, index) =>
        part.startsWith("@") ? (
          <span key={index} className="font-medium text-accent">
            {part}
          </span>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  );
}
