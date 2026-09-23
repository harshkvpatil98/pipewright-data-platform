"use client";

import { useCallback, useState } from "react";

import type {
  AuthUser,
  ChangeRequest,
  ChangeRequestDetail,
  ChangeRequestListResponse,
  ChangeStatus,
  Comment,
  CommentListResponse,
} from "@platform/shared-types";
import { Button, SectionPanel, Textarea } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { cx } from "@/lib/utils";

type ChangesPageProps = {
  currentUser: AuthUser;
  projectId: string;
  initial: ChangeRequestListResponse;
};

const STATUS_TONE: Record<ChangeStatus, string> = {
  open: "border-info-line bg-info-soft text-info",
  approved: "border-success-line bg-success-soft text-success",
  rejected: "border-danger-line bg-danger-soft text-danger",
  withdrawn: "border-line bg-surface-2 text-ink-3",
};

const KIND_TONE: Record<string, string> = {
  added: "text-success",
  removed: "text-danger",
  changed: "text-warning",
};

export function ChangesPageView({ currentUser, projectId, initial }: ChangesPageProps) {
  const [data, setData] = useState(initial);
  const [open, setOpen] = useState<ChangeRequestDetail | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [commentDraft, setCommentDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadComments = useCallback(
    async (changeId: string) => {
      try {
        const response = await apiFetch<CommentListResponse>(
          `/projects/${projectId}/comments?target_type=change_request&target_id=${changeId}`,
        );
        setComments(response.items);
      } catch {
        setComments([]);
      }
    },
    [projectId],
  );

  const postComment = useCallback(async () => {
    if (!open || !commentDraft.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/projects/${projectId}/comments`, {
        method: "POST",
        body: JSON.stringify({
          target_type: "change_request",
          target_id: open.id,
          body: commentDraft.trim(),
        }),
      });
      setCommentDraft("");
      await loadComments(open.id);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }, [open, commentDraft, projectId, loadComments]);

  const reload = useCallback(async () => {
    setData(await apiFetch<ChangeRequestListResponse>(`/projects/${projectId}/changes`));
  }, [projectId]);

  const inspect = useCallback(
    async (change: ChangeRequest) => {
      setError(null);
      setCommentDraft("");
      try {
        setOpen(
          await apiFetch<ChangeRequestDetail>(`/projects/${projectId}/changes/${change.id}`),
        );
        await loadComments(change.id);
      } catch (caught) {
        setError(extractErrorMessage(caught));
      }
    },
    [projectId, loadComments],
  );

  const review = useCallback(
    async (change: ChangeRequestDetail, action: "approve" | "reject" | "withdraw") => {
      setBusy(true);
      setError(null);
      try {
        const updated = await apiFetch<ChangeRequestDetail>(
          `/projects/${projectId}/changes/${change.id}/${action}`,
          { method: "POST", body: JSON.stringify({}) },
        );
        setOpen(updated);
        await reload();
      } catch (caught) {
        setError(extractErrorMessage(caught));
      } finally {
        setBusy(false);
      }
    },
    [projectId, reload],
  );

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Team"
      title="Changes awaiting review"
      subtitle="In a project that requires approval, edits to workflows and pipelines are proposed here instead of being applied. Running things is never gated — only changing what they are."
    >
      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
        <SectionPanel
          title={`${data.open_count} open`}
          description="Newest first."
        >
          {data.items.length === 0 ? (
            <p className="rounded-xl border border-line px-4 py-8 text-center text-[12.5px] text-muted">
              Nothing proposed yet.
            </p>
          ) : (
            <ul className="space-y-2">
              {data.items.map((change) => (
                <li key={change.id}>
                  <button
                    type="button"
                    onClick={() => void inspect(change)}
                    className={cx(
                      "w-full rounded-xl border px-3 py-2.5 text-left transition",
                      open?.id === change.id
                        ? "border-[color:var(--accent)] bg-[color:var(--accent-faint)]"
                        : "border-line bg-surface hover:border-line-strong",
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-[13px] text-ink">{change.title}</span>
                      <span
                        className={cx(
                          "shrink-0 rounded-full border px-2 py-0.5 text-[10.5px] capitalize",
                          STATUS_TONE[change.status],
                        )}
                      >
                        {change.status}
                      </span>
                    </div>
                    {change.change_summary ? (
                      <p className="mt-1 line-clamp-2 text-[12px] text-ink-3">
                        {change.change_summary}
                      </p>
                    ) : null}
                    <div className="mt-1.5 text-[11px] text-muted">
                      {change.requested_by_username ?? "unknown"} · {formatDate(change.created_at)}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </SectionPanel>

        <SectionPanel
          title={open ? open.title : "Pick a change"}
          description={open?.description ?? "The diff shows exactly what would be applied."}
          actions={
            open && open.status === "open" ? (
              <div className="flex items-center gap-2">
                {open.requested_by_user_id === currentUser.id ? (
                  <Button
                    variant="secondary"
                    disabled={busy}
                    onClick={() => void review(open, "withdraw")}
                  >
                    Withdraw
                  </Button>
                ) : (
                  <>
                    <Button
                      variant="secondary"
                      disabled={busy}
                      onClick={() => void review(open, "reject")}
                    >
                      Reject
                    </Button>
                    <Button disabled={busy} onClick={() => void review(open, "approve")}>
                      Approve
                    </Button>
                  </>
                )}
              </div>
            ) : null
          }
        >
          {!open ? (
            <p className="text-[12.5px] text-muted">
              Choose a proposal on the left to see what it would change.
            </p>
          ) : (
            <>
              {open.requested_by_user_id === currentUser.id && open.status === "open" ? (
                <p className="mb-3 flex items-start gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-[12px] text-ink-3">
                  <Icon name="info" size={12} className="mt-0.5 shrink-0" />
                  You proposed this, so someone else has to approve it. A review with one pair of
                  eyes is not a review.
                </p>
              ) : null}

              <p className="rounded-lg border border-line bg-surface px-3 py-2.5 text-[12.5px] text-ink">
                {open.diff.summary}
              </p>

              <ul className="mt-3 space-y-1.5">
                {open.diff.changes.map((change, index) => (
                  <li
                    key={`${change.path}-${index}`}
                    className="rounded-lg border border-line px-2.5 py-2"
                  >
                    <div className="flex items-baseline gap-2">
                      <span className={cx("text-[10.5px] uppercase", KIND_TONE[change.kind])}>
                        {change.kind}
                      </span>
                      <span className="truncate font-mono text-[11.5px] text-ink-2">
                        {change.path}
                      </span>
                    </div>
                    {change.kind === "changed" ? (
                      <div className="mt-1 font-mono text-[11px]">
                        <span className="text-danger">{JSON.stringify(change.before)}</span>
                        <span className="mx-1.5 text-muted">→</span>
                        <span className="text-success">{JSON.stringify(change.after)}</span>
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>

              {open.diff.truncated ? (
                <p className="mt-2 text-[11px] text-muted">
                  Only the first changes are listed.
                </p>
              ) : null}

              <div className="mt-5 border-t border-line pt-4">
                <h3 className="text-[12px] font-semibold uppercase tracking-[0.14em] text-muted">
                  Review discussion
                </h3>
                {comments.length === 0 ? (
                  <p className="mt-2 text-[12px] text-muted">
                    No comments yet. Ask for changes without rejecting — the proposal stays open.
                  </p>
                ) : (
                  <ul className="mt-2 space-y-2">
                    {comments.map((comment) => (
                      <li key={comment.id} className="rounded-lg border border-line bg-surface px-3 py-2">
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="text-[12px] font-medium text-ink">
                            {comment.author_username ?? "someone"}
                          </span>
                          <span className="text-[10.5px] text-muted">{formatDate(comment.created_at)}</span>
                        </div>
                        <p className="mt-1 whitespace-pre-wrap text-[12.5px] leading-5 text-ink-2">
                          {comment.body}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
                <div className="mt-3 space-y-2">
                  <Textarea
                    value={commentDraft}
                    onChange={(event) => setCommentDraft(event.target.value)}
                    placeholder="Request changes, or leave a note for the author…"
                    rows={2}
                  />
                  <Button
                    variant="secondary"
                    disabled={busy || commentDraft.trim().length === 0}
                    onClick={() => void postComment()}
                  >
                    {open.status === "open" ? "Request changes" : "Comment"}
                  </Button>
                </div>
              </div>

              {open.status !== "open" ? (
                <p className="mt-3 text-[12px] text-muted">
                  {open.status} by {open.reviewed_by_username ?? "unknown"}
                  {open.review_note ? ` — ${open.review_note}` : ""}
                </p>
              ) : null}
            </>
          )}
        </SectionPanel>
      </div>
    </AppShell>
  );
}
