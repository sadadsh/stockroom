import { describe, expect, it } from "vitest";
import {
  PIN_CATEGORY_HUES,
  UNION_CLASSIFICATION_HUES,
  pinElectricalHue,
  unionClassificationHue,
} from "./stmPinHue";

const CATEGORY_KEYS = [
  "gpio",
  "analog",
  "debug",
  "oscillator",
  "power",
  "ground",
  "reset",
  "boot",
  "vcap",
  "nc",
] as const;

describe("pinElectricalHue", () => {
  it("teaches the ten API category buckets in legend order", () => {
    expect(PIN_CATEGORY_HUES.map((h) => h.key)).toEqual([...CATEGORY_KEYS]);
  });

  it("maps each category to its own --stm-<key> token reference", () => {
    for (const key of CATEGORY_KEYS) {
      const h = pinElectricalHue(key);
      expect(h.key).toBe(key);
      expect(h.token).toBe(`--stm-${key}`);
      expect(h.stroke).toBe(`var(--stm-${key})`);
    }
  });

  it("reads the raw io electrical class as its own io token", () => {
    const h = pinElectricalHue("io");
    expect(h.token).toBe("--stm-io");
    expect(h.stroke).toBe("var(--stm-io)");
    expect(h.label).toBe("GPIO");
  });

  it("falls back to the neutral --c-t2 token for an unknown or empty category (total)", () => {
    for (const c of ["", "someday-new", "switch-fabric"]) {
      const h = pinElectricalHue(c);
      expect(h.key).toBe("neutral");
      expect(h.token).toBe("--c-t2");
      expect(h.stroke).toBe("var(--c-t2)");
      expect(h.tileClass).toBe("");
    }
  });
});

describe("unionClassificationHue", () => {
  it("teaches the three union states in order", () => {
    expect(UNION_CLASSIFICATION_HUES.map((h) => h.key)).toEqual([
      "shared",
      "divergent",
      "partial",
    ]);
  });

  it("maps each classification to its own --stm-classify-<key> token reference", () => {
    for (const key of ["shared", "divergent", "partial"] as const) {
      const h = unionClassificationHue(key);
      expect(h.key).toBe(key);
      expect(h.token).toBe(`--stm-classify-${key}`);
      expect(h.stroke).toBe(`var(--stm-classify-${key})`);
    }
  });

  it("falls back to the neutral --c-t2 token for an unknown classification (total)", () => {
    const h = unionClassificationHue("nonsense");
    expect(h.key).toBe("neutral");
    expect(h.token).toBe("--c-t2");
    expect(h.stroke).toBe("var(--c-t2)");
  });
});

describe("stmPinHue tokens", () => {
  it("never emits a raw hex literal (tokens only)", () => {
    const all = [...PIN_CATEGORY_HUES, ...UNION_CLASSIFICATION_HUES, pinElectricalHue("")];
    for (const h of all) {
      expect(h.stroke).toMatch(/var\(--/);
      expect(h.stroke).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
      expect(h.tileClass).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    }
  });
});
