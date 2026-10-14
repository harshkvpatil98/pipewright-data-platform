import { expect, test } from "@playwright/test";

test("a new project goes from nothing to cleaned data", async ({ page }) => {
  await page.goto("/projects");
  await page.getByRole("button", { name: "New project" }).first().click();
  await page.getByLabel("Name", { exact: true }).fill(`Browser test ${Date.now()}`);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/);

  await page.getByRole("button", { name: "Add data" }).first().click();
  const addData = page.getByRole("dialog");
  await addData.getByRole("button", { name: "Add", exact: true }).first().click();
  await expect(page).toHaveURL(/\/datasets\/[0-9a-f-]{36}/);
  await expect(page.getByRole("heading", { name: "Rows" })).toBeVisible();

  // Clean it: one step from the search, saved as a recipe and run.
  await page.getByRole("link", { name: "Clean in Studio" }).click();
  await expect(page).toHaveURL(/\/studio/);
  await page.getByRole("button", { name: "Add a step" }).click();
  await page.getByPlaceholder(/What do you want to do/).fill("remove duplicates");
  await page.keyboard.press("Enter");
  await expect(page.getByText("Not saved yet")).toBeVisible();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Run", exact: true }).click();
  await page.getByRole("button", { name: "Open the result" }).click();
  await expect(page).toHaveURL(/\/datasets\/[0-9a-f-]{36}/);
  await expect(page.getByText("Made by a recipe").first()).toBeVisible();
  const projectUrl = page.url().replace(/\/datasets\/.*$/, "");

  // Check it: every order has an id.
  await page.goto(`${projectUrl}/checks`);
  await page.getByRole("button", { name: "New check" }).first().click();
  const newCheck = page.getByRole("dialog");
  await newCheck.getByLabel("Name", { exact: true }).fill("Every order has an id");
  await newCheck.getByLabel("What it checks").selectOption({ label: "Must have a value" });
  await newCheck.getByLabel("Dataset").selectOption({ label: "Sample orders" });
  await newCheck.getByLabel("Column").selectOption("order_id");
  await newCheck.getByRole("button", { name: "Save check" }).click();
  await expect(page.getByText("Every order has an id")).toBeVisible();

  // Chart it, onto a new dashboard.
  await page.goto(`${projectUrl}/charts`);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByRole("button", { name: "Put it on a new dashboard" }).click();
  await expect(page).toHaveURL(/\/dashboards\/[0-9a-f-]{36}/);
  await page.screenshot({ path: "test-results/dashboard.png" });
});
