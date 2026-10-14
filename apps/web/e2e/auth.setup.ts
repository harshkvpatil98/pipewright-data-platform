import { test as setup } from "@playwright/test";

import { signIn } from "./helpers";

/*
 * Signs in once, through the form, and saves the session for every other
 * test. Signing in per test would also run into the sign-in rate limit (ten
 * attempts per account and address in five minutes), which is working as
 * meant.
 */
setup("sign in", async ({ page }) => {
  await signIn(page);
  await page.context().storageState({ path: "e2e/.auth/session.json" });
});
