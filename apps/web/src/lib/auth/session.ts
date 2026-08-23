export const ACCESS_TOKEN_KEY = "idp.access_token";
export const ACCESS_TOKEN_COOKIE = "idp_access_token";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }

  const stored = window.localStorage.getItem(ACCESS_TOKEN_KEY);
  if (stored) {
    return stored;
  }

  // The cookie is what server components authenticate with. If localStorage was
  // cleared independently (private mode, site-data reset, a second tab signing
  // out), pages would still render while every client request failed. Falling
  // back to the cookie keeps both halves of the app on the same session.
  const match = document.cookie.match(
    new RegExp(`(?:^|;\\s*)${ACCESS_TOKEN_COOKIE}=([^;]*)`),
  );
  // A cleared cookie is written as an empty value, which is not a session.
  const value = match ? decodeURIComponent(match[1]) : "";
  return value || null;
}

export function setAccessToken(token: string): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(ACCESS_TOKEN_KEY, token);
  document.cookie = `${ACCESS_TOKEN_COOKIE}=${token}; path=/; samesite=lax`;
}

export function clearAccessToken(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
  document.cookie = `${ACCESS_TOKEN_COOKIE}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; samesite=lax`;
}
