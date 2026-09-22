"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { Button, FormField, Input, LogoMark, SectionPanel } from "@platform/shared-ui";
import type { AuthTokenResponse, LoginPayload } from "@platform/shared-types";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { setAccessToken } from "@/lib/auth/session";
import { brand } from "@/lib/brand";

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"signin" | "code">("signin");
  const [code, setCode] = useState("");
  const [codePassword, setCodePassword] = useState("");

  const nextPath = searchParams.get("next") || "/projects";

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const payload: LoginPayload = { username, password };
      const response = await apiFetch<AuthTokenResponse>("/auth/login", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setAccessToken(response.access_token);
      router.push(nextPath);
      router.refresh();
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
        title={mode === "signin" ? "Sign in" : "Set your password"}
        description={
          mode === "signin"
            ? "Sign in to your Pipewright workspace."
            : "Enter the one-time code you were given, and choose a password."
        }
      >
        {mode === "signin" ? (
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
