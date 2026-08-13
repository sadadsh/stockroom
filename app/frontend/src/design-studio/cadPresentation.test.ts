import { describe, expect, it } from "vitest";
import { committedDevModeDraft } from "../lib/devModeDraft";
import { updateCadPresentationDocument, updateCadPresentationThemeDocument } from "./cadPresentation";
import { builtInVariationDocument, resolveDesign, type DesignDocument } from "./document";

function document(): DesignDocument {
  return {
    schemaVersion: 2,
    base: committedDevModeDraft(),
    variations: builtInVariationDocument(),
    activeVariationId: "full-data",
    globalTargets: {},
    orphanedEdits: {},
    cadPresentation: {},
  };
}

describe("CAD presentation editing", () => {
  it("writes sparse typed presentation into the active variation without touching CAD data", () => {
    const source = document();
    const next = updateCadPresentationDocument(source, "cad.symbol", "symbol", {
      body: false,
      pins: true,
      stroke: "#123456",
    });

    expect(source).toEqual(document());
    expect(resolveDesign(next, "full-data", "dark").cadPresentation["cad.symbol"]).toEqual({
      symbol: { body: false, pins: true, stroke: "#123456" },
    });
    expect(next.base).toBe(source.base);
  });

  it("merges one CAD kind without deleting the other presentation kinds", () => {
    const withFootprint = updateCadPresentationDocument(document(), "cad.asset", "footprint", {
      pads: false,
    });
    const next = updateCadPresentationDocument(withFootprint, "cad.asset", "model3d", {
      models: false,
      opacity: 0.4,
    });

    expect(resolveDesign(next, "full-data", "dark").cadPresentation["cad.asset"]).toEqual({
      footprint: { pads: false },
      model3d: { models: false, opacity: 0.4 },
    });
  });

  it("keeps CAD colors independent between dark and light themes", () => {
    const dark = updateCadPresentationThemeDocument(document(), "cad.symbol", "symbol", { stroke: "#111111" }, "dark");
    const next = updateCadPresentationThemeDocument(dark, "cad.symbol", "symbol", { stroke: "#eeeeee" }, "light");

    expect(resolveDesign(next, "full-data", "dark").cadPresentation["cad.symbol"]?.symbol?.stroke).toBe("#111111");
    expect(resolveDesign(next, "full-data", "light").cadPresentation["cad.symbol"]?.symbol?.stroke).toBe("#eeeeee");
  });
});
