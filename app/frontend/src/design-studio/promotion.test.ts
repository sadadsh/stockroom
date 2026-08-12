import { describe, expect, it, vi } from "vitest";
import type { DevWorkspaceStatus } from "../api/types";
import type { DesignDocument } from "./document";
import {
  PromotionValidationError,
  collectDesignIssues,
  promotionPlan,
  runPersonalDesignPromotion,
} from "./promotion";

function fixtureDocument(): DesignDocument {
  return {
    schemaVersion: 1,
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
    targetScopes: {},
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
  document.targetScopes[`unregistered.${code}`] = "instance";
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

  it("never invokes source APIs while a fixture scenario is active", async () => {
    const client = {
      devStatus: vi.fn(),
      devSave: vi.fn(),
      devPublish: vi.fn(),
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
    expect(client.devSave).not.toHaveBeenCalled();
    expect(client.devPublish).not.toHaveBeenCalled();
  });

  it("reports the exact source blocker without saving or publishing", async () => {
    const client = {
      devStatus: vi.fn().mockResolvedValue(readyStatus({
        available: false,
        publish_blocker: "Dev Mode needs a managed Stockroom source checkout.",
      })),
      devSave: vi.fn(),
      devPublish: vi.fn(),
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
    expect(client.devSave).not.toHaveBeenCalled();
    expect(client.devPublish).not.toHaveBeenCalled();
  });

  it("calls status, save, and publish in order and returns the published result", async () => {
    const calls: string[] = [];
    const client = {
      devStatus: vi.fn(async () => {
        calls.push("status");
        return readyStatus();
      }),
      devSave: vi.fn(async () => {
        calls.push("save");
        return {
          ok: true,
          written: [],
          tokens: 2,
          copy: 1,
          icons: 1,
          elements: 1,
          behaviors: 1,
        };
      }),
      devPublish: vi.fn(async () => {
        calls.push("publish");
        return {
          ok: true,
          commit: "b".repeat(40),
          branch: "main",
          message: "Promote personal design",
          checks: ["typecheck", "production build"],
          pushed: true,
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

    expect(calls).toEqual(["status", "save", "publish"]);
    expect(client.devSave).toHaveBeenCalledWith(promotionPlan(personalDocument(), "light", null));
    expect(result).toEqual({
      state: "success",
      message: "Promoted personal design at " + "b".repeat(40) + ".",
      commit: "b".repeat(40),
    });
  });

  it("retains the source refusal message after save without attempting publish", async () => {
    const client = {
      devStatus: vi.fn().mockResolvedValue(readyStatus()),
      devSave: vi.fn().mockRejectedValue(new Error("Source write rolled back.")),
      devPublish: vi.fn(),
    };

    const result = await runPersonalDesignPromotion({
      document: personalDocument(),
      activeScenarioId: null,
      theme: "dark",
      message: "Promote personal design",
      client,
      targetRoot: null,
    });

    expect(result).toEqual({ state: "failure", message: "Source write rolled back." });
    expect(client.devPublish).not.toHaveBeenCalled();
  });
});
