import type { DesignScenario, ScenarioFixture, ScenarioUiState } from "../scenario";
import { settingsReadFixtures, SETTINGS_ONBOARDING } from "../fixtures/settingsFixtures";
import { guidedSetupAt } from "../fixtures/onboardingFixtures";

export const globalScenarioIds = [
  "global.real-data", "global.onboarding.open", "global.onboarding.create", "global.onboarding.clone",
  "global.onboarding.error", "global.onboarding.create-error", "global.onboarding.clone-error",
  "global.rail.expanded", "global.rail.collapsed", "global.theme.dark", "global.theme.light",
  "global.update.current", "global.update.available", "global.update.updating", "global.update.error",
  "global.add-parts.empty", "global.add-parts.validating", "global.add-parts.exact", "global.add-parts.mismatch", "global.add-parts.duplicate", "global.add-parts.failure",
  "global.search.initial", "global.search.filtered", "global.search.empty", "global.search.error",
  "global.confirmation.neutral", "global.confirmation.destructive",
  "global.toast.neutral", "global.toast.success", "global.toast.error",
  "global.capture.active", "global.capture.backgrounded", "global.capture.complete", "global.capture.error",
  "global.offline", "global.service-error", "global.stale",
  "global.source-promotion.unavailable", "global.source-promotion.ready", "global.source-promotion.blocked", "global.source-promotion.success", "global.source-promotion.failure",
] as const;

type GlobalScenarioId = typeof globalScenarioIds[number];

const firstRun = {
  ...SETTINGS_ONBOARDING,
  onboarded: false,
  first_run: true,
  libraries: [],
  profiles: [],
  guided_setup: guidedSetupAt("catalog_repository", {
    ready: false,
    repository_ready: false,
    repository: null,
  }),
};
const firstRunSignedOut = {
  ...firstRun,
  guided_setup: guidedSetupAt("catalog_repository", {
    ready: false,
    repository_ready: false,
    repository: null,
    github: {
      available: true,
      version: "2.80.0",
      authenticated: false,
      online: true,
      viewer: null,
      owners: [],
    },
  }),
};
const searchRows = [{ id: "fixture-part", display_name: "LM358", category: "Integrated Circuits", mpn: "LM358DR", manufacturer: "Texas Instruments", is_complete: true, missing: [], specs: { channels: 2 }, stock: 1200, unit_price: 0.42, currency: "USD" }];

function fixture(method: string, path: string, response: unknown, behavior?: ScenarioFixture["behavior"]): ScenarioFixture {
  return { method, path, params: {}, body: undefined, response, behavior };
}

function globalFixtures(id: GlobalScenarioId): ScenarioFixture[] {
  if (id === "global.real-data") return [];
  const isOnboarding = id.startsWith("global.onboarding.");
  const updateState = id.endsWith("update.available") ? "update_available"
    : id.endsWith("update.updating") ? "updating" : id === "global.offline" ? "offline"
      : id === "global.stale" ? "restart_required" : "up_to_date";
  const reads: ScenarioFixture[] = [];
  for (const item of settingsReadFixtures({ updateState })) {
    if (isOnboarding && item.path === "/api/onboarding") continue;
    reads.push(id === "global.update.error" && item.path === "/api/update/check"
      ? { ...item, behavior: { state: "error" as const, status: 503, message: "Update check unavailable." } }
      : item);
  }
  if (isOnboarding) reads.unshift(
    fixture("GET", "/api/onboarding", id === "global.onboarding.open" ? firstRunSignedOut : firstRun),
    fixture("GET", "/api/onboarding/github/repositories/engineer", {
      repositories: [{
        owner: "engineer",
        name: "stockroom-catalog",
        url: "https://github.com/engineer/stockroom-catalog",
        visibility: "private",
        permission: "admin",
        writable: true,
      }],
    }),
  );
  if (id.startsWith("global.search.")) {
    const query = id.endsWith(".initial") ? "" : id.endsWith(".filtered") ? "LM358" : id.endsWith(".empty") ? "missing-part" : "LM358";
    const error = id.endsWith(".error") ? { state: "error" as const, status: 503, message: "Search unavailable." } : undefined;
    const rows = id.endsWith(".empty") ? [] : searchRows;
    const params = query ? { q: query, ...(id.endsWith(".filtered") ? { category: "Integrated Circuits" } : {}) } : {};
    reads.push(
      { ...fixture("GET", "/api/library/search", { parts: rows, count: rows.length }, error), params },
      { ...fixture("GET", "/api/library/facets/parametric", { category: id.endsWith(".filtered") ? "Integrated Circuits" : null, facets: [], total: rows.length }), params },
    );
  }
  return reads;
}

