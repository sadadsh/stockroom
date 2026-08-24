import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

const repo = path.resolve(process.env.STOCKROOM_REPOSITORY_ROOT ?? process.cwd());
const evidenceRoot = path.resolve(
  process.env.STOCKROOM_DESIGN_STUDIO_EVIDENCE ??
    path.join(repo, "work", "Design Studio Evidence", "browser"),
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
const scenarioIds = String(process.env.STOCKROOM_BROWSER_SCENARIO_ID ?? "")
  .split(",")
  .map((id) => id.trim())
  .filter(Boolean);

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
from stockroom.api.routers import onboarding as onboarding_router
from stockroom.eda.primary_policy import PrimaryEdaPolicy
from stockroom.host.run import run_windowed
from stockroom.store import guided_setup
from stockroom.store.machine_config import MachineConfig
from stockroom.store.onboarding import bootstrap_library, complete_onboarding
from stockroom.vcs.repo import GitRepo
def open_window(base_url, token):
    print("STOCKROOM_BROWSER_BOOTSTRAP " + json.dumps({"baseUrl": base_url, "token": token}), flush=True)
    while True:
        time.sleep(30)
config = MachineConfig.load()
library = bootstrap_library(config)
PrimaryEdaPolicy(config).request_switch("kicad")
repo = GitRepo(library)
remote = "https://github.com/stockroom-design-studio/browser-acceptance.git"
if not repo.remote_url("origin"):
    repo.add_remote("origin", remote)
guided_setup.record_repository(
    config,
    owner="stockroom-design-studio",
    name="browser-acceptance",
    visibility="private",
    url=remote,
)
guided_setup.record_tool_connection(config, tool="kicad", receipt={"verified": True})
guided_setup.record_source_decision(config, skipped=True)
complete_onboarding(config)
guided_setup.record_completion(config)

def browser_github_status(*args, **kwargs):
    return {
        "available": True,
        "version": "browser-acceptance",
        "authenticated": True,
        "online": True,
        "viewer": {"login": "stockroom-design-studio", "name": "Design Studio Browser"},
        "owners": [{"login": "stockroom-design-studio", "kind": "user"}],
        "verified_repository": {
            "owner": "stockroom-design-studio",
            "name": "browser-acceptance",
            "url": remote,
            "visibility": "private",
            "permission": "admin",
            "writable": True,
        },
    }

def browser_tool_connection(ctx):
    return {
        "tool": "kicad",
        "installed": True,
        "connected": True,
        "restart_required": False,
        "detail": "KiCad is connected for this disposable browser acceptance run.",
    }

onboarding_router._github_status = browser_github_status
guided_setup.current_tool_connection = browser_tool_connection
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
  if (process.platform === "win32") {
    await new Promise((resolve) => {
      const killer = spawn("taskkill", ["/PID", String(host.child.pid), "/T", "/F"], {
        stdio: "ignore",
        windowsHide: true,
      });
      killer.once("exit", resolve);
      killer.once("error", resolve);
    });
    return;
  }
  await new Promise((resolve) => {
    const timeout = setTimeout(resolve, 5_000);
    host.child.once("exit", () => {
      clearTimeout(timeout);
      resolve();
    });
    host.child.kill();
  });
}

async function openBootstrappedStockroom(page, baseUrl) {
  const onboardingResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/onboarding" && response.request().method() === "GET" && response.ok();
  });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  const onboarding = await (await onboardingResponse).json();
  assert.equal(onboarding.primary_eda, "kicad", "browser acceptance must confirm one Primary CAD Tool");
  assert.equal(onboarding.onboarded, true, "browser acceptance must explicitly complete Guided Setup");
  assert.equal(onboarding.guided_setup.ready, true, "browser acceptance must start from authoritative Ready state");
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
      const scenarioButton = page.locator(`[data-scenario-catalog-id="${id}"]`);
      if (!(await scenarioButton.isVisible())) {
        await page.getByLabel("Design Studio Drawers").getByRole("button", { name: "Screens", exact: true }).click();
      }
      await page.getByRole("searchbox", { name: "Search Screens And States" }).fill(id);
      await scenarioButton.click();
      await page.locator(`[data-scenario-id="${id}"]`).waitFor({ state: "attached" });
      await page.getByRole("searchbox", { name: "Search Screens And States" }).fill("");
      const screensToggle = page.getByLabel("Design Studio Drawers").getByRole("button", { name: "Screens", exact: true });
      if ((await screensToggle.getAttribute("aria-pressed")) === "true") await screensToggle.click();
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
      await page.getByRole("button", { name: "View", exact: true }).click();
      await page.getByLabel("Viewport", { exact: true }).selectOption(viewport.preset);
      await page.getByRole("button", { name: "View", exact: true }).click();
    },
    async close() {
      if (await page.locator('[aria-label="Design Studio Breadcrumb"]').count()) {
        await page.getByRole("button", { name: "Exit", exact: true }).click();
      }
    },
  };
}

