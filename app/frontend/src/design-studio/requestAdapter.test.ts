import { api } from "../api/client";
import {
  MissingScenarioFixtureError,
  installApiRequestAdapter,
  previewAdapter,
  type DesignScenario,
  type ScenarioFixture,
} from "./requestAdapter";
import { PreviewMutationError } from "./mutationGuard";

function scenarioWith(fixtures: readonly ScenarioFixture[]): DesignScenario {
  return {
    id: "components.full",
    title: "Components Full Data",
    area: "components",
    group: "Components",
    route: "components",
    fixtures,
    initialUi: {},
    expectedTargets: ["shell.root"],
  };
}

describe("preview request adapter", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("never falls through to live data while a scenario is active", async () => {
    const live = vi.fn();
    const adapter = previewAdapter(scenarioWith([]));

    await expect(
      adapter.handle(
        { method: "GET", path: "/api/parts", params: {}, body: undefined },
        live,
      ),
    ).rejects.toBeInstanceOf(MissingScenarioFixtureError);
    expect(live).not.toHaveBeenCalled();
  });

  it("resolves an exact typed fixture before considering a live allowlist", async () => {
    const live = vi.fn().mockResolvedValue({ revision: "live", document: null });
    const fixture = { revision: "fixture", document: null };
    const adapter = previewAdapter(
      scenarioWith([
        {
          method: "GET",
          path: "/api/design-studio/personal",
          params: {},
          body: undefined,
          response: fixture,
        },
      ]),
    );

    await expect(
      adapter.handle(
        {
          method: "GET",
          path: "/api/design-studio/personal",
          params: {},
          body: undefined,
        },
        live,
      ),
    ).resolves.toEqual(fixture);
    expect(live).not.toHaveBeenCalled();
  });

  it("blocks a product mutation even when a scenario declares a local outcome", async () => {
    const live = vi.fn();
    const adapter = previewAdapter(
      scenarioWith([
        {
          method: "POST",
          path: "/api/parts",
          params: {},
          body: { id: "fixture-part" },
          response: { saved: false, id: "fixture-part" },
        },
      ]),
    );

    await expect(
      adapter.handle(
        {
          method: "POST",
          path: "/api/parts",
          params: {},
          body: { id: "fixture-part" },
        },
        live,
      ),
    ).rejects.toBeInstanceOf(PreviewMutationError);
    expect(live).not.toHaveBeenCalled();
  });

  it("allows personal persistence but keeps source status and writes off the live seam", async () => {
    const live = vi.fn().mockResolvedValue({ ok: true });
    const adapter = previewAdapter(scenarioWith([]));

    await expect(
      adapter.handle(
        {
          method: "PUT",
          path: "/api/design-studio/personal",
          params: {},
          body: { document: {} },
        },
        live,
      ),
    ).resolves.toEqual({ ok: true });
    await expect(
      adapter.handle(
        { method: "GET", path: "/api/dev/status", params: {}, body: undefined },
        live,
      ),
    ).rejects.toBeInstanceOf(MissingScenarioFixtureError);

    for (const path of ["/api/dev/save", "/api/dev/publish"]) {
      await expect(
        adapter.handle({ method: "POST", path, params: {}, body: {} }, live),
      ).rejects.toBeInstanceOf(PreviewMutationError);
    }
    expect(live).toHaveBeenCalledOnce();
  });

  it("routes the API client through the installed adapter and restores the exact live adapter", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ parts: [{ id: "live" }], count: 1 }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const restore = installApiRequestAdapter(
      previewAdapter(
        scenarioWith([
          {
            method: "GET",
            path: "/api/library/parts",
            params: {},
            body: undefined,
            response: { parts: [{ id: "fixture" }], count: 1 },
          },
        ]),
      ),
    );

    try {
      await expect(api.listParts({})).resolves.toEqual({
        parts: [{ id: "fixture" }],
        count: 1,
      });
      expect(fetchMock).not.toHaveBeenCalled();
    } finally {
      restore();
    }

    await expect(api.listParts({})).resolves.toEqual({
      parts: [{ id: "live" }],
      count: 1,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("routes binary API reads through the same fail-closed seam", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const fixtureBlob = new Blob(["<svg />"], { type: "image/svg+xml" });
    const restore = installApiRequestAdapter(
      previewAdapter(
        scenarioWith([
          {
            method: "GET",
            path: "/api/previews/symbol/lm358.svg",
            params: { bw: "true" },
            body: undefined,
            response: fixtureBlob,
          },
        ]),
      ),
    );

    try {
      await expect(api.previewSvg("symbol", "lm358")).resolves.toBe(fixtureBlob);
      expect(fetchMock).not.toHaveBeenCalled();
    } finally {
      restore();
    }
  });
});
