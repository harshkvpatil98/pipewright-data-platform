import { requireCurrentUser } from "@/lib/auth/server";
import { redirectToProjectScope } from "@/lib/project-scope";

export const dynamic = "force-dynamic";

export default async function DatasetsPage() {
  await requireCurrentUser();
  await redirectToProjectScope("");
}
