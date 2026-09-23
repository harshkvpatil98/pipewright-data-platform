import { describe, expect, it } from "vitest";

import { SSO_START_PATH, chooseSsoProvider } from "./sso-choice";

describe("which sign-in the login screen offers", () => {
  it("offers nothing when no provider is configured", () => {
    expect(chooseSsoProvider({ oidc_configured: false, saml_configured: false })).toBeNull();
  });

  it("offers OIDC when only OIDC is configured", () => {
    expect(chooseSsoProvider({ oidc_configured: true, saml_configured: false })).toBe("oidc");
  });

  it("offers SAML when that is the only protocol the provider speaks", () => {
    expect(chooseSsoProvider({ oidc_configured: false, saml_configured: true })).toBe("saml");
  });

  it("prefers OIDC when a deployment has configured both", () => {
    expect(chooseSsoProvider({ oidc_configured: true, saml_configured: true })).toBe("oidc");
  });

  it("offers nothing when the status could not be read", () => {
    // The status call failing must not show a button that cannot work.
    expect(chooseSsoProvider(null)).toBeNull();
    expect(chooseSsoProvider(undefined)).toBeNull();
  });

  it("sends each protocol to its own start route", () => {
    expect(SSO_START_PATH.oidc).toBe("/auth/sso/start");
    expect(SSO_START_PATH.saml).toBe("/auth/saml/start");
  });
});
