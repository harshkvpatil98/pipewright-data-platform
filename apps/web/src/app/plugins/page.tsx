import type { PluginListResponse } from "@platform/shared-types";

import { PluginsPageView } from "@/features/plugins/components/plugins-page";
import { ApiError } from "@/lib/api/errors";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";

export const metadata = { title: "Plugins" };

export const dynamic = "force-dynamic";

export default async function PluginsPage() {
  const currentUser = await requireCurrentUser();
  try {
    const listed = await serverApiFetch<PluginListResponse>("/plugins");
    return <PluginsPageView currentUser={currentUser} listed={listed} forbidden={false} />;
  } catch (error) {
    // Only a platform admin may see what is loaded into the server.
    if (error instanceof ApiError && error.status === 403) {
      return <PluginsPageView currentUser={currentUser} listed={null} forbidden />;
    }
    throw error;
  }
}