async function assertVisibleTargets(page, scenario) {
  const root = page.locator(`[data-scenario-id="${scenario.id}"]`);
  await root.waitFor({ state: "attached" });
  for (const target of scenario.expectedTargets) {
    const locator = page.locator(`[data-dev-id="${target}"], [data-dev-role="${target}"]`).first();
    try {
      await locator.waitFor({ state: "attached", timeout: 15_000 });
      const bounds = await locator.boundingBox();
      const minimumWidth = target === "settings.vendor-login-row" ? 320 : 1;
      assert.ok(
        bounds && bounds.width >= minimumWidth && bounds.height >= 1,
        `${scenario.id} target ${target} must occupy useful layout space (minimum ${minimumWidth}px wide)`,
      );
      await locator.waitFor({ state: "visible", timeout: 15_000 });
    } catch (error) {
      await page.screenshot({
        path: path.join(evidenceRoot, `${safeName(scenario.id)}--missing-${safeName(target)}.png`),
        fullPage: false,
      });
      const diagnostic = await page.evaluate((targetId) => {
        const matches = [...document.querySelectorAll(`[data-dev-id="${targetId}"], [data-dev-role="${targetId}"]`)];
        return {
          body: (document.body.innerText ?? "").slice(0, 2500),
          matches: matches.slice(0, 4).map((element) => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            const ancestors = [];
            let current = element.parentElement;
            while (current && ancestors.length < 8) {
              const currentRect = current.getBoundingClientRect();
              const currentStyle = getComputedStyle(current);
              ancestors.push({
                tag: current.tagName,
                className: current.className,
                devId: current.getAttribute("data-dev-id"),
                rect: [currentRect.x, currentRect.y, currentRect.width, currentRect.height],
                box: [currentStyle.width, currentStyle.minWidth, currentStyle.maxWidth],
                grid: [currentStyle.gridColumn, currentStyle.justifySelf, currentStyle.alignSelf],
                transform: currentStyle.transform,
                overflow: currentStyle.overflow,
              });
              current = current.parentElement;
            }
            return {
              display: style.display,
              visibility: style.visibility,
              opacity: style.opacity,
              transform: style.transform,
              transition: style.transition,
              animation: style.animation,
              rect: [rect.x, rect.y, rect.width, rect.height],
              client: [element.clientWidth, element.clientHeight],
              scroll: [element.scrollWidth, element.scrollHeight],
              ancestors,
              parent: element.parentElement?.outerHTML.slice(0, 800) ?? "",
            };
          }),
        };
      }, target);
      throw new Error(`Scenario ${scenario.id} did not expose ${target}:\n${JSON.stringify(diagnostic, null, 2)}`, { cause: error });
    }
  }
  let previous = "";
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const product = page.locator("[data-design-product-root]");
    const targetMarkup = await Promise.all(scenario.expectedTargets.map(async (target) =>
      page.locator(`[data-dev-id="${target}"], [data-dev-role="${target}"]`).first().evaluate((element) => element.outerHTML),
    ));
    const current = [`theme:${await page.locator("html").getAttribute("data-theme") ?? ""}`, await product.innerHTML(), ...targetMarkup].join("\n").replace(/\s+/g, " ").trim();
    if (current === previous) return current;
    previous = current;
    await page.waitForTimeout(100);
  }
  return previous;
}

