"use client";

import { useCallback, useEffect, useState } from "react";

import type { ChangeRequestDetail, ChangeRequestListResponse } from "@platform/shared-types";
import { Button, Input, Modal } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";

import { compareRecipes, type PlainStep } from "./recipe-diff";

const plain = (snapshot: Record<string, unknown> | null) => ({
  name: typeof snapshot?.name === "string" ? snapshot.name : "",
  steps: Array.isArray(snapshot?.steps_json) ? (snapshot.steps_json as PlainStep[]) : [],
});

/**
 * The suggestions waiting on a recipe (C2), for someone who may apply them:
 * what each changes, step by step, and accept or decline with a note.
 */
export function SuggestionsDrawer({
  open,
  onClose,
  onDecided,
  projectId,
  recipeId,
  currentUsername,
}: {
  open: boolean;
  onClose: () => void;
  onDecided: () => void;
  projectId: string;
  recipeId: string;
  currentUsername: string;
}) {
  const [items, setItems] = useState<ChangeRequestDetail[] | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const list = await apiFetch<ChangeRequestListResponse>(`/projects/${projectId}/changes?status=open`);
      const mine = list.items.filter((item) => item.resource_type === "pipeline" && item.resource_id === recipeId);
      setItems(
        await Promise.all(mine.map((item) => apiFetch<ChangeRequestDetail>(`/projects/${projectId}/changes/${item.id}`))),
      );
    } catch (caught) {
      setError(extractErrorMessage(caught));
    }
  }, [projectId, recipeId]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const decide = async (item: ChangeRequestDetail, verdict: "approve" | "reject" | "withdraw") => {
    setBusy(item.id);
    setError(null);
    try {
      await apiFetch(`/projects/${projectId}/changes/${item.id}/${verdict}`, {
        method: "POST",
        body: verdict === "withdraw" ? undefined : JSON.stringify({ note: notes[item.id]?.trim() || null }),
      });
      await load();
      onDecided();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      side="right"
      widthClassName="max-w-xl"
      title="Suggestions"
      description="Changes people suggested for this recipe. Accepting one saves it as the recipe's next version."
    >
      {error ? (
        <p role="alert" className="mb-3 text-sm text-danger">
          {error}
        </p>
      ) : null}
      {items === null ? (
        <p className="text-sm text-ink-3">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-ink-3">No suggestions are waiting for this recipe.</p>
      ) : (
        <ul className="space-y-4">
          {items.map((item) => {
            const own = item.requested_by_username === currentUsername;
            const changes = compareRecipes(plain(item.before_json), plain(item.after_json));
            return (
              <li key={item.id} className="rounded-2xl border border-line bg-surface px-4 py-3">
                <div className="text-[15px] font-medium text-ink">{item.title}</div>
                <div className="mt-0.5 text-[13px] text-ink-3">
                  {item.requested_by_username ?? "Someone"} · {formatDateTime(item.created_at)}
                </div>
                {item.description ? <p className="mt-2 text-sm text-ink-2">{item.description}</p> : null}
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-2">
                  {changes.map((change) => (
                    <li key={change.text}>{change.text}</li>
                  ))}
                </ul>
                {own ? (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <span className="text-[13px] text-ink-3">Yours: someone else accepts or declines it.</span>
                    <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => void decide(item, "withdraw")}>
                      Withdraw it
                    </Button>
                  </div>
                ) : (
                  <div className="mt-3 flex flex-wrap items-end gap-2">
                    <div className="min-w-[12rem] flex-1">
                      <label htmlFor={`note-${item.id}`} className="sr-only">
                        A note for {item.requested_by_username ?? "them"}
                      </label>
                      <Input
                        id={`note-${item.id}`}
                        value={notes[item.id] ?? ""}
                        onChange={(event) => {
                          const value = event.target.value;
                          setNotes((current) => ({ ...current, [item.id]: value }));
                        }}
                        placeholder="A note for them (optional)"
                      />
                    </div>
                    <Button size="sm" disabled={busy !== null} onClick={() => void decide(item, "approve")}>
                      {busy === item.id ? "Saving…" : "Accept"}
                    </Button>
                    <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => void decide(item, "reject")}>
                      Decline
                    </Button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Modal>
  );
}
