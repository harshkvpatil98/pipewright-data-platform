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
