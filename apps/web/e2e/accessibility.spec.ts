import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

/*
 * Accessibility on each page template (A7, X8), with axe-core: WCAG 2.1 A and
 * AA. A serious or critical violation fails the build; the rest are printed,
 * so they stay visible without blocking.
 */

async function audit(page: Page, name: string): Promise<void> {
  // Pages fade in, and colours ease between themes: measure the finished
  // page, not a frame half way through (axe reads the blended colour).
  await page.waitForFunction(() =>
    document.getAnimations().every((animation) => animation.playState !== "running" || animation.effect?.getTiming().iterations === Infinity),
  );
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    // The framework's dev-only overlay is not part of the product.
    .exclude("nextjs-portal")
    .analyze();
  // One heading names each page; editors give theirs to screen readers only.
  expect.soft(await page.locator("h1").count(), `${name}: one h1`).toBe(1);
  const blocking = results.violations.filter((item) => item.impact === "serious" || item.impact === "critical");
  for (const item of results.violations) {
    console.log(`${name}: ${item.impact} ${item.id} (${item.nodes.length}) ${item.help}`);
  }
  expect.soft(blocking.map((item) => `${item.id}: ${item.help} [${item.nodes[0]?.target.join(" ")}] ${item.nodes[0]?.failureSummary?.split("\n")[1] ?? ""}`), name).toEqual([]);
}

test.describe("signed out", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("the sign-in page", async ({ page }) => {
    await page.goto("/login");
    await audit(page, "sign in");
  });
});

test("each page template, signed in", async ({ page }) => {
  await page.goto("/");
  await audit(page, "home");

  await page.goto("/projects");
  await audit(page, "projects");

  // A project of its own, with data, so the project pages have content.
  await page.getByRole("button", { name: "New project" }).first().click();
  await page.getByLabel("Name", { exact: true }).fill(`Accessibility ${Date.now()}`);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/);
  const project = new URL(page.url()).pathname;
  await page.getByRole("button", { name: "Add data" }).first().click();
  await page.getByRole("dialog").getByRole("button", { name: "Add", exact: true }).first().click();
  await expect(page).toHaveURL(/\/datasets\/[0-9a-f-]{36}/);
  await page.waitForLoadState("networkidle");
  await audit(page, "dataset");

  for (const [name, path] of [
    ["project overview", ""],
    ["datasets", "/datasets"],
    ["studio", "/studio"],
    ["sql", "/workbench"],
    ["notebooks", "/notebooks"],
    ["table editor", "/table-editor"],
    ["checks", "/checks"],
    ["dashboards", "/dashboards"],
    ["schedules", "/schedules"],
  ] as const) {
    await page.goto(`${project}${path}`);
    await page.waitForLoadState("networkidle");
    await audit(page, name);
  }

  for (const [name, path] of [
    ["help", "/help/data"],
    ["system status", "/system-status"],
    ["your settings", "/settings"],
  ] as const) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await audit(page, name);
  }
});

test("the same templates in the dark theme", async ({ page }) => {
  for (const [name, path] of [
    ["home", "/"],
    ["projects", "/projects"],
    ["help", "/help/trust"],
    ["system status", "/system-status"],
  ] as const) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));
    // Colours ease from one theme to the other over transitions that have
    // not started yet when this returns; give them a moment to begin.
    await page.waitForTimeout(100);
    await audit(page, `${name}, dark`);
  }
});
