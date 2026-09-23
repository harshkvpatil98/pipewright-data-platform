import type { SsoAvailability } from "@platform/shared-types";

/** Which single sign-on button the login screen offers, if any. */
export type SsoProvider = "oidc" | "saml";

/** Where a sign-in of each kind starts. */
export const SSO_START_PATH: Record<SsoProvider, string> = {
  oidc: "/auth/sso/start",
  saml: "/auth/saml/start",
};

/**
 * Decide what the login screen offers.
 *
 * OIDC wins when a deployment has configured both. It is the better protocol,
 * and two buttons that mean the same thing to the person signing in is a
 * choice they have no way to make. A deployment that wants the SAML button
 * instead unsets the OIDC settings, which is also the honest way to say which
 * provider it actually uses.
 */
export function chooseSsoProvider(
  status: Pick<SsoAvailability, "oidc_configured" | "saml_configured"> | null | undefined,
): SsoProvider | null {
  if (!status) return null;
  if (status.oidc_configured) return "oidc";
  if (status.saml_configured) return "saml";
  return null;
}
