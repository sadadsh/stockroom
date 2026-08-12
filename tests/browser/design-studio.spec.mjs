import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

const repo = path.resolve(process.env.STOCKROOM_REPOSITORY_ROOT ?? process.cwd());
const evidenceRoot = path.resolve(
  process.env.STOCKROOM_DESIGN_STUDIO_EVIDENCE ??
    path.join(repo, ".work plans", "sdd", "2026-08-11-in-app-design-studio", "task-15-evidence", "browser"),
);
const registryPath = path.join(repo, "app", "frontend-dist", "design-studio-scenarios.json");
const playwrightCore = process.env.STOCKROOM_PLAYWRIGHT_CORE;
if (!playwrightCore) throw new Error("STOCKROOM_PLAYWRIGHT_CORE must name the locked Playwright core index.mjs.");
const { chromium } = await import(pathToFileURL(playwrightCore).href);

const matrix = [
  { name: "1366x872", width: 1366, height: 872, preset: "desktop-1366" },
  { name: "1600x1000", width: 1600, height: 1000, preset: "desktop-1600" },
  { name: "1920x1200", width: 1920, height: 1200, preset: "desktop-1920" },
];
const themes = ["dark", "light"];
const scenarioLimit = Number(process.env.STOCKROOM_BROWSER_SCENARIO_LIMIT ?? "0");

function safeName(value) {
  return value.replace(/[^a-zA-Z0-9._-]+/g, "-");
}

function startStockroom() {
  const bootstrapScript = String.raw`
import json, sys, time
from pathlib import Path
repo = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(repo / "app" / "backend"))
from stockroom.api.serve import build_context
from stockroom.host.run import run_windowed
from stockroom.store.machine_config import MachineConfig
from stockroom.store.onboarding import bootstrap_library
def open_window(base_url, token):
    print("STOCKROOM_BROWSER_BOOTSTRAP " + json.dumps({"baseUrl": base_url, "token": token}), flush=True)
    while True:
        time.sleep(30)
library = bootstrap_library(MachineConfig.load())
config = MachineConfig.load()
config.onboarded = True
config.save()
context = build_context(library, cold=True)
run_windowed(ctx=context, open_window=open_window)
`;
  const python = path.join(repo, ".venv", "Scripts", "python.exe");
  const serviceState = path.join(evidenceRoot, "service-state");
  const child = spawn(python, ["-c", bootstrapScript, repo, serviceState], {
    cwd: repo,
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  let stderr = "";
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk) => { stderr += chunk; });
  const ready = new Promise((resolve, reject) => {
    let stdout = "";
    const timeout = setTimeout(() => reject(new Error(`Stockroom browser host timed out.\n${stderr}`)), 60_000);
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
      for (const line of stdout.split(/\r?\n/)) {
        if (!line.startsWith("STOCKROOM_BROWSER_BOOTSTRAP ")) continue;
        clearTimeout(timeout);
        resolve(JSON.parse(line.slice("STOCKROOM_BROWSER_BOOTSTRAP ".length)));
      }
    });
    child.once("exit", (code) => {
      clearTimeout(timeout);
      reject(new Error(`Stockroom browser host exited ${code}.\n${stderr}`));
    });
  });
  return { child, ready, stderr: () => stderr };
}

async function stopStockroom(host) {
  if (host.child.exitCode !== null) return;
  await new Promise((resolve) => {
    const timeout = setTimeout(resolve, 5_000);
    host.child.once("exit", () => {
      clearTimeout(timeout);
      resolve();
    });
    host.child.kill();
  });
}

