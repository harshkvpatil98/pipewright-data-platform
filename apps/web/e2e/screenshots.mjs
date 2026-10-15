/**
 * The help's screenshots, taken of the one-click demo (adoption-readiness A9, Z2).
 *
 *   npx playwright test --project setup          # signs in, saves e2e/.auth/session.json
 *   E2E_BASE_URL=http://localhost:3002 E2E_API_URL=http://localhost:8100/api/v1 \
 *     node e2e/screenshots.mjs [--keep]
 *
 * Makes a fresh demo project, photographs the pages the help describes at
 * 1280×800 in the light theme, writes them to `docs/user/images/`, and
 * deletes the project again (unless --keep). Because every picture is of the
 * demo a new install makes in one click, what the help shows is what a reader
 * gets. Run it after changing a page the help pictures.
 */
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const base = process.env.E2E_BASE_URL ?? "http://localhost:3000";
const api = process.env.E2E_API_URL ?? `${base.replace(/:\d+$/, ":8000")}/api/v1`;
const out = fileURLToPath(new URL("../../../docs/user/images/", import.meta.url));
mkdirSync(out, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1280, height: 800 },
  deviceScaleFactor: 1,
  storageState: "e2e/.auth/session.json",
});
// The light theme, and no welcome tour over the page.
await context.addInitScript(() => {
  try {
    localStorage.setItem("pw.theme", "light");
    for (const tour of ["welcome-v2", "studio-v2", "data-quality-v1", "schedules-v1"]) {
      localStorage.setItem(`pipewright.tour.${tour}`, "done");
    }
  } catch {
    // Pictures in the default theme are still pictures.
  }
});
const page = await context.newPage();
await page.goto(`${base}/projects`);
const token = await page.evaluate(() => localStorage.getItem("idp.access_token"));
const call = async (method, path) => {
  const response = await fetch(`${api}${path}`, { method, headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok && response.status !== 204) throw new Error(`${method} ${path}: ${response.status} ${await response.text()}`);
  return response.status === 204 ? null : response.json();
};
const items = (body) => (Array.isArray(body) ? body : body?.items ?? []);

const demo = await call("POST", "/projects/demo");
const project = demo.id;
const datasets = items(await call("GET", `/projects/${project}/datasets`));
const raw = datasets.find((dataset) => dataset.name === "Customer orders (sample)");
const cleaned = datasets.find((dataset) => dataset.id !== raw.id);
const [recipe] = items(await call("GET", `/projects/${project}/pipelines`));
const [dashboard] = items(await call("GET", `/projects/${project}/dashboards`));

const shots = [
  ["overview", `/projects/${project}`],
  ["dataset", `/projects/${project}/datasets/${raw.id}`],
  ["studio", `/projects/${project}/studio?recipe=${recipe.id}`],
  ["checks", `/projects/${project}/checks`],
  ["data-health", `/projects/${project}/datasets/${cleaned.id}/metrics`],
  ["dashboard", `/projects/${project}/dashboards/${dashboard.id}`],
  ["activity", `/projects/${project}/activity`],
];

try {
  for (const [name, path] of shots) {
    await page.goto(`${base}${path}`, { waitUntil: "networkidle", timeout: 60_000 });
    // The development build's corner badge is not part of the product.
    await page.addStyleTag({ content: "nextjs-portal { display: none !important; }" });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${out}${name}.png` });
    console.log(`${name}.png  ${path.replace(project, "{demo}")}`);
    if (name === "data-health") {
      // The alerts sit below the history; pictured on their own.
      const alerts = page.locator("section", { has: page.getByRole("heading", { name: "Alerts", exact: true }) });
      await alerts.scrollIntoViewIfNeeded();
      await alerts.screenshot({ path: `${out}alerts.png` });
      console.log("alerts.png  (the Alerts section of the same page)");
    }
  }
} finally {
  if (!process.argv.includes("--keep")) await call("DELETE", `/projects/${project}`);
  await browser.close();
}
