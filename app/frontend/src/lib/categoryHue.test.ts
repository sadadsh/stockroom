import { categoryHue } from "./categoryHue";

const KNOWN = [
  ["Resistors", "resistor"],
  ["Capacitors", "capacitor"],
  ["Inductors", "inductor"],
  ["Ferrite Beads", "inductor"],
  ["Diodes", "diode"],
  ["LEDs", "diode"],
  ["Connectors", "connector"],
  ["Pin Headers", "connector"],
  ["Crystals & Oscillators", "crystal"],
  ["ICs", "ic"],
] as const;

describe("categoryHue", () => {
  it("maps each known family to its stable family descriptor", () => {
    for (const [category, family] of KNOWN) {
      expect(categoryHue(category).family).toBe(family);
    }
  });

  it("is case-insensitive and substring-based (mirrors CategoryGlyph)", () => {
    expect(categoryHue("RESISTORS").family).toBe("resistor");
    expect(categoryHue("Chip Resistor").family).toBe("resistor");
    expect(categoryHue("thin film resistors").family).toBe("resistor");
  });

  it("gives distinct hues to distinct passive families (no collision)", () => {
    const tokens = ["Resistors", "Capacitors", "Inductors", "Diodes", "Connectors", "Crystals"].map(
      (c) => categoryHue(c).token,
    );
    expect(new Set(tokens).size).toBe(tokens.length);
  });

  it("falls back to neutral for an unknown or empty category", () => {
    expect(categoryHue("").family).toBe("neutral");
    expect(categoryHue("Cardboard Boxes").family).toBe("neutral");
    expect(categoryHue("Hardware").family).toBe("neutral");
  });

  it("references design tokens only, never a raw hex literal", () => {
    for (const [category] of [...KNOWN, ["", "neutral"] as const]) {
      const h = categoryHue(category);
      expect(h.stroke).toMatch(/var\(--/);
      expect(h.stroke).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
      expect(h.tileClass).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    }
  });
});
