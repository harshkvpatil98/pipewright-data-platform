import { PeoplePageView } from "@/features/people/components/people-page";
import { requireCurrentUser } from "@/lib/auth/server";
import { serverApiFetch } from "@/lib/api/server";
import type { AuthUser } from "@platform/shared-types";

export default async function PeoplePage() {
  const currentUser = await requireCurrentUser();
  const response = await serverApiFetch<{ items: AuthUser[] }>("/auth/users");
  return <PeoplePageView currentUser={currentUser} users={response.items} />;
}
