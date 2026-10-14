/**
 * The address of the person viewing a public page, for the API's rate limit.
 *
 * Shared and embedded dashboards are fetched by this server, so without this
 * the API sees one address for everyone viewing them and limits them all as
 * one. The address is read as the API reads its own: `TRUSTED_PROXY_HOPS`
 * proxies in front, each adding the address it received from. With none
 * trusted there is nothing safe to pass on, and the API uses this server's.
 */
export function viewerAddress(forwardedFor: string | null, trustedProxyHops: number): string | null {
  if (!forwardedFor || !(trustedProxyHops > 0)) return null;
  const hops = forwardedFor
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
  if (hops.length === 0) return null;
  return hops[Math.max(0, hops.length - trustedProxyHops)] ?? null;
}
