import { describe, expect, it } from "vitest";
import type { SymbolGeometry } from "../../api/client";
import { symbolLabelFontSize } from "./SymbolPreview";

describe("symbolLabelFontSize", () => {
  it("shrinks dense long pin labels while leaving sparse symbols readable", () => {
    const dense = {
      bounds: { x: 0, y: 0, width: 20, height: 20 },
      pins: Array.from({ length: 100 }, (_, index) => ({ name: `VERY_LONG_PIN_${index}` })),
    } as SymbolGeometry;
    const sparse = {
      bounds: { x: 0, y: 0, width: 20, height: 10 },
      pins: [{ name: "A" }, { name: "B" }],
    } as SymbolGeometry;

    expect(symbolLabelFontSize(dense)).toBeLessThan(0.7);
    expect(symbolLabelFontSize(sparse)).toBe(1.1);
  });
});
