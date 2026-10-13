/**
 * The `exp` claim of a sign-in token, read without checking its signature, or
 * null for anything that is not one (an API token, garbage). Only ever used to
 * decide when to renew or where to send someone; the API verifies every token.
 */
export function tokenExpiry(token: string): number | null {
  const part = token.split(".")[1];
  if (!part) return null;
  try {
    const json = atob(part.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(part.length / 4) * 4, "="));
    const exp = (JSON.parse(json) as { exp?: unknown }).exp;
    return typeof exp === "number" ? exp : null;
  } catch {
    return null;
  }
}
