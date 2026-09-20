import {
  OrganisationsPageView,
  type Organisation,
} from "@/features/organisations/components/organisations-page";
import { ApiError } from "@/lib/api/errors";
import { requireCurrentUser } from "@/lib/auth/server";
import { serverApiFetch } from "@/lib/api/server";
import type { AuthUser } from "@platform/shared-types";

export default async function OrganisationsPage() {
  const currentUser = await requireCurrentUser();

  // The listing is platform-admin only. A non-admin reaching this URL should
  // be told so, not shown a crashed page — so the refusal is carried into the
  // view rather than thrown.
  let organisations: Organisation[] = [];
  let restricted: string | null = null;
  try {
    organisations = (
      await serverApiFetch<{ items: Organisation[] }>("/organisations")
    ).items;
  } catch (error) {
    if (error instanceof ApiError && (error.status === 403 || error.status === 401)) {
      restricted = "Only a platform admin can see or manage organisations.";
    } else {
      throw error;
    }
  }

  const users = restricted
    ? []
    : (await serverApiFetch<{ items: AuthUser[] }>("/auth/users")).items;

  return (
    <OrganisationsPageView
      currentUser={currentUser}
      organisations={organisations}
      users={users}
      restricted={restricted}
    />
  );
}
