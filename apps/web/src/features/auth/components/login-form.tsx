"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { Button, FormField, Input, LogoMark, SectionPanel } from "@platform/shared-ui";
import type { AuthTokenResponse, LoginPayload, LoginResult } from "@platform/shared-types";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { setAccessToken } from "@/lib/auth/session";
import { appConfig } from "@/lib/config";
import { brand } from "@/lib/brand";

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"signin" | "code" | "mfa">("signin");
  const [code, setCode] = useState("");
  const [codePassword, setCodePassword] = useState("");
  const [mfaTicket, setMfaTicket] = useState<string | null>(null);
  const [mfaCode, setMfaCode] = useState("");
  const [ssoConfigured, setSsoConfigured] = useState(false);

  const nextPath = searchParams.get("next") || "/projects";

  // Show "Continue with SSO" only when a provider is actually configured, and
  // surface a message if the provider bounced us back with an error.
  // An emailed invitation or reset link lands here with ?code=; open the
  // redeem form with it filled in, so the person only types a password.
  useEffect(() => {
    const linked = searchParams.get("code");
    if (linked) {
      setCode(linked);
      setMode("code");
    }
  }, [searchParams]);

  useEffect(() => {
    const ssoError = searchParams.get("sso_error");
    if (ssoError) setError(ssoError);
    apiFetch<{ oidc_configured: boolean }>("/auth/sso/status")
      .then((status) => setSsoConfigured(Boolean(status.oidc_configured)))
      .catch(() => setSsoConfigured(false));
  }, [searchParams]);

  const startSso = () => {
    // A full navigation, not a fetch: the flow is a 302 to the provider.
    window.location.href = `${appConfig.apiBaseUrl}/auth/sso/start?next=${encodeURIComponent(nextPath)}`;
  };

  const finishLogin = (result: LoginResult) => {
    if (result.access_token) {
      setAccessToken(result.access_token);
      router.push(nextPath);
      router.refresh();
    }
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const payload: LoginPayload = { username, password };
      const response = await apiFetch<LoginResult>("/auth/login", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (response.status === "mfa_required") {
        // Password accepted; a second factor is on. Hold the ticket and ask
        // for the code rather than dropping the browser back to the start.
        setMfaTicket(response.mfa_ticket);
        setMode("mfa");
        setSubmitting(false);
        return;
      }
      finishLogin(response);
    } catch (submitError) {
      setError(extractErrorMessage(submitError));
      setSubmitting(false);
    }
  };

  const submitMfa = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const response = await apiFetch<LoginResult>("/auth/login/mfa", {
        method: "POST",
        body: JSON.stringify({ mfa_ticket: mfaTicket, code: mfaCode.trim() }),
      });
      finishLogin(response);
    } catch (submitError) {
      setError(extractErrorMessage(submitError));
      setSubmitting(false);
    }
  };

  const redeemCode = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const response = await apiFetch<AuthTokenResponse>("/auth/redeem-code", {
        method: "POST",
        body: JSON.stringify({ code: code.trim(), new_password: codePassword }),
      });
      setAccessToken(response.access_token);
      router.push(nextPath);
      router.refresh();
    } catch (submitError) {
      setError(extractErrorMessage(submitError));
      setSubmitting(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-6 py-10">
      <div className="mb-8 flex flex-col items-center text-center animate-fade-up">
        <LogoMark size={64} title={brand.name} />
        <h1 className="mt-4 text-3xl font-semibold tracking-tight text-ink">{brand.name}</h1>
        <p className="mt-2 text-sm text-ink-3">{brand.shortDescription}</p>
      </div>
      <SectionPanel
        title={
          mode === "signin"
            ? "Sign in"
            : mode === "mfa"
              ? "Two-factor authentication"
              : "Set your password"
        }
        description={
          mode === "signin"
            ? "Sign in to your Pipewright workspace."
            : mode === "mfa"
              ? "Enter the 6-digit code from your authenticator app, or a recovery code."
              : "Enter the one-time code you were given, and choose a password."
        }
      >
        {mode === "mfa" ? (
          <form className="space-y-5" onSubmit={submitMfa}>
            <FormField label="Authentication code" htmlFor="mfa-code">
              <Input
                id="mfa-code"
                value={mfaCode}
                onChange={(event) => setMfaCode(event.target.value)}
                autoFocus
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="123456"
              />
            </FormField>
            {error ? <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div> : null}
            <Button type="submit" disabled={submitting || mfaCode.trim().length < 6} className="w-full">
              {submitting ? "Verifying..." : "Verify"}
            </Button>
            <button
              type="button"
              onClick={() => { setMode("signin"); setError(null); setMfaCode(""); setMfaTicket(null); }}
              className="w-full text-center text-[12px] text-ink-3 transition hover:text-ink"
            >
              Back to sign in
            </button>
          </form>
        ) : mode === "signin" ? (
          <form className="space-y-5" onSubmit={handleSubmit}>
            <FormField label="Username" htmlFor="username">
              <Input id="username" value={username} onChange={(event) => setUsername(event.target.value)} autoFocus />
            </FormField>
            <FormField label="Password" htmlFor="password">
              <Input id="password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
            </FormField>
            {error ? <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div> : null}
            <Button type="submit" disabled={submitting || username.length < 3 || password.length < 8} className="w-full">
              {submitting ? "Signing in..." : "Sign in"}
            </Button>
            {ssoConfigured ? (
              <>
                <div className="flex items-center gap-3 text-[11px] uppercase tracking-[0.16em] text-muted">
                  <span className="h-px flex-1 bg-line" />
                  or
                  <span className="h-px flex-1 bg-line" />
                </div>
                <Button type="button" variant="secondary" onClick={startSso} className="w-full">
                  Continue with SSO
                </Button>
              </>
            ) : null}
            <button
              type="button"
              onClick={() => { setMode("code"); setError(null); }}
              className="w-full text-center text-[12px] text-ink-3 transition hover:text-ink"
            >
              Have an invite or reset code?
            </button>
          </form>
        ) : (
          <form className="space-y-5" onSubmit={redeemCode}>
            <FormField label="One-time code" htmlFor="code">
              <Input id="code" value={code} onChange={(event) => setCode(event.target.value)} autoFocus />
            </FormField>
            <FormField label="New password" htmlFor="code-password">
              <Input id="code-password" type="password" value={codePassword} onChange={(event) => setCodePassword(event.target.value)} />
            </FormField>
            {error ? <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div> : null}
            <Button type="submit" disabled={submitting || code.trim().length < 8 || codePassword.length < 8} className="w-full">
              {submitting ? "Setting password..." : "Set password and sign in"}
            </Button>
            <button
              type="button"
              onClick={() => { setMode("signin"); setError(null); }}
              className="w-full text-center text-[12px] text-ink-3 transition hover:text-ink"
            >
              Back to sign in
            </button>
          </form>
        )}
      </SectionPanel>
    </main>
  );
}
