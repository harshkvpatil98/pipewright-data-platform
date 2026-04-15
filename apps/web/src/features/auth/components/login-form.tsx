"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { Button, FormField, Input, SectionPanel } from "@platform/shared-ui";
import type { AuthTokenResponse, LoginPayload } from "@platform/shared-types";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { setAccessToken } from "@/lib/auth/session";

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  return (
    <main className="mx-auto flex min-h-screen max-w-xl items-center px-6 py-10">
      <SectionPanel
        title="Platform login"
        description="Authenticate with a bootstrapped platform user to access your owned projects and run history."
      >
        <form className="space-y-5" onSubmit={handleSubmit}>
          <FormField label="Username" htmlFor="username">
            <Input id="username" value={username} onChange={(event) => setUsername(event.target.value)} autoFocus />
          </FormField>
          <FormField label="Password" htmlFor="password">
            <Input id="password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
          </FormField>
          {error ? <div className="rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">{error}</div> : null}
          <Button type="submit" disabled={submitting || username.length < 3 || password.length < 8} className="w-full">
            {submitting ? "Signing in..." : "Sign in"}
          </Button>
        </form>
      </SectionPanel>
    </main>
  );
}
