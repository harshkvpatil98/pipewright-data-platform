import "server-only";

import { redirect } from "next/navigation";

import type { AuthUser } from "@platform/shared-types";

import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";

export async function getCurrentUser(): Promise<AuthUser | null> {
  try {
    return await serverApiFetch<AuthUser>("/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null;
    }
    throw error;
  }
}

export async function requireCurrentUser(): Promise<AuthUser> {
  const user = await getCurrentUser();
  if (user === null) {
    redirect("/login");
  }
  return user;
}
