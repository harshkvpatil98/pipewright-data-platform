"use client";

import { useState } from "react";

import { Button, FormField, Input } from "@platform/shared-ui";

import { useToast } from "@/components/providers/toast-provider";
import { apiFetch } from "@/lib/api/client";
import { clearAccessToken } from "@/lib/auth/session";
import { extractErrorMessage } from "@/lib/api/errors";
import { assessPassword } from "@/lib/password-strength";

const STRENGTH_TONE = [
  "bg-danger",
  "bg-danger",
  "bg-warning",
  "bg-success",
  "bg-success",
] as const;

/**
 * Change your own password, and end every session at once.
 *
 * A password change requires the current password even though you are signed
 * in — that is what stops a walked-up-to browser being used to lock the real
 * owner out. On success the server has bumped your token version, so this
 * client's own token is now invalid and the right thing to do is return to
 * the login screen.
 */
export function AccountSecurity() {
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const strength = assessPassword(next);
  const mismatch = confirm.length > 0 && confirm !== next;

  const submit = async () => {
    if (next !== confirm) {
      setError("The two new passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/auth/me/password", {
        method: "PATCH",
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      toast.success("Password changed", "Every session has been signed out. Please sign in again.");
      clearAccessToken();
      window.location.href = "/login";
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const signOutEverywhere = async () => {
    setBusy(true);
    try {
      await apiFetch("/auth/me/sign-out-everywhere", { method: "POST" });
      toast.info("Signed out everywhere", "All sessions ended. Please sign in again.");
      clearAccessToken();
      window.location.href = "/login";
    } catch (caught) {
      toast.error("Could not sign out everywhere", extractErrorMessage(caught));
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5 px-4 py-4">
      <div className="grid gap-3 sm:max-w-sm">
        <FormField label="Current password" htmlFor="pw-current">
          <Input
            id="pw-current"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
        </FormField>
        <FormField label="New password" htmlFor="pw-new">
          <Input
            id="pw-new"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
          />
        </FormField>
        {next ? (
          <div className="flex items-center gap-2">
            <div className="flex h-1.5 flex-1 gap-1">
              {[0, 1, 2, 3].map((i) => (
                <div
                  key={i}
                  className={`h-full flex-1 rounded-full ${
                    i < strength.score ? STRENGTH_TONE[strength.score] : "bg-surface-2"
                  }`}
                />
              ))}
            </div>
            <span className="w-16 text-right text-[11px] text-muted">{strength.label}</span>
          </div>
        ) : null}
        <FormField label="Confirm new password" htmlFor="pw-confirm">
          <Input
            id="pw-confirm"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
        </FormField>
        {mismatch ? <p className="text-[12px] text-danger">The passwords do not match.</p> : null}
        {error ? (
          <p role="alert" className="text-[12px] text-danger">
            {error}
          </p>
        ) : null}
        <Button
          onClick={() => void submit()}
          disabled={busy || !current || next.length < 8 || mismatch}
        >
          {busy ? "Saving…" : "Change password"}
        </Button>
      </div>

      <div className="border-t border-line pt-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-[13px] text-ink">Sign out everywhere</div>
            <div className="mt-0.5 text-[11px] text-muted">
              End every session on every device, including this one. Use it if you think a
              session was left open somewhere.
            </div>
          </div>
          <Button variant="secondary" onClick={() => void signOutEverywhere()} disabled={busy}>
            Sign out everywhere
          </Button>
        </div>
      </div>
    </div>
  );
}
