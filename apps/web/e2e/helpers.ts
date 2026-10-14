import { expect, type Page } from "@playwright/test";

import { ALL_TOUR_IDS } from "../src/components/tour/tours";

export const USERNAME = process.env.E2E_USERNAME ?? "platform-admin";
export const PASSWORD = process.env.E2E_PASSWORD ?? "change-me-now";

/** Sign in through the form, as a person would. */
export async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Username").fill(USERNAME);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/\/login/);
  // The first-visit tours are for people; the tests know the way.
  const keys = ALL_TOUR_IDS.map((id) => `pipewright.tour.${id}`);
  await page.evaluate((tourKeys) => {
    for (const key of tourKeys) window.localStorage.setItem(key, "done");
  }, keys);
}
