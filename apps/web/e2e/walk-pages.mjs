/**
 * Walk every page of a running app and report what a person would trip over
 * (adoption-readiness A7, X10). Not a Playwright test: a sweep to run at the
 * end of a phase, against a stack with real data in it.
 *
 *   npx playwright test --project setup          # signs in, saves e2e/.auth/session.json
 *   E2E_BASE_URL=http://localhost:3002 E2E_API_URL=http://localhost:8100/api/v1 \
 *     node e2e/walk-pages.mjs [--width 1024] [--project <project id>] [--only <regex>]
 *
 * The pages come from `src/app/**\/page.tsx`, so a new page is walked without
 * editing this file; ids in the path are filled from the chosen project (the
 * one with the most datasets unless --project says), and a page whose ids the
 * project lacks is listed as not walked. Each page is checked, once its
 * content has loaded, for error text and raw values, console errors and 5xx
 * answers, sideways scrolling, controls with no name, tab lists or toolbars
 * cut off, and exactly one heading. It runs headless on purpose: a
 * background browser tab never reveals streamed content.
 */
import { readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const base = process.env.E2E_BASE_URL ?? "http://localhost:3000";
const api = process.env.E2E_API_URL ?? `${base.replace(/:\d+$/, ":8000")}/api/v1`;
const argument = (name) => {
  const index = process.argv.indexOf(name);
  return index > -1 ? process.argv[index + 1] : undefined;
};
const width = Number(argument("--width") ?? 1280);
const appDir = fileURLToPath(new URL("../src/app/", import.meta.url));
const docsDir = fileURLToPath(new URL("../../../docs/user/", import.meta.url));

function routes(dir) {
  const found = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) found.push(...routes(path));
    else if (name === "page.tsx") found.push(`/${relative(appDir, dir)}`.replace(/\/$/, "") || "/");
  }
  return found.sort();
}

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width, height: 900 }, storageState: "e2e/.auth/session.json" });
const page = await context.newPage();
await page.goto(`${base}/projects`);
const token = await page.evaluate(() => localStorage.getItem("idp.access_token"));
const get = async (path) => {
  const response = await fetch(`${api}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  return response.ok ? response.json() : null;
};
const items = (body) => (Array.isArray(body) ? body : body?.items ?? []);

let projectId = argument("--project");
if (!projectId) {
  let best = { id: null, count: -1 };
  for (const project of items(await get("/projects")).slice(0, 30)) {
    const count = items(await get(`/projects/${project.id}/datasets`)).length;
    if (count > best.count) best = { id: project.id, count };
  }
  projectId = best.id;
}
const first = async (path) => items(await get(`/projects/${projectId}${path}`))[0]?.id;
const datasets = items(await get(`/projects/${projectId}/datasets`));
const dashboards = items(await get(`/projects/${projectId}/dashboards`));
// An embed that is on, for /embed/[token]: a share token is not an embed's (A8, Y4).
let embedToken;
for (const dashboard of dashboards) {
  embedToken ??= items(await get(`/projects/${projectId}/dashboards/${dashboard.id}/embeds`)).find((embed) => embed.state === "on")?.token;
}
const ids = {
  projectId,
  datasetId: datasets[0]?.id,
  otherDatasetId: datasets[1]?.id,
  dashboardId: dashboards[0]?.id,
  token: dashboards.find((dashboard) => dashboard.share_token)?.share_token,
  savedTestId: await first("/tests/saved"),
  workflowId: await first("/workflows"),
  pipelineId: await first("/pipelines"),
  runId: await first("/runs"),
  incidentId: await first("/incidents"),
};

const pages = [];
const skipped = [];
for (const route of routes(appDir)) {
  if (route === "/help/[slug]") {
    for (const file of readdirSync(docsDir).filter((name) => name.endsWith(".md") && name !== "index.md")) {
      pages.push(`/help/${file.replace(/\.md$/, "")}`);
    }
    continue;
  }
  const missing = [];
  const fill = route.startsWith("/embed/") ? { ...ids, token: embedToken } : ids;
  const path = route.replace(/\[(\w+)\]/g, (_, key) => fill[key] ?? (missing.push(key), `[${key}]`));
  if (missing.length) skipped.push(`${route} (no ${missing.join(", ")} in this project)`);
  else pages.push(path);
}
pages.push(`/projects/${projectId}/datasets/00000000-0000-4000-8000-000000000000`, "/no-such-page");
const only = argument("--only") ? new RegExp(argument("--only")) : null;
if (only) {
  pages.splice(0, pages.length, ...pages.filter((path) => only.test(path)));
  skipped.splice(0, skipped.length, ...skipped.filter((line) => only.test(line)));
}

const BAD = /Application error|Unhandled Runtime Error|Something went wrong|Internal Server Error|\bundefined\b|\bNaN\b|\[object Object\]|Invalid Date|null null/;
let problems = 0;
for (const path of pages) {
  const errors = [];
  const onConsole = (message) => {
    if (message.type() === "error" && !/Download the React DevTools|favicon/.test(message.text())) {
      errors.push(`console: ${message.text().slice(0, 160)}`);
    }
  };
  const onPageError = (error) => errors.push(`page error: ${String(error.message).slice(0, 160)}`);
  const onResponse = (response) => {
    if (response.status() >= 500) errors.push(`HTTP ${response.status()} ${response.url().slice(0, 120)}`);
  };
  page.on("console", onConsole);
  page.on("pageerror", onPageError);
  page.on("response", onResponse);
  try {
    await page.goto(`${base}${path}`, { waitUntil: "load", timeout: 30_000 });
    await page.waitForTimeout(2500);
  } catch (error) {
    errors.push(`did not load: ${String(error.message).slice(0, 100)}`);
  }
  const found = await page.evaluate((bad) => {
    const issues = [];
    const text = document.body.innerText;
    const match = text.match(new RegExp(bad));
    if (match) issues.push(`says "${match[0]}": …${text.slice(Math.max(0, match.index - 50), match.index + 30).replace(/\s+/g, " ")}…`);
    if (document.documentElement.scrollWidth > innerWidth + 2) issues.push(`scrolls sideways (${document.documentElement.scrollWidth}px)`);
    // Streamed content is revealed into place once the page is visible; a
    // block still hidden with words in it means the page rendered twice
    // (A8, Y8). An empty one is a placeholder a not-found cut short.
    const leftover = [...document.querySelectorAll('div[hidden][id^="S:"]')].filter((block) => block.textContent.trim()).length;
    if (leftover) issues.push(`${leftover} streamed blocks left hidden`);
    const headings = [...document.querySelectorAll("h1")].filter((heading) => !heading.closest("[hidden]")).length;
    if (headings !== 1) issues.push(`${headings} page headings`);
    const unnamed = [...document.querySelectorAll("button, a[href], input:not([type=hidden]), select, textarea")].filter((element) => {
      const box = element.getBoundingClientRect();
      if (!box.width || element.closest("[hidden], [inert]")) return false;
      const name = (element.getAttribute("aria-label") || element.getAttribute("title") || element.textContent || element.value || element.getAttribute("placeholder") || "").trim();
      return !name && !(element.id && document.querySelector(`label[for="${element.id}"]`)) && !element.closest("label") && !element.getAttribute("aria-labelledby");
    });
    if (unnamed.length) issues.push(`${unnamed.length} controls with no name`);
    for (const element of document.querySelectorAll("[role=tablist], [role=toolbar], nav")) {
      if (element.getBoundingClientRect().width && element.scrollWidth > element.clientWidth + 2) {
        issues.push(`"${(element.getAttribute("aria-label") || element.getAttribute("role") || "nav").slice(0, 30)}" is cut off`);
      }
    }
    return { heading: document.querySelector("h1")?.innerText ?? "", issues };
  }, BAD.source);
  page.off("console", onConsole);
  page.off("pageerror", onPageError);
  page.off("response", onResponse);
  const expected404 = path === "/no-such-page" ? /status of 404/ : null;
  const all = [...found.issues, ...errors.filter((error) => !(expected404 && expected404.test(error)))];
  if (all.length) problems += 1;
  console.log(`${all.length ? "PROBLEM" : "ok     "} ${path.replaceAll(projectId, "{project}")} [${found.heading}]${all.length ? `\n          ${all.join("\n          ")}` : ""}`);
}
for (const line of skipped) console.log(`not walked ${line}`);
console.log(`\n${pages.length} pages at ${width}px wide: ${problems} with a problem; ${skipped.length} not walked.`);
await browser.close();
process.exit(problems ? 1 : 0);
