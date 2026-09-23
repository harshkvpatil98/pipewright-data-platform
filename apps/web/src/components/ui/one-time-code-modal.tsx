"use client";

import { Button } from "@platform/shared-ui";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/providers/toast-provider";
import type { OneTimeCode } from "@platform/shared-types";

/**
 * Shows a one-time activation or reset code once, for an admin to pass on.
 *
 * When the server could email it, this says where it went and shows no code at
 * all -- the admin never sees it, which is the point. Otherwise the code is
 * handed to the admin once, with the reason it could not be emailed when there
 * was an address to send it to.
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
    if (!code.code) return;
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
      title={
        code.emailed
          ? isActivation
            ? "Invitation emailed"
            : "Reset email sent"
          : isActivation
            ? "Invitation created"
            : "Reset code generated"
      }
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
        {code.emailed ? (
          <p>
            {isActivation ? (
              <>
                <span className="font-medium text-ink">{code.username}</span> has an account and an
                email at <span className="font-medium text-ink">{code.emailed_to}</span> with a link to
                set their password. The link works for {code.expires_in_minutes} minutes.
              </>
            ) : (
              <>
                An email with a reset link went to{" "}
                <span className="font-medium text-ink">{code.emailed_to}</span>. It works for{" "}
                {code.expires_in_minutes} minutes; every earlier session is already signed out.
              </>
            )}
          </p>
        ) : (
          <>
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
            {code.email_error ? (
              <p className="rounded-xl border border-warning-line bg-warning-soft px-3 py-2 text-[12px] text-warning">
                It could not be emailed: {code.email_error}
              </p>
            ) : (
              <p className="text-[12px] text-muted">
                This server has no email configured (or the account has no address), so the code is
                shown here once for you to pass on.
              </p>
            )}
            <div className="flex items-center gap-2">
              <code className="flex-1 rounded-xl border border-line bg-sunken px-3 py-2 font-mono text-[15px] tracking-[0.2em] text-ink">
                {code.code}
              </code>
              <Button variant="secondary" size="sm" onClick={() => void copy()}>
                Copy
              </Button>
            </div>
            <p className="text-[12px] text-muted">
              Expires in {code.expires_in_minutes} minutes and works once. It will not be shown again.
            </p>
          </>
        )}
      </div>
    </Modal>
  );
}
