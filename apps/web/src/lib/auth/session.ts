export const ACCESS_TOKEN_KEY = "idp.access_token";
export const ACCESS_TOKEN_COOKIE = "idp_access_token";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(ACCESS_TOKEN_KEY);
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
