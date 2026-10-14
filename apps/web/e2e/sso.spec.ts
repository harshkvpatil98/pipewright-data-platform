import { expect, test } from "@playwright/test";

/*
 * Single sign-on against a live identity provider (A8): "Continue with SSO",
 * the provider's own sign-in form, and back into Pipewright signed in, with
 * the account made from the provider's claims. CI runs Keycloak for it
 * (`scripts/sso-test-provider.py`); without E2E_SSO_USERNAME it is skipped.
 */
test.use({ storageState: { cookies: [], origins: [] } });

test("signing in through the identity provider", async ({ page }) => {
  const username = process.env.E2E_SSO_USERNAME;
  test.skip(!username, "No identity provider: set E2E_SSO_USERNAME and E2E_SSO_PASSWORD.");

  await page.goto("/login");
  await page
    .getByRole("link", { name: /Continue with SSO/i })
    .or(page.getByRole("button", { name: /Continue with SSO/i }))
    .first()
    .click();

  // The provider's own form, on the provider's address.
  await page.locator("#username").fill(username ?? "");
  await page.locator("#password").fill(process.env.E2E_SSO_PASSWORD ?? "");
  await page.locator("#kc-login").click();

  const web = new URL(process.env.E2E_BASE_URL ?? "http://localhost:3000").origin;
  await page.waitForURL((url) => url.origin === web && !url.pathname.startsWith("/login"));

  // The gateway set the session on its own address; ask it who this is.
  const api = process.env.E2E_API_URL ?? "http://localhost:8000/api/v1";
  const me = await page.request.get(`${api}/auth/me`);
  expect(me.ok()).toBe(true);
  expect(await me.json()).toMatchObject({
    username,
    email: "ann@example.com",
    display_name: "Ann Example",
    role: "admin",
  });
});
