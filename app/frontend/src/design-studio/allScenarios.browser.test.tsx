import { describe, expect, it } from "vitest";
import { bootstrapScenarioRegistry } from "./scenarios";
import { mountScenario } from "./scenarios/testHarness";

/**
 * Browser-floor coverage over the one production scenario registry. The external Playwright
 * matrix consumes the JSON build projection of this same registry; this jsdom pass gives each
 * production component mount a fast, diagnostic RED before the longer real-browser run.
 */
describe("all production Design Studio scenarios", () => {
  for (const scenario of bootstrapScenarioRegistry.scenarios) {
    it(`renders ${scenario.id} with its case identity and expected targets`, async () => {
      const mounted = await mountScenario(scenario.id);

      expect(
        document.querySelector(`[data-scenario-id="${scenario.id}"]`),
      ).toBeInTheDocument();
      for (const target of scenario.expectedTargets) {
        expect(
          document.querySelector(`[data-dev-id="${target}"], [data-dev-role="${target}"]`),
          target,
        ).toBeInTheDocument();
      }
      const liveMutations = mounted.liveRequest.mock.calls.filter(([, init]) =>
        !new Set(["GET", "HEAD", "OPTIONS"]).has(String(init?.method ?? "GET").toUpperCase()),
      );
      expect(liveMutations).toEqual([]);
      if (scenario.id !== "global.real-data") expect(mounted.liveRequest).not.toHaveBeenCalled();
    });
  }
});
