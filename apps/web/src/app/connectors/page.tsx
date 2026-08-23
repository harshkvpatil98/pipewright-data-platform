import { ConnectorCatalogPageView } from "@/features/connectors/components/connector-catalog-page";
import { serverApiFetch } from "@/lib/api/server";
import { requireCurrentUser } from "@/lib/auth/server";
import type { ConnectorCatalogResponse } from "@platform/shared-types";

export const metadata = { title: "Connectors" };

export default async function ConnectorsPage() {
  const currentUser = await requireCurrentUser();
  const catalogue = await serverApiFetch<ConnectorCatalogResponse>("/connectors");
  return <ConnectorCatalogPageView currentUser={currentUser} initial={catalogue} />;
}
