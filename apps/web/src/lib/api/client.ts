import { parseApiResponse } from "@/lib/api/errors";
import { getAccessToken } from "@/lib/auth/session";
import { appConfig } from "@/lib/config";

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const accessToken = getAccessToken();
  const isFormData = init?.body instanceof FormData;
  const response = await fetch(`${appConfig.apiBaseUrl}${path}`, {
    ...init,
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });

  return parseApiResponse<T>(response);
}

/**
 * Fetch a file the API generates rather than a JSON body.
 *
 * Kept beside `apiFetch` so both read the token the same way: a component that
 * reaches into localStorage itself is a component that keeps working right up
 * until the session moves.
 */
export async function apiDownload(
  path: string,
  init?: RequestInit,
): Promise<{ blob: Blob; filename: string | null }> {
  const accessToken = getAccessToken();
  const response = await fetch(`${appConfig.apiBaseUrl}${path}`, {
    ...init,
    headers: {
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...(init?.headers ?? {}),
    },
    credentials: "include",
    cache: "no-store",
  });

  if (!response.ok) {
    // Errors still come back as JSON, so reuse the normal parser to get the
    // message the API meant to show.
    await parseApiResponse(response);
  }

  const disposition = response.headers.get("content-disposition") ?? "";
  const match = disposition.match(/filename="([^"]+)"/);
  return { blob: await response.blob(), filename: match ? match[1] : null };
}
