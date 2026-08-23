import { SettingsPageView } from "@/features/settings/components/settings-page";
import { requireCurrentUser } from "@/lib/auth/server";

export const metadata = { title: "Settings" };

export default async function SettingsPage() {
  const currentUser = await requireCurrentUser();
  return <SettingsPageView currentUser={currentUser} />;
}
