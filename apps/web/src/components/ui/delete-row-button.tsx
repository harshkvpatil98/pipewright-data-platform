"use client";

import { useState } from "react";

import { ConfirmDeleteDialog } from "@/components/ui/confirm-delete-dialog";
import { apiFetch } from "@/lib/api/client";
import { Icon } from "@platform/shared-ui";

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
  /** Words beside the icon, for a page's own delete rather than a row's. */
  label?: string;
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
  label,
}: DeleteRowButtonProps) {
  const [confirming, setConfirming] = useState(false);

  return (
    <>
      <button
        type="button"
        onClick={() => setConfirming(true)}
        aria-label={label ? undefined : `Delete ${name}`}
        className={
          className ??
          (label
            ? "inline-flex items-center gap-2 rounded-xl border border-line px-3 py-2 text-[14px] text-ink-2 transition hover:border-danger-line hover:text-danger"
            : "rounded-lg border border-line p-1.5 text-muted transition hover:border-danger-line hover:text-danger")
        }
      >
        <Icon name="trash" size={label ? 14 : 12} />
        {label}
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
