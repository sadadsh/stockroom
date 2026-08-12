import { cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { globalScenarios } from "./global";
import { mountScenario } from "./testHarness";

const GLOBAL_SCENARIO_INVENTORY = [
  "global.real-data",
  "global.onboarding.open",
  "global.onboarding.create",
  "global.onboarding.clone",
  "global.onboarding.error",
  "global.onboarding.create-error",
  "global.onboarding.clone-error",
  "global.about.open",
  "global.about.current",
  "global.about.update-available",
  "global.about.stale",
  "global.rail.expanded",
  "global.rail.collapsed",
  "global.theme.dark",
  "global.theme.light",
  "global.update.current",
  "global.update.available",
  "global.update.updating",
  "global.update.error",
  "global.add-parts.empty",
  "global.add-parts.validating",
  "global.add-parts.exact",
  "global.add-parts.mismatch",
  "global.add-parts.duplicate",
  "global.add-parts.failure",
  "global.search.initial",
  "global.search.filtered",
  "global.search.empty",
  "global.search.error",
  "global.confirmation.neutral",
  "global.confirmation.destructive",
  "global.toast.neutral",
  "global.toast.success",
  "global.toast.error",
  "global.capture.active",
  "global.capture.backgrounded",
  "global.capture.complete",
  "global.capture.error",
  "global.offline",
  "global.service-error",
  "global.stale",
  "global.source-promotion.unavailable",
  "global.source-promotion.ready",
  "global.source-promotion.blocked",
  "global.source-promotion.success",
  "global.source-promotion.failure",
] as const;

afterEach(cleanup);

describe("global Design Studio scenarios", () => {
  it("registers the complete literal global and modal inventory", () => {
    expect(globalScenarios.map((scenario) => scenario.id)).toEqual(GLOBAL_SCENARIO_INVENTORY);
  });

  it.each(GLOBAL_SCENARIO_INVENTORY.filter((id) => id !== "global.real-data"))(
    "mounts the production app for %s",
    async (id) => {
      const mounted = await mountScenario(id);
      expect(mounted.liveRequest).not.toHaveBeenCalled();
    },
  );

  it.each([
    ["global.onboarding.open", "onboarding.gate"],
    ["global.about.open", "about.root"],
    ["global.add-parts.empty", "addpart.root"],
    ["global.search.initial", "search.root"],
    ["global.toast.success", "toast.status"],
    ["global.capture.backgrounded", "capture.status"],
  ])("mounts %s through production global UI", async (id, target) => {
    const mounted = await mountScenario(id);
    expect(document.querySelector(`[data-dev-id="${target}"], [data-dev-role="${target}"]`)).toBeInTheDocument();
    expect(mounted.liveRequest).not.toHaveBeenCalled();
  });
});
