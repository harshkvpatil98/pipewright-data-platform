"use client";

import { useEffect, useState } from "react";

import { Button, FormField, Input } from "@platform/shared-ui";
import type {
  MfaEnrollResponse,
  MfaRecoveryCodesResponse,
  MfaStatus,
} from "@platform/shared-types";

import { useToast } from "@/components/providers/toast-provider";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";

/**
 * Turn a second factor on and off.
 *
 * Enrolment is a two-step handshake on purpose: the server hands back a secret
 * (as a QR to scan and text to type by hand), and it only *takes effect* once a
 * live code proves the authenticator was set up — otherwise a mistyped setup
 * would lock the owner out on their next sign-in. Recovery codes are shown once,
 * here, because after this the server keeps only their hashes.
 */
export function MfaPanel() {
  const toast = useToast();
  const [status, setStatus] = useState<MfaStatus | null>(null);
  const [enroll, setEnroll] = useState<MfaEnrollResponse | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);

  const refresh = () =>
    apiFetch<MfaStatus>("/auth/me/mfa")
      .then(setStatus)
      .catch(() => setStatus(null));

  useEffect(() => {
    void refresh();
  }, []);

  const begin = async () => {
    setBusy(true);
    setError(null);
    setRecoveryCodes(null);
    try {
      setEnroll(await apiFetch<MfaEnrollResponse>("/auth/me/mfa/enroll", { method: "POST" }));
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const activate = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await apiFetch<MfaRecoveryCodesResponse>("/auth/me/mfa/activate", {
        method: "POST",
        body: JSON.stringify({ code: code.trim() }),
      });
      setRecoveryCodes(result.recovery_codes);
      setEnroll(null);
      setCode("");
      toast.success("Two-factor is on", "Save your recovery codes somewhere safe.");
      await refresh();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const disable = async () => {
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/auth/me/mfa/disable", {
        method: "POST",
        body: JSON.stringify({ code: code.trim() }),
      });
      setCode("");
      setRecoveryCodes(null);
      toast.success("Two-factor turned off", "You can turn it back on any time.");
      await refresh();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const regenerate = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await apiFetch<MfaRecoveryCodesResponse>("/auth/me/mfa/recovery-codes", {
        method: "POST",
        body: JSON.stringify({ code: code.trim() }),
      });
      setRecoveryCodes(result.recovery_codes);
      setCode("");
      toast.success("New recovery codes", "The old codes no longer work.");
      await refresh();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const errorBox = error ? (
    <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
      {error}
    </div>
  ) : null;

  if (recoveryCodes) {
    return (
      <div className="space-y-4">
        <p className="text-[13px] leading-6 text-ink-2">
          Save these recovery codes now — each works once if you lose your authenticator. They are
          shown only this once.
        </p>
        <ul className="grid grid-cols-2 gap-2 rounded-xl border border-line bg-sunken p-4 font-mono text-[13px] text-ink">
          {recoveryCodes.map((recoveryCode) => (
            <li key={recoveryCode}>{recoveryCode}</li>
          ))}
        </ul>
        <Button variant="secondary" onClick={() => setRecoveryCodes(null)}>
          I have saved them
        </Button>
      </div>
    );
  }

  // Mid-enrolment: show the QR + secret and ask for a confirming code.
  if (enroll) {
    return (
      <div className="space-y-4">
        <p className="text-[13px] leading-6 text-ink-2">
          Scan this with an authenticator app (or type the secret by hand), then enter the 6-digit
          code it shows to turn two-factor on.
        </p>
        <div className="flex flex-col items-start gap-4 sm:flex-row">
          <div
            className="w-40 shrink-0 rounded-xl border border-line p-2 [&_svg]:h-full [&_svg]:w-full"
            aria-label="Two-factor QR code"
            dangerouslySetInnerHTML={{ __html: enroll.qr_svg }}
          />
          <div className="space-y-3">
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-muted">Secret</div>
              <code className="mt-1 block break-all rounded-lg bg-sunken px-2 py-1 font-mono text-[13px] text-ink-2">
                {enroll.secret}
              </code>
            </div>
            <FormField label="6-digit code" htmlFor="mfa-activate-code">
              <Input
                id="mfa-activate-code"
                value={code}
                onChange={(event) => setCode(event.target.value)}
                inputMode="numeric"
                placeholder="123456"
                autoFocus
              />
            </FormField>
          </div>
        </div>
        {errorBox}
        <div className="flex gap-2">
          <Button onClick={() => void activate()} disabled={busy || code.trim().length < 6}>
            {busy ? "Verifying…" : "Turn on two-factor"}
          </Button>
          <Button variant="secondary" onClick={() => { setEnroll(null); setCode(""); setError(null); }}>
            Cancel
          </Button>
        </div>
      </div>
    );
  }

  // Active: offer to add recovery codes or turn it off (both need a live code).
  if (status?.active) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2 text-[13px] text-ink-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-success-line bg-success-soft px-2.5 py-0.5 text-[11px] font-medium uppercase tracking-[0.14em] text-success">
            On
          </span>
          <span>{status.recovery_codes_remaining} recovery code(s) left.</span>
        </div>
        <p className="text-[13px] leading-6 text-ink-3">
          Enter a current code (or a recovery code) to change or turn off two-factor.
        </p>
        <FormField label="Authentication code" htmlFor="mfa-manage-code">
          <Input
            id="mfa-manage-code"
            value={code}
            onChange={(event) => setCode(event.target.value)}
            inputMode="numeric"
            placeholder="123456"
          />
        </FormField>
        {errorBox}
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => void regenerate()} disabled={busy || code.trim().length < 6}>
            New recovery codes
          </Button>
          <Button variant="danger" onClick={() => void disable()} disabled={busy || code.trim().length < 6}>
            Turn off two-factor
          </Button>
        </div>
      </div>
    );
  }

  // Off: offer to enrol.
  return (
    <div className="space-y-4">
      <p className="text-[13px] leading-6 text-ink-2">
        Add a second factor so a stolen password is not enough to sign in. You will need an
        authenticator app such as Google Authenticator, 1Password, or Authy.
      </p>
      {errorBox}
      <Button onClick={() => void begin()} disabled={busy}>
        {busy ? "Starting…" : "Set up two-factor"}
      </Button>
    </div>
  );
}