function createStudio(page, baseUrl) {
  const productEffects = [];
  let mark = 0;
  page.on("request", (request) => {
    const url = new URL(request.url());
    const method = request.method().toUpperCase();
    const external = url.origin !== new URL(baseUrl).origin;
    const personalAutosave = url.pathname === "/api/design-studio/personal";
    const productApi = url.origin === new URL(baseUrl).origin &&
      url.pathname.startsWith("/api/") && !personalAutosave;
    if (external || productApi) {
      productEffects.push({ method, url: request.url(), external });
    }
  });

  return {
    async open(id) {
      if (!(await page.locator('[aria-label="Design Studio Breadcrumb"]').count())) {
        await page.locator("[data-design-studio-entry]").click();
        await page.locator('[aria-label="Design Studio Breadcrumb"]').waitFor({ state: "visible" });
      }
      mark = productEffects.length;
      await page.locator(`[data-scenario-catalog-id="${id}"]`).click();
      await page.locator(`[data-scenario-id="${id}"]`).waitFor({ state: "attached" });
    },
    liveProductRequests() {
      return productEffects.slice(mark);
    },
    async setTheme(theme) {
      const root = page.locator("html");
      if ((await root.getAttribute("data-theme")) !== theme) {
        await page.getByTitle("Switch Preview Theme").click();
      }
      await page.locator(`html[data-theme="${theme}"]`).waitFor({ state: "attached" });
    },
    async setViewport(viewport) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.getByLabel("Viewport", { exact: true }).selectOption(viewport.preset);
    },
    async close() {
      if (await page.locator('[aria-label="Design Studio Breadcrumb"]').count()) {
        await page.getByRole("button", { name: "Close Design Studio" }).click();
      }
    },
  };
}

async function assertVisibleTargets(page, scenario) {
  await page.locator(`[data-scenario-id="${scenario.id}"]`).waitFor({ state: "attached" });
  for (const target of scenario.expectedTargets) {
    const locator = page.locator(`[data-dev-id="${target}"], [data-dev-role="${target}"]`).first();
    await locator.waitFor({ state: "visible", timeout: 15_000 });
  }
}

async function representativeClickThrough(page, studio) {
  await studio.open("components.full-data");
  const modes = page.getByLabel("Studio Mode");
  await modes.getByRole("button", { name: "Inspect", exact: true }).click();
  await page.locator('[data-dev-id="shell.root"]').click({ position: { x: 10, y: 10 } });
  for (const domain of ["Box", "Text", "Icon", "Arrangement", "Behavior", "States", "Advanced"]) {
    const button = page.getByRole("button", { name: domain, exact: true });
    if (await button.count()) await button.first().click();
  }
  await modes.getByRole("button", { name: "Arrange", exact: true }).click();
  await modes.getByRole("button", { name: "Browse", exact: true }).click();
  await page.getByRole("button", { name: "Hide Screens And States", exact: true }).click();
  await page.getByRole("button", { name: "Show Screens And States", exact: true }).click();
  await page.getByRole("button", { name: "Hide Inspector", exact: true }).click();
  await page.getByRole("button", { name: "Show Inspector", exact: true }).click();
  await page.screenshot({ path: path.join(evidenceRoot, "representative-click-through.png"), fullPage: false });
}

await mkdir(evidenceRoot, { recursive: true });
const registry = JSON.parse(await readFile(registryPath, "utf8"));
assert.equal(registry.schemaVersion, 1);
assert.ok(Array.isArray(registry.scenarios) && registry.scenarios.length > 0);

