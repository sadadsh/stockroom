import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cadVariantApi,
  CadVariantApiError,
  type CadVariantDocument,
} from "./cadVariantClient";
import {
  installApiRequestAdapter,
  previewAdapter,
  type DesignScenario,
  type ScenarioFixture,
} from "../design-studio/requestAdapter";
import { PreviewMutationError } from "../design-studio/mutationGuard";

const DOCUMENT: CadVariantDocument = {
  partId: "part/1",
  inventories: [],
  pairs: [],
  supplementary: [],
};

const REVERIFIED_DOCUMENT: CadVariantDocument = {
  ...DOCUMENT,
  inventories: [
    {
      tool: "kicad",
      activeVariantId: "sha256:manifest",
      variants: [
        {
          id: "sha256:manifest",
          provider: "Ultra Librarian",
          format: "KiCad 10",
          artifacts: [{ kind: "symbol", fileName: "Part.kicad_sym" }],
          evidenceDigest: "sha256:manifest",
          verificationState: "reverified",
          trustRank: 0,
          trustLabel: "Preferred Source",
        },
      ],
    },
  ],
};

function scenarioWith(fixtures: readonly ScenarioFixture[]): DesignScenario {
  return {
    id: "components.cad-variants",
    title: "CAD Variants",
    area: "components",
    group: "Components",
    route: "components",
    fixtures,
    initialUi: {},
    expectedTargets: ["shell.root"],
    coverage: ["route:components"],
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("cadVariantApi", () => {
  it("resolves inventory from the active scenario without a live product read", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ...DOCUMENT, partId: "live" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const restore = installApiRequestAdapter(
      previewAdapter(
        scenarioWith([
          {
            method: "GET",
            path: "/api/library/parts/part%2F1/cad-variants",
            params: {},
            body: undefined,
            response: DOCUMENT,
          },
        ]),
      ),
    );

    try {
      await expect(cadVariantApi.inventory("part/1")).resolves.toEqual(DOCUMENT);
      expect(fetchMock).not.toHaveBeenCalled();
    } finally {
      restore();
    }
  });

  it("blocks pair activation before a live product mutation", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(DOCUMENT), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const restore = installApiRequestAdapter(previewAdapter(scenarioWith([])));

    try {
      await expect(
        cadVariantApi.activatePair("part/1", {
          kicadVariantId: "sha256:kicad-new",
          altiumVariantId: "sha256:altium-new",
          expectedActiveKicadVariantId: "sha256:kicad-old",
          expectedActiveAltiumVariantId: "sha256:altium-old",
        }),
      ).rejects.toBeInstanceOf(PreviewMutationError);
      expect(fetchMock).not.toHaveBeenCalled();
    } finally {
      restore();
    }
  });

  it("reads only the requested part through the authenticated API boundary", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(DOCUMENT), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(cadVariantApi.inventory("part/1")).resolves.toEqual(DOCUMENT);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/api/library/parts/part%2F1/cad-variants",
      {
        method: "GET",
        headers: {
          Accept: "application/json",
          Authorization: "Bearer test-token",
        },
      },
    );
  });

  it("preserves the reverified evidence state without a fabricated check count", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(REVERIFIED_DOCUMENT), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const result = await cadVariantApi.inventory("part/1");
    const variant = result.inventories[0]?.variants[0];

    expect(variant?.verificationState).toBe("reverified");
    expect(variant).not.toHaveProperty("validationChecks");
  });

  it("posts both expected pointers when atomically switching a validated pair", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(DOCUMENT), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await cadVariantApi.activatePair("part/1", {
      kicadVariantId: "sha256:kicad-new",
      altiumVariantId: "sha256:altium-new",
      expectedActiveKicadVariantId: "sha256:kicad-old",
      expectedActiveAltiumVariantId: "sha256:altium-old",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/api/library/parts/part%2F1/cad-variants/activate-pair",
      {
        method: "POST",
        headers: {
          Accept: "application/json",
          Authorization: "Bearer test-token",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          kicadVariantId: "sha256:kicad-new",
          altiumVariantId: "sha256:altium-new",
          expectedActiveKicadVariantId: "sha256:kicad-old",
          expectedActiveAltiumVariantId: "sha256:altium-old",
        }),
      },
    );
    expect("activate" in cadVariantApi).toBe(false);
  });

  it("preserves a stale-selection conflict as a typed 409", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "active variant changed" }), {
          status: 409,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const result = cadVariantApi.activatePair("p1", {
      kicadVariantId: "sha256:new",
      altiumVariantId: "sha256:new",
      expectedActiveKicadVariantId: null,
      expectedActiveAltiumVariantId: null,
    });

    await expect(result).rejects.toMatchObject({
      name: "CadVariantApiError",
      status: 409,
      message: "active variant changed",
    } satisfies Partial<CadVariantApiError>);
  });
});
