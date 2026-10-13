import { clearAccessToken } from "@/lib/auth/session";

let ending = false;

/** True once the session has ended and the page is on its way to sign-in. */
export function isSessionEnding(): boolean {
  return ending;
}

/** Where to send someone whose session ended while they were at `here`. */
export function signInAgainHref(here: string): string {
  return `/login?expired=1&next=${encodeURIComponent(here)}`;
}

/**
 * The API said the session is no longer valid. Rather than leave every panel
 * on the page showing "Invalid or expired access token", go to sign-in and
 * come back to the same page afterwards. Unsaved work that matters keeps its
 * own draft (the Studio does), so leaving does not lose it.
 */
export function endSession(): void {
  if (ending || typeof window === "undefined") return;
  const here = `${window.location.pathname}${window.location.search}`;
  if (here.startsWith("/login") || here.startsWith("/sign-in") || here.startsWith("/shared/")) return;
  ending = true;
  clearAccessToken();
  window.location.assign(signInAgainHref(here));
}

/**
 * A `next` address that stays on this site. Anything else (another origin, a
 * protocol-relative "//host", a non-path) falls back, so a crafted sign-in link
 * cannot send someone elsewhere after they sign in.
 */
export function safeNextPath(next: string | null, fallback = "/projects"): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return fallback;
  return next;
}
