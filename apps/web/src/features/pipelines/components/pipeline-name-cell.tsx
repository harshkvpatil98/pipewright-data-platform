"use client";

import Link from "next/link";
import { useState } from "react";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { recipeHref } from "@/lib/navigation";
import { Icon, useToast } from "@platform/shared-ui";

type PipelineNameCellProps = {
  projectId: string;
  pipelineId: string;
  name: string;
};

/**
 * A recipe's name, editable in place.
 *
 * Auto-named recipes pile up as look-alikes; this fixes the ones already saved
 * without opening each in the Studio. It stays a link until you choose to
 * rename.
 */
export function PipelineNameCell({ projectId, pipelineId, name }: PipelineNameCellProps) {
  const toast = useToast();
  const [current, setCurrent] = useState(name);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    const next = draft.trim();
    if (next.length < 2 || next === current) {
      setEditing(false);
      setDraft(current);
      return;
    }
    setBusy(true);
    try {
      await apiFetch(`/projects/${projectId}/pipelines/${pipelineId}`, {
        method: "PATCH",
        body: JSON.stringify({ name: next }),
      });
      setCurrent(next);
      setEditing(false);
      toast.success("Pipeline renamed", `Now “${next}”.`);
    } catch (caught) {
      toast.error("Could not rename", extractErrorMessage(caught));
      setDraft(current);
    } finally {
      setBusy(false);
    }
  };

  if (editing) {
    return (
      <span className="flex items-center gap-1.5">
        <input
          value={draft}
          autoFocus
          disabled={busy}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void save();
            if (e.key === "Escape") {
              setEditing(false);
              setDraft(current);
            }
          }}
          className="h-7 w-56 rounded-lg border border-line bg-sunken px-2 text-[13px] text-ink outline-none focus:border-accent"
          aria-label="Pipeline name"
        />
        <button
          type="button"
          onClick={() => void save()}
          disabled={busy}
          className="rounded-md p-1 text-muted transition hover:text-success"
          aria-label="Save name"
        >
          <Icon name="check" size={13} />
        </button>
      </span>
    );
  }

  return (
    <span className="group/name flex items-center gap-1.5">
      <Link
        href={recipeHref(projectId, pipelineId)}
        className="font-medium text-ink hover:text-accent"
      >
        {current}
      </Link>
      <button
        type="button"
        onClick={() => {
          setDraft(current);
          setEditing(true);
        }}
        className="rounded-md p-1 text-muted opacity-0 transition hover:text-ink group-hover/name:opacity-100"
        aria-label={`Rename ${current}`}
      >
        <Icon name="settings" size={12} />
      </button>
    </span>
  );
}
