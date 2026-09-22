"use client";

import { Button } from "@platform/shared-ui";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/providers/toast-provider";
import type { OneTimeCode } from "@platform/shared-types";

/**
 * Shows a one-time activation or reset code once, for an admin to pass on.
 *
 * In a deployment with email configured the code is emailed and this never
 * appears; here it is handed to the admin, so the copy is explicit that it is
 * shown once and must be delivered to the person by hand.
 */
export function OneTimeCodeModal({
  code,
  onClose,
}: {
  code: OneTimeCode | null;
  onClose: () => void;
}) {
  const toast = useToast();
  if (!code) return null;

  const isActivation = code.purpose === "activation";
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code.code);
      toast.success("Copied", "Send it to the person; it will not be shown again.");
    } catch {
      toast.info("Copy it now", "It will not be shown again.");
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={isActivation ? "Invitation sent" : "Reset code generated"}
      widthClassName="max-w-md"
      footer={
        <div className="flex justify-end">
          <Button size="sm" onClick={onClose}>
            Done
          </Button>
        </div>
      }
    >
      <div className="space-y-3 text-sm text-ink-3">
        <p>
          {isActivation ? (
            <>
              <span className="font-medium text-ink">{code.username}</span> has an account, but
              cannot sign in until they set a password with this code.
            </>
          ) : (
            <>
              Give this reset code to <span className="font-medium text-ink">{code.username}</span>.
              They redeem it on the sign-in screen to set a new password.
            </>
          )}
        </p>
        <div className="flex items-center gap-2">
          <code className="flex-1 overflow-x-auto whitespace-nowrap rounded-lg border border-line bg-sunken px-2.5 py-1.5 font-mono text-[13px] text-ink">
            {code.code}
          </code>
          <Button variant="secondary" size="sm" onClick={() => void copy()}>
            Copy
          </Button>
        </div>
        <p className="text-[12px] text-muted">
          It works once and expires in {code.expires_in_minutes} minutes. It is shown here only
          now — a deployment with email configured would send it automatically.
        </p>
      </div>
    </Modal>
  );
}
