import Link from "next/link";

import { buttonClassName } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { getCurrentUser } from "@/lib/auth/server";

export const metadata = { title: "Page not found" };

/**
 * Shown for any address that does not exist, inside the normal frame so the
 * navigation is still there to get somewhere useful.
 */
export default async function NotFound() {
  const currentUser = await getCurrentUser().catch(() => null);

  return (
    <AppShell
      currentUser={currentUser}
      title="We could not find that page"
      subtitle="The link may be out of date, or what it pointed to has been deleted."
    >
      <div className="flex flex-wrap gap-2">
        <Link href="/" className={buttonClassName("primary", "sm")}>
          Go to Home
        </Link>
        <Link href="/projects" className={buttonClassName("secondary", "sm")}>
          See your projects
        </Link>
      </div>
    </AppShell>
  );
}
