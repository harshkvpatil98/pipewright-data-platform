import { defineConfig, devices } from "@playwright/test";

/**
 * Browser tests (adoption-readiness A7, X8): the golden path a new person
 * follows, and an accessibility check on each page template. They run against
 * a running app: E2E_BASE_URL (the web app) with E2E_USERNAME and
 * E2E_PASSWORD for an account on it. CI starts a gateway and the production
 * web build for them; locally, point them at the dev stack.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    viewport: { width: 1280, height: 800 },
  },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "chromium",
      dependencies: ["setup"],
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 }, storageState: "e2e/.auth/session.json" },
    },
  ],
});
