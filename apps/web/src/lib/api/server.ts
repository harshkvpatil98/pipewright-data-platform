import "server-only";

import { parseApiResponse } from "@/lib/api/errors";
import { getServerAccessToken } from "@/lib/auth/cookies";
import { appConfig } from "@/lib/config";

export async function serverApiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const accessToken = await getServerAccessToken();
  const response = await fetch(`${appConfig.internalApiBaseUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });

  return parseApiResponse<T>(response);
}