async function representativeClickThrough(page, studio) {
  async function exerciseControl(control) {
    await control.focus();
    await page.locator("[data-design-product-root]").waitFor({ state: "visible" });
    await control.press("ArrowRight");
    await page.getByRole("button", { name: "Undo", exact: true }).waitFor({ state: "visible" });
    assert.equal(await page.getByRole("button", { name: "Undo", exact: true }).isEnabled(), true);
    await page.getByRole("button", { name: "Undo", exact: true }).click();
  }
  await studio.open("components.full-data");
  const modes = page.getByLabel("Studio Mode");
  await modes.getByRole("button", { name: "Edit", exact: true }).click();
  await page.locator('[data-dev-id="shell.root"]').click({ position: { x: 10, y: 10 } });
  await page.screenshot({ path: path.join(evidenceRoot, "representative-edit.png"), fullPage: false });
  await page.locator('[data-design-product-root] [data-icon-id="nav.components"]').first().click();
  await page.getByRole("button", { name: "View", exact: true }).click();
  const grid = page.getByRole("button", { name: "Grid", exact: true });
  if ((await grid.getAttribute("aria-pressed")) !== "true") await grid.click();
  const snap = page.getByRole("button", { name: "Snap", exact: true });
  if ((await snap.getAttribute("aria-pressed")) !== "true") await snap.click();
  await page.getByLabel("Grid And Snap Size Exact", { exact: true }).fill("12");
  await page.getByRole("button", { name: "View", exact: true }).click();
  await page.locator('[aria-label="Stockroom Preview"][data-grid-size="12"][data-snap="on"]').waitFor({ state: "visible" });
  await exerciseControl(page.getByRole("button", { name: /^Move / }).first());
  await exerciseControl(page.getByRole("button", { name: /^Resize .* East$/ }).first());
  await page.getByRole("button", { name: /^More actions for / }).click();
  await exerciseControl(page.getByRole("button", { name: /^Rotate / }).first());
  await page.getByRole("button", { name: "Content", exact: true }).click();
  await page.getByRole("button", { name: "Choose Icon", exact: true }).first().click();
  await page.getByRole("dialog", { name: "Choose Icon" }).waitFor({ state: "visible" });
  await page.getByRole("searchbox", { name: "Search Icon Catalog" }).waitFor({ state: "visible" });
  await page.getByRole("option", { name: "Lucide", exact: true }).waitFor({ state: "attached", timeout: 30_000 });
  await page.screenshot({ path: path.join(evidenceRoot, "representative-icon-library.png"), fullPage: false });
  await page.keyboard.press("Escape");
  for (const domain of ["Quick", "Arrangement", "Appearance", "Content", "States", "Advanced"]) {
    const button = page.getByRole("button", { name: domain, exact: true });
    if (await button.count()) await button.first().click();
  }
  await modes.getByRole("button", { name: "Preview", exact: true }).click();
  const drawers = page.getByLabel("Design Studio Drawers");
  await drawers.getByRole("button", { name: "Screens", exact: true }).click();
  await drawers.getByRole("button", { name: "Screens", exact: true }).click();
  await drawers.getByRole("button", { name: "Layers", exact: true }).click();
  await drawers.getByRole("button", { name: "Layers", exact: true }).click();
  await page.screenshot({ path: path.join(evidenceRoot, "representative-click-through.png"), fullPage: false });
}

