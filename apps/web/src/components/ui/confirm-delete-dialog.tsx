"use client";

import { useEffect, useState } from "react";

import { Button } from "@platform/shared-ui";
import { Modal } from "@/components/ui/modal";
import { extractErrorMessage } from "@/lib/api/errors";

type ConfirmDeleteDialogProps = {
  open: boolean;
  /** What is being deleted, e.g. "Revenue Quality". Shown, and typed to confirm. */
  name: string;
  /** The kind of thing, lower case: "project", "dataset", "schedule". */
  kind: string;
  /**
   * What else goes when this does. Listed in the dialog so the scale of a
   * cascade is visible *before* the click, not discovered afterwards.
   */
  consequences?: string[];
  /**
   * Require the name to be typed out. For deletes that take other things with
   * them -- a project holding datasets, runs and history -- where a
   * mis-aimed click is expensive and unrecoverable.
   */
  requireTypedName?: boolean;
  confirmLabel?: string;
  onConfirm: () => Promise<unknown>;
  onClose: () => void;
  /** Called after a delete that actually succeeded. */
  onDeleted?: () => void;
};

/**
 * One confirmation dialog for every destructive action in the app.
 *
 * It exists because the API refuses some deletes on purpose -- a user who
 * still owns projects, a notification target a report still delivers to, an
 * organisation that is not empty -- and each refusal carries a sentence saying
 * what to do instead. A component that closed on error, or replaced the
 * message with "Something went wrong", would throw away the only part of the
 * response worth reading. So a failed delete keeps the dialog open and shows
 * what the server said.
 */
export function ConfirmDeleteDialog({
  open,
  name,
  kind,
  consequences,
  requireTypedName = false,
  confirmLabel,
  onConfirm,
  onClose,
  onDeleted,
}: ConfirmDeleteDialogProps) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reopening after a refusal must not show the previous attempt's error, and
  // must not keep a name that was already typed out.
  useEffect(() => {
    if (open) {
      setTyped("");
      setError(null);
      setBusy(false);
    }
  }, [open]);

  const nameMatches = !requireTypedName || typed.trim() === name.trim();

  const confirm = async () => {
    if (!nameMatches || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      onDeleted?.();
      onClose();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={busy ? () => undefined : onClose}
      title={`Delete this ${kind}?`}
      widthClassName="max-w-lg"
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={() => void confirm()}
            disabled={!nameMatches || busy}
          >
            {busy ? "Deleting…" : (confirmLabel ?? `Delete ${kind}`)}
          </Button>
        </div>
      }
    >
      <div className="space-y-4 text-sm text-ink-3">
        <p>
          <span className="font-semibold text-ink">{name}</span> will be deleted. This cannot
          be undone.
        </p>

        {consequences?.length ? (
          <ul className="space-y-1.5 rounded-2xl border border-danger-line bg-sunken px-4 py-3">
            {consequences.map((line) => (
              <li key={line} className="flex gap-2">
                <span aria-hidden className="text-danger">
                  •
                </span>
                <span>{line}</span>
              </li>
            ))}
          </ul>
        ) : null}

        {requireTypedName ? (
          <label className="block space-y-1.5">
            <span className="text-[12px] text-ink-3">
              Type <span className="font-semibold text-ink">{name}</span> to confirm.
            </span>
            <input
              autoFocus
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void confirm();
              }}
              aria-label={`Type ${name} to confirm deletion`}
              className="h-9 w-full rounded-lg border border-line bg-sunken px-3 text-sm text-ink outline-none focus:border-accent"
            />
          </label>
        ) : null}

        {error ? (
          // The server's own sentence. These refusals say what to do instead,
          // so replacing them with a generic message would remove the point.
          <p role="alert" className="rounded-2xl border border-danger-line bg-sunken px-4 py-3 text-danger">
            {error}
          </p>
        ) : null}
      </div>
    </Modal>
  );
}
