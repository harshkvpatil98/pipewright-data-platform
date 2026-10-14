import "server-only";

import { headers } from "next/headers";

import { serverApiFetch } from "@/lib/api/server";
import { viewerAddress } from "@/lib/viewer-address";

/** A public API read made for the person viewing the page, carrying their address. */
export async function publicApiFetch<T>(path: string): Promise<T> {
  const incoming = await headers();
  const address = viewerAddress(incoming.get("x-forwarded-for"), Number(process.env.TRUSTED_PROXY_HOPS ?? 0));
  return serverApiFetch<T>(path, address ? { headers: { "X-Forwarded-For": address } } : undefined);
}