function uiFor(id: GlobalScenarioId): Readonly<ScenarioUiState> {
  if (id.startsWith("global.onboarding.")) {
    const mode = id.includes("clone") ? "clone" : id.includes("create") ? "create" : "open";
    const setupError = !id.includes("error")
      ? undefined
      : id.includes("create-error")
        ? "Could not create the catalog."
        : id.includes("clone-error")
          ? "Could not connect the catalog."
          : "Could not prepare the catalog.";
    return { onboarding: { mode, setupError } };
  }
  if (id === "global.rail.collapsed" || id === "global.rail.expanded") return { railState: id.endsWith("collapsed") ? "collapsed" : "expanded" };
  if (id === "global.theme.dark" || id === "global.theme.light") return { theme: id.endsWith("light") ? "light" : "dark" };
  if (id.startsWith("global.add-parts.")) return { addParts: { state: id.split(".").slice(-1)[0] as NonNullable<ScenarioUiState["addParts"]>["state"] } };
  if (id.startsWith("global.search.")) return { search: { open: true, query: id.endsWith(".initial") ? "" : id.endsWith(".filtered") ? "LM358" : id.endsWith(".empty") ? "missing-part" : "LM358", category: id.endsWith(".filtered") ? "Integrated Circuits" : undefined } };
  if (id === "global.confirmation.neutral" || id === "global.confirmation.destructive") return { confirmation: { danger: id.endsWith("destructive") } };
  if (id.startsWith("global.toast.")) return { toast: { message: `Fixture ${id.split(".").slice(-1)[0]} notification.`, tone: id.endsWith("success") ? "ok" : id.endsWith("error") ? "err" : "neutral" } };
  if (id.startsWith("global.capture.")) return { capture: { status: id.endsWith("complete") ? "done" : id.endsWith("error") ? "error" : id.endsWith("active") ? "receiving" : "resolving", backgrounded: true } };
  if (id === "global.service-error") return { service: { error: "Service unavailable" } };
  if (id.startsWith("global.source-promotion.")) return { sourcePromotion: { state: id.split(".").slice(-1)[0] as NonNullable<ScenarioUiState["sourcePromotion"]>["state"] } };
  return {};
}

function targetFor(id: GlobalScenarioId): string {
  if (id.startsWith("global.onboarding.")) return "onboarding.gate";
  if (id.startsWith("global.add-parts.")) return "addpart.root";
  if (id.startsWith("global.search.")) return "search.root";
  if (id.startsWith("global.confirmation.")) return "confirm.root";
  if (id.startsWith("global.toast.")) return "toast.status";
  if (id.startsWith("global.capture.") && !id.endsWith("active")) return "capture.status";
  if (id === "global.service-error") return "components.list-unreachable";
  if (id.startsWith("global.theme.")) return "rail.theme-toggle";
  if (id === "global.update.current" || id === "global.update.error") return "shell.statusbar";
  if (id.includes("update.available") || id.includes("update.updating")) return "rail.update";
  return "shell.root";
}

function scenario(id: GlobalScenarioId): DesignScenario {
  return {
    id, title: id === "global.real-data" ? "Real Data" : id.split(".").slice(1).join(" ").replace(/(^|[ -])\w/g, (letter) => letter.toUpperCase()), area: "global", group: "Global", route: "components",
    fixtures: globalFixtures(id), initialUi: uiFor(id), expectedTargets: [targetFor(id)],
  };
}

export const globalScenarios: readonly DesignScenario[] = globalScenarioIds.map(scenario);
