import { requireCurrentUser } from "@/lib/auth/server";
import { redirectToProjectScope } from "@/lib/project-scope";

export const dynamic = "force-dynamic";

export default async function TestingPage() {
  await requireCurrentUser();
  await redirectToProjectScope("/tests/saved");
}
