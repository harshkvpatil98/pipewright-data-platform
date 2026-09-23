"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { AuthUser, Comment, CommentListResponse, CommentTargetType } from "@platform/shared-types";
import { Button, SectionPanel } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";
import { cx } from "@/lib/utils";

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
};

/**
 * A comment thread on one thing -- a dataset, a pipeline, a dashboard, a
 * change request -- with @mentions that notify the person named.
 *
 * One component for every surface, so the thread on a dashboard and the review
 * discussion on a change request behave the same way and hit the same API
 * (`/discussion`). Mentions autocomplete from the people who have accounts;
 * the server parses them again on save, so the client list is a convenience,
 * not the source of truth.
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
}: DiscussionPanelProps) {
  const [thread, setThread] = useState<CommentListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [showResolved, setShowResolved] = useState(false);
  const [people, setPeople] = useState<string[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

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
  }, [load]);

  // People to complete @mentions against -- fetched once, on the first @.
  const loadPeople = useCallback(async () => {
    if (people.length > 0) return;
    try {
      const response = await apiFetch<{ items: AuthUser[] }>("/auth/users");
      setPeople(response.items.map((user) => user.username));
    } catch {
      // Autocomplete is a convenience; the server parses mentions regardless.
    }
  }, [people.length]);

  // The word being typed after an @, if any, and the matches for it.
  const mentionQuery = useMemo(() => {
    const match = /(?:^|\s)@([a-zA-Z0-9_.-]*)$/.exec(draft);
    return match ? match[1].toLowerCase() : null;
  }, [draft]);
  const suggestions = useMemo(
    () =>
      mentionQuery === null
        ? []
        : people.filter((name) => name.toLowerCase().startsWith(mentionQuery)).slice(0, 6),
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
        body: JSON.stringify({ target_type: targetType, target_id: targetId, body }),
      });
      setDraft("");
      await load();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const resolve = async (comment: Comment) => {
    setError(null);
    try {
      await apiFetch<Comment>(`/projects/${projectId}/discussion/${comment.id}/resolve`, {
        method: "POST",
      });
      await load();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    }
  };

  const items = thread?.items ?? [];
  const visible = showResolved ? items : items.filter((comment) => comment.resolved_at === null);
  const resolvedCount = items.length - items.filter((comment) => comment.resolved_at === null).length;

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
        <p className="text-[12.5px] text-muted">
          {items.length === 0 ? "No comments yet." : "No open comments."}
        </p>
      ) : (
        <ul className="space-y-2">
          {visible.map((comment) => (
            <li
              key={comment.id}
              className={cx(
                "rounded-xl border border-line bg-surface px-3.5 py-2.5",
                comment.resolved_at ? "opacity-70" : null,
              )}
            >
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="text-[12.5px] font-medium text-ink">
                  {comment.author_username === currentUsername
                    ? "you"
                    : (comment.author_username ?? "someone")}
                </span>
                <span className="text-[10.5px] text-muted">{formatDateTime(comment.created_at)}</span>
                {comment.resolved_at ? (
                  <span className="rounded-full border border-line bg-sunken px-1.5 py-0.5 text-[10px] text-muted">
                    resolved
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => void resolve(comment)}
                    className="ml-auto text-[11px] text-accent hover:underline"
                  >
                    Resolve
                  </button>
                )}
              </div>
              <p className="mt-1 whitespace-pre-wrap text-[13px] leading-5 text-ink-2">
                <MentionedBody body={comment.body} />
              </p>
            </li>
          ))}
        </ul>
      )}

      {resolvedCount > 0 ? (
        <button
          type="button"
          onClick={() => setShowResolved((current) => !current)}
          className="text-[11.5px] text-muted hover:text-ink"
        >
          {showResolved ? "Hide" : "Show"} {resolvedCount} resolved
        </button>
      ) : null}

      <div className="relative space-y-2">
        <textarea
          ref={textareaRef}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
              event.preventDefault();
              void post();
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
        <div className="flex items-center justify-between gap-2">
          <span className="text-[10.5px] text-muted">Ctrl/⌘ + Enter to post</span>
          <Button variant="secondary" size="sm" disabled={busy || !draft.trim()} onClick={() => void post()}>
            {busy ? "Posting…" : composerLabel}
          </Button>
        </div>
      </div>
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

/** Highlights @mentions in a comment body without turning it into markup. */
function MentionedBody({ body }: { body: string }) {
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
