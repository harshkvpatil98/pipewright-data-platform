import { NotificationsPage } from "@/features/notifications/components/notifications-page";
import { requireCurrentUser } from "@/lib/auth/server";

export default async function NotificationsRoute() {
  const currentUser = await requireCurrentUser();
  return <NotificationsPage currentUser={currentUser} />;
}
