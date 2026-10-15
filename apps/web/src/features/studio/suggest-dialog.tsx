"use client";

import { useState } from "react";

import { Button, FormField, Input, Modal, Textarea } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";

import { compareRecipes, type PlainStep } from "./recipe-diff";

/**
 * Suggesting a change instead of saving it (C2): for someone who may not
 * edit the recipe, or anyone in a project whose changes need approval.
 */
export function SuggestDialog({
  open,
  onClose,
  onSent,
  projectId,
  recipeId,
  saved,
  proposed,
  reason,
}: {
  open: boolean;
  onClose: () => void;
  onSent: () => void;
  projectId: string;
  recipeId: string;
  saved: { name: string; steps: PlainStep[] };
  proposed: { name: string; steps: PlainStep[] };
  /** Why this is a suggestion rather than a save, in a sentence. */
  reason: string;
}) {
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const changes = compareRecipes(saved, proposed);

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/projects/${projectId}/pipelines/${recipeId}/suggest`, {
        method: "POST",
        body: JSON.stringify({
          title: title.trim() || `Changes to ${saved.name}`,
          note: note.trim() || null,
          name: proposed.name.trim() || saved.name,
          steps_json: proposed.steps,
        }),
      });
      setTitle("");
      setNote("");
      onSent();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Suggest these changes"
      description={reason}
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button size="sm" onClick={() => void send()} disabled={busy || changes.length === 0}>
            {busy ? "Sending…" : "Send the suggestion"}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <FormField label="What it is, in a few words" htmlFor="suggest-title">
          <Input
            id="suggest-title"
            value={title}
            maxLength={200}
            onChange={(event) => setTitle(event.target.value)}
            placeholder={`Changes to ${saved.name}`}
          />
        </FormField>
        <FormField label="Why (optional)" htmlFor="suggest-note">
          <Textarea
            id="suggest-note"
            rows={3}
            maxLength={2000}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="The regions are spelled two ways, so the totals split."
          />
        </FormField>
        <div>
          <h3 className="text-sm font-medium text-ink">What it changes</h3>
          {changes.length === 0 ? (
            <p className="mt-1 text-sm text-ink-3">Nothing yet: change a step first.</p>
          ) : (
            <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-ink-2">
              {changes.map((change) => (
                <li key={change.text}>{change.text}</li>
              ))}
            </ul>
          )}
        </div>
        {error ? (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        ) : null}
      </div>
    </Modal>
  );
}