async function exactEditingAndExport(page, studio) {
  await studio.open("components.full-data");
  await page.getByLabel("Studio Mode").getByRole("button", { name: "Edit", exact: true }).click();

  const drawers = page.getByLabel("Design Studio Drawers");
  await drawers.getByRole("button", { name: "Layers", exact: true }).click();
  const sourceRows = page.locator('button[title="component-browser.source-state"]');
  await sourceRows.first().waitFor({ state: "visible", timeout: 10_000 });
  assert.ok(await sourceRows.count() >= 1, "Layers must expose the populated provider row.");
  assert.ok((await sourceRows.evaluateAll((rows) => rows.every((row) => !row.hasAttribute("disabled")))));
  await sourceRows.first().click();
  await drawers.getByRole("button", { name: "Layers", exact: true }).click();

  const product = page.locator("[data-design-product-root]");
  const digikey = product.locator('[data-design-key="digikey"] span').filter({ hasText: /^DigiKey$/ }).first();
  await digikey.dispatchEvent("click");
  await page.getByRole("button", { name: "Content", exact: true }).click();
  const textContent = page.getByLabel("Text Content", { exact: true });
  await textContent.waitFor({ state: "visible" });
  assert.equal(await textContent.inputValue(), "DigiKey");
  const providerCount = async (label) => product.locator("span").filter({ hasText: new RegExp(`^${label}$`) }).count();
  const digikeyCount = await providerCount("DigiKey");
  const mouserCount = await providerCount("Mouser");
  await textContent.fill("");
  await page.waitForFunction((expected) => (
    [...document.querySelectorAll("[data-design-product-root] span")]
      .filter((element) => element.textContent === "DigiKey").length === expected
  ), digikeyCount - 1);
  assert.equal(await providerCount("Mouser"), mouserCount, "Editing DigiKey must not change Mouser.");
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await page.waitForFunction((expected) => (
    [...document.querySelectorAll("[data-design-product-root] span")]
      .filter((element) => element.textContent === "DigiKey").length === expected
  ), digikeyCount);

  await studio.open("global.real-data");
  await page.getByRole("button", { name: "View", exact: true }).click();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export Design", exact: true }).click();
  const download = await downloadPromise;
  const downloadPath = await download.path();
  assert.ok(downloadPath, "Export Design must create a download.");
  const handoff = JSON.parse(await readFile(downloadPath, "utf8"));
  assert.equal(handoff.schema, "stockroom-design-handoff/1");
  assert.equal(handoff.activeScenarioId, null);
  assert.equal(handoff.document.schemaVersion, 2);
  assert.ok(handoff.instructions.includes("ChatGPT"));
  process.stdout.write("PASS exact provider editing, populated Layers, and design handoff export\n");
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
  await openBootstrappedStockroom(page, baseUrl);
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
  const renderedStates = new Map();

  const selectedScenarioIds = new Set(scenarioIds);
  const selectedScenarios = scenarioIds.length
    ? registry.scenarios.filter((scenario) => selectedScenarioIds.has(scenario.id))
    : registry.scenarios;
  if (scenarioIds.length) {
    assert.equal(
      selectedScenarios.length,
      selectedScenarioIds.size,
      `Unknown Design Studio scenario: ${scenarioIds.filter((id) => !selectedScenarios.some((scenario) => scenario.id === id)).join(", ")}`,
    );
  }
  const scenarios = scenarioLimit > 0 ? selectedScenarios.slice(0, scenarioLimit) : selectedScenarios;
  for (const scenario of scenarios) {
    await studio.open(scenario.id);
    renderedStates.set(scenario.id, await assertVisibleTargets(page, scenario));
    for (const viewport of matrix) {
      await studio.setViewport(viewport);
      for (const theme of themes) {
        await studio.setTheme(theme);
        const renderedState = await assertVisibleTargets(page, scenario);
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

  const stateOwners = new Map();
  for (const [id, state] of renderedStates) {
    stateOwners.set(state, [...(stateOwners.get(state) ?? []), id]);
  }
  const duplicateStates = Array.from(stateOwners.values()).filter((ids) => ids.length > 1);
  assert.deepEqual(duplicateStates, [], "Every shipped case must render distinct product DOM.");

  await representativeClickThrough(page, studio);
  await exactEditingAndExport(page, studio);
  assert.deepEqual(consoleErrors, [], `Browser console errors:\n${consoleErrors.join("\n")}`);

  // Prove the debounced personal design survives a real service stop/start, using the same
  // task-owned machine-config root and an edit made through the product UI.
  await studio.open("global.real-data");
  await studio.setTheme("dark");
  await page.getByRole("button", { name: "View", exact: true }).click();
  await page.getByRole("button", { name: "Developer Tools", exact: true }).click();
  await page.getByRole("tab", { name: "Tokens", exact: true }).click();
  const showAll = page.getByRole("button", { name: "Show All", exact: true });
  if (await showAll.count()) await showAll.click();
  const accentInput = page.getByLabel("Accent value", { exact: true });
  const persistedAccent = (await accentInput.inputValue()).toLowerCase() === "#c1c4c8"
    ? "#c2c5c9"
    : "#c1c4c8";
  const saveResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/design-studio/personal" &&
      response.request().method() === "PUT" && response.ok();
  });
  await accentInput.fill(persistedAccent);
  const saved = await (await saveResponse).json();
  assert.equal(saved.document.variations["full-data"].patch.tokens.root["--c-acc"], persistedAccent);
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
  await restartedPage.getByRole("button", { name: "View", exact: true }).click();
  await restartedPage.getByRole("button", { name: "Developer Tools", exact: true }).click();
  await restartedPage.getByRole("tab", { name: "Tokens", exact: true }).click();
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