let host = startStockroom();
let browser;
let context;
try {
  const { baseUrl } = await host.ready;
  browser = await chromium.launch({ headless: true, args: ["--force-color-profile=srgb"] });
  context = await browser.newContext({
    viewport: { width: 1366, height: 872 },
    reducedMotion: "reduce",
    colorScheme: "dark",
  });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on("pageerror", (error) => consoleErrors.push(error.stack ?? error.message));
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  try {
    await page.locator("[data-design-studio-entry]").waitFor({ state: "visible", timeout: 30_000 });
  } catch (error) {
    const diagnostic = {
      url: page.url(),
      title: await page.title(),
      text: (await page.locator("body").innerText()).slice(0, 4000),
      html: (await page.locator("body").innerHTML()).slice(0, 4000),
      consoleErrors,
    };
    await page.screenshot({ path: path.join(evidenceRoot, "boot-failure.png"), fullPage: false });
    throw new Error(`Stockroom browser boot did not expose Design Studio:\n${JSON.stringify(diagnostic, null, 2)}`, { cause: error });
  }
  const studio = createStudio(page, baseUrl);

  const scenarios = scenarioLimit > 0 ? registry.scenarios.slice(0, scenarioLimit) : registry.scenarios;
  for (const scenario of scenarios) {
    await studio.open(scenario.id);
    for (const viewport of matrix) {
      await studio.setViewport(viewport);
      for (const theme of themes) {
        await studio.setTheme(theme);
        await assertVisibleTargets(page, scenario);
        if (scenario.id !== "global.real-data") {
          assert.deepEqual(studio.liveProductRequests(), [], `${scenario.id} produced a live product effect`);
        }
        if (process.env.STOCKROOM_BROWSER_SKIP_SCREENSHOTS !== "1") {
          await page.screenshot({
            path: path.join(evidenceRoot, `${safeName(scenario.id)}--${theme}--${viewport.name}.png`),
            fullPage: false,
          });
        }
      }
    }
    process.stdout.write(`PASS ${scenario.id}\n`);
  }

  await representativeClickThrough(page, studio);
  assert.deepEqual(consoleErrors, [], `Browser console errors:\n${consoleErrors.join("\n")}`);

  // Prove the debounced personal design survives a real service stop/start, using the same
  // task-owned machine-config root and an edit made through the product UI.
  await studio.setTheme("dark");
  await page.getByRole("tab", { name: "Tokens", exact: true }).click();
  const showAll = page.getByRole("button", { name: "Show All", exact: true });
  if (await showAll.count()) await showAll.click();
  const persistedAccent = "#c1c4c8";
  const saveResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/design-studio/personal" &&
      response.request().method() === "PUT" && response.ok();
  });
  await page.getByLabel("Accent value", { exact: true }).fill(persistedAccent);
  const saved = await (await saveResponse).json();
  assert.equal(saved.document.base.tokens.root["--c-acc"], persistedAccent);
  await writeFile(
    path.join(evidenceRoot, "autosave-before-restart.json"),
    JSON.stringify({ revision: saved.revision, persistedAccent }, null, 2) + "\n",
    "utf8",
  );

  await studio.close();
  await context.close();
  context = undefined;
  await browser.close();
  browser = undefined;
  await stopStockroom(host);

  host = startStockroom();
  const restarted = await host.ready;
  browser = await chromium.launch({ headless: true, args: ["--force-color-profile=srgb"] });
  context = await browser.newContext({
    viewport: { width: 1366, height: 872 },
    reducedMotion: "reduce",
    colorScheme: "dark",
  });
  const restartedPage = await context.newPage();
  await restartedPage.goto(restarted.baseUrl, { waitUntil: "networkidle" });
  await restartedPage.locator("[data-design-studio-entry]").click();
  await restartedPage.locator('[aria-label="Design Studio Breadcrumb"]').waitFor({ state: "visible" });
  if ((await restartedPage.locator("html").getAttribute("data-theme")) !== "dark") {
    await restartedPage.getByTitle("Switch Preview Theme").click();
  }
  const restoredAccent = restartedPage.getByLabel("Accent value", { exact: true });
  await restoredAccent.waitFor({ state: "visible" });
  await restartedPage.waitForFunction(
    ({ label, value }) => document.querySelector(`input[aria-label="${label}"]`)?.value === value,
    { label: "Accent value", value: persistedAccent },
  );
  assert.equal(await restoredAccent.inputValue(), persistedAccent);
  await restartedPage.screenshot({ path: path.join(evidenceRoot, "autosave-after-restart.png"), fullPage: false });
  await writeFile(
    path.join(evidenceRoot, "autosave-after-restart.json"),
    JSON.stringify({ persistedAccent, restoredAccent: await restoredAccent.inputValue() }, null, 2) + "\n",
    "utf8",
  );
  await context.close();
  context = undefined;
  process.stdout.write(`PASS Design Studio browser matrix: ${scenarios.length} scenarios x 2 themes x 3 viewports\n`);
  process.stdout.write("PASS personal design autosave across service restart\n");
} finally {
  if (context) await context.close();
  if (browser) await browser.close();
  await stopStockroom(host);
}
