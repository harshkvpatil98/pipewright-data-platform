import { getAccessToken, setAccessToken } from "@/lib/auth/session";
import { tokenExpiry } from "@/lib/auth/token-expiry";
import { appConfig } from "@/lib/config";

export { tokenExpiry };

/** Renew once fewer than this many seconds are left on the token. */
export const RENEW_WITHIN_SECONDS = 15 * 60;

/** True when the token is still valid but close enough to expiry to renew. */
export function shouldRenew(token: string, nowSeconds: number): boolean {
  const exp = tokenExpiry(token);
  return exp !== null && exp > nowSeconds && exp - nowSeconds < RENEW_WITHIN_SECONDS;
}

let inFlight: Promise<void> | null = null;

/**
 * Swap a sign-in token that is about to expire for a fresh one, so someone
 * using the app is not signed out mid-task. Called on activity only: a tab
 * left alone still runs out, and the server caps how long a session can be
 * renewed for. Failure is silent; the next request that is refused sends the
 * person to sign in.
 */
export function renewIfDue(): void {
  if (typeof window === "undefined" || inFlight) return;
  const token = getAccessToken();
  if (!token || !shouldRenew(token, Date.now() / 1000)) return;
  inFlight = fetch(`${appConfig.apiBaseUrl}/auth/session/renew`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  })
    .then((response) => (response.ok ? (response.json() as Promise<{ access_token?: string }>) : null))
    .then((body) => {
      // Only replace the token this renewed; a sign-out or a new sign-in in
      // another tab meanwhile wins.
      if (body?.access_token && getAccessToken() === token) setAccessToken(body.access_token);
    })
    .catch(() => undefined)
    .finally(() => {
      inFlight = null;
    });
}
