import "server-only";

import { cookies } from "next/headers";

export async function getServerAccessToken(): Promise<string | null> {
  const cookieStore = await cookies();
  return cookieStore.get("idp_access_token")?.value ?? null;
}
