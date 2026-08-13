import { describe, expect, it, vi } from "vitest";
import type { DevWorkspaceStatus } from "../api/types";
import type { DesignDocument } from "./document";
import {
  PromotionValidationError,
  collectDesignIssues,
  promotionPlan,
  promotionTransactionPlan,
  runPersonalDesignPromotion,
} from "./promotion";

function fixtureDocument(): DesignDocument {
  return {
    schemaVersion: 2,
    base: {
      tokens: { root: {}, light: {} },
      copy: {},
      icons: {},
      elements: {},
      behaviors: {},
      layout: null,
    },
    variations: {},
    activeVariationId: "",
    globalTargets: {},
    orphanedEdits: {},
    cadPresentation: {},
  };
}

function personalDocument(): DesignDocument {
  const document = fixtureDocument();
  document.base = {
    tokens: { root: { "--r-card": "18px" }, light: { "--c-t1": "#111111" } },
    copy: { "rail.components": "My Components" },
    icons: { "nav.components": { swapToId: "nav.stm" } },
    elements: { "rail.about": { width: "240px" } },
    behaviors: { "projects.board-control": { preset: "segmented" } },
    layout: null,
  };
  return document;
}

function documentWithIssue(code: "missing-target"): DesignDocument {
  const document = fixtureDocument();
  document.orphanedEdits[`unregistered.${code}`] = {
    targetId: `unregistered.${code}`,
  };
  return document;
}

function readyStatus(overrides: Partial<DevWorkspaceStatus> = {}): DevWorkspaceStatus {
  return {
    available: true,
    branch: "main",
    revision: "a".repeat(40),
    dirty: [],
    can_publish: false,
    publish_blocker: "Save a Dev Mode change before publishing.",
    ...overrides,
  };
}

describe("personal design source promotion", () => {
  it("translates the complete resolved design into the existing source-owned save body", () => {
    expect(promotionPlan(personalDocument(), "light", null)).toEqual({
      tokens: { root: { "--r-card": "18px" }, light: { "--c-t1": "#111111" } },
      copy: { "rail.components": "My Components" },
      icons: { "nav.components": { swapToId: "nav.stm" } },
      elements: { "rail.about": { width: "240px" } },
      behaviors: { "projects.board-control": { preset: "segmented" } },
      copyPlaceholders: {},
      layout: { workspace: null },
      committedIssues: { workspace: [] },
      ownerAuthoredCopy: ["rail.components"],
    });
  });

  it("preserves base, both themes, and every supported variation in the atomic plan", () => {
    const document = personalDocument();
    document.variations.custom = {
      id: "custom",
      title: "Custom",
      patch: { copy: { "rail.components": "Custom Components" } },
      themes: { light: { copy: { "rail.components": "Light Custom Components" } } },
    };
    document.activeVariationId = "custom";

    const plan = promotionTransactionPlan(document, "Promote", "light", null);

    expect(Object.keys(plan.translations.base)).toEqual(["dark", "light"]);
    expect(Object.keys(plan.translations.variations)).toEqual(["custom"]);
    expect(plan.translations.variations.custom?.themes.dark.copy["rail.components"]).toBe("Custom Components");
    expect(plan.translations.variations.custom?.themes.light.copy["rail.components"]).toBe("Light Custom Components");
    expect(plan.source.copy["rail.components"]).toBe("Light Custom Components");
  });

  it("collects every issue and refuses promotion when a target remains unresolved", () => {
    const document = documentWithIssue("missing-target");
    expect(collectDesignIssues(document, "dark", null).map((issue) => issue.code)).toEqual([
      "missing-target",
    ]);
    expect(() => promotionPlan(document, "dark", null)).toThrow(
      "Resolve 1 Design Studio issue before making this design the app default.",
    );
    expect(() => promotionPlan(document, "dark", null)).toThrow(PromotionValidationError);
  });

  it("validates only the rendered product root, never Design Studio controls", () => {
    const shell = document.createElement("div");
    shell.innerHTML = `
      <button>Make App Default</button>
      <div data-design-product-root>
        <button data-dev-id="rail.about">About</button>
      </div>
    `;

    expect(collectDesignIssues(fixtureDocument(), "dark", shell)).toEqual([]);
  });

  it("accepts a safe generated icon attached to a known global target", () => {
    const document = fixtureDocument();
    document.base.icons["auto.inserted-icon.001c8t8"] = {
      body: '<path d="M4 12h16" />',
      insertInto: "auto.copy.0fedcba",
      placement: "before",
    };

    expect(collectDesignIssues(document, "dark", null)).toEqual([]);
  });

  it("never invokes source APIs while a fixture scenario is active", async () => {
    const client = {
      devStatus: vi.fn(),
      devPromote: vi.fn(),
    };

    const result = await runPersonalDesignPromotion({
      document: personalDocument(),
      activeScenarioId: "global.source-promotion.ready",
      theme: "dark",
      message: "Promote personal design",
      client,
      targetRoot: null,
    });

    expect(result).toEqual({
      state: "blocked",
      message: "Return to Real Data before making this design the app default.",
    });
    expect(client.devStatus).not.toHaveBeenCalled();
    expect(client.devPromote).not.toHaveBeenCalled();
  });

  it("reports the exact source blocker without saving or publishing", async () => {
    const client = {
      devStatus: vi.fn().mockResolvedValue(readyStatus({
        available: false,
        publish_blocker: "Dev Mode needs a managed Stockroom source checkout.",
      })),
      devPromote: vi.fn(),
    };

    const result = await runPersonalDesignPromotion({
      document: personalDocument(),
      activeScenarioId: null,
      theme: "dark",
      message: "Promote personal design",
      client,
      targetRoot: null,
    });

    expect(result).toEqual({
      state: "blocked",
      message: "Dev Mode needs a managed Stockroom source checkout.",
    });
    expect(client.devPromote).not.toHaveBeenCalled();
  });

  it("calls status and the one atomic promotion endpoint in order", async () => {
    const calls: string[] = [];
    const client = {
      devStatus: vi.fn(async () => {
        calls.push("status");
        return readyStatus();
      }),
      devPromote: vi.fn(async () => {
        calls.push("promote");
        return {
          ok: true,
          commit: "b".repeat(40),
          branch: "main",
          message: "Promote personal design",
          checks: ["typecheck", "production build"],
          pushed: true,
          themes: ["dark", "light"] as ["dark", "light"],
          variations: 0,
        };
      }),
    };

    const result = await runPersonalDesignPromotion({
      document: personalDocument(),
      activeScenarioId: null,
      theme: "light",
      message: "Promote personal design",
      client,
      targetRoot: null,
    });

    expect(calls).toEqual(["status", "promote"]);
    expect(client.devPromote).toHaveBeenCalledWith(
      promotionTransactionPlan(personalDocument(), "Promote personal design", "light", null),
    );
    expect(result).toEqual({
      state: "success",
      message: "Promoted personal design at " + "b".repeat(40) + ".",
      commit: "b".repeat(40),
    });
  });

  it("retains the backend recovery message after an atomic promotion failure", async () => {
    const client = {
      devStatus: vi.fn().mockResolvedValue(readyStatus()),
      devPromote: vi.fn().mockRejectedValue(new Error("Source and dist snapshot restored.")),
    };

    const result = await runPersonalDesignPromotion({
      document: personalDocument(),
      activeScenarioId: null,
      theme: "dark",
      message: "Promote personal design",
      client,
      targetRoot: null,
    });

    expect(result).toEqual({ state: "failure", message: "Source and dist snapshot restored." });
  });
});
