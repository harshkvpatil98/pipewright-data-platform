"use client";

import { useState } from "react";

import { ConfirmDeleteDialog } from "@/components/ui/confirm-delete-dialog";
import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";

type DeleteRowButtonProps = {
  /** Path under the API root, e.g. `/projects/abc/schedules/def`. */
  path: string;
  /** What is being deleted, shown in the dialog. */
  name: string;
  /** The kind of thing, lower case: "schedule", "destination". */
  kind: string;
  consequences?: string[];
  requireTypedName?: boolean;
  onDeleted?: () => void;
  className?: string;
};

/**
 * The trash button and its confirmation, as one thing.
 *
 * Fifteen endpoints in the API could delete something and had no button
 * anywhere in the app. Giving each list page its own dialog would have meant
 * fifteen chances to forget the confirmation, or to swallow the refusal
 * message the API sends back -- so the pair travels together.
 */
export function DeleteRowButton({
  path,
  name,
  kind,
  consequences,
  requireTypedName,
  onDeleted,
  className,
}: DeleteRowButtonProps) {
  const [confirming, setConfirming] = useState(false);

  return (
    <>
      <button
        type="button"
        onClick={() => setConfirming(true)}
        aria-label={`Delete ${name}`}
        className={
          className ??
          "rounded-lg border border-line p-1.5 text-muted transition hover:border-danger-line hover:text-danger"
        }
      >
        <Icon name="trash" size={12} />
      </button>

      <ConfirmDeleteDialog
        open={confirming}
        name={name}
        kind={kind}
        consequences={consequences}
        requireTypedName={requireTypedName}
        onConfirm={() => apiFetch(path, { method: "DELETE" })}
        onDeleted={onDeleted}
        onClose={() => setConfirming(false)}
      />
    </>
  );
}
