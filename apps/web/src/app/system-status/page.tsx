import { SystemStatusPage } from "@/features/system-status/components/system-status-page";
import { getCurrentUser } from "@/lib/auth/server";

export const metadata = { title: "System status" };

// Readable without signing in -- a status page that needs a working login to
// say the login is down is no status page -- but a signed-in visitor should
// still see their own account in the top bar, not a "?".
export default async function SystemStatusRoute() {
  const currentUser = await getCurrentUser();
  return <SystemStatusPage currentUser={currentUser} />;
}
