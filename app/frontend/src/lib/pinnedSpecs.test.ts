/**
 * The pinned-spec preference, now bound to the dossier's canonical key.
 *
 * The point of the change is what a pin IDENTIFIES. It used to be a canonical id derived on the
 * client from a distributor's own wording, which meant the preference could only follow a
 * specification as far as the client's spelling rules reached. It is now the backend's `key`,
 * which is the same identity for that specification on every part, in every category, from every
 * source - so nothing here has to know how a vendor spelled it.
 */
import { describe, expect, it } from "vitest";
import {
  categoryKey,
  isPinned,
  normalizePinnedSpecs,
  togglePinned,
  type PinnedSpecs,
} from "./pinnedSpecs";

describe("the category a pin belongs to", () => {
  it("folds a display name and a schema key onto the same category", () => {
    expect(categoryKey("Crystals & Oscillators")).toBe("crystals_oscillators");
    expect(categoryKey("crystals_oscillators")).toBe("crystals_oscillators");
    expect(categoryKey("  ICs  ")).toBe("ics");
    expect(categoryKey("")).toBe("");
  });
});

describe("pinning a specification", () => {
  it("adds and removes by the canonical key, never by a vendor's wording", () => {
    let pinned: PinnedSpecs = {};
    pinned = togglePinned(pinned, "ICs", "supply_voltage");
    expect(isPinned(pinned, "ICs", "supply_voltage")).toBe(true);
    // The same category under its other spelling is the same category.
    expect(isPinned(pinned, "ics", "supply_voltage")).toBe(true);
    // And a different category is genuinely different.
    expect(isPinned(pinned, "Resistors", "supply_voltage")).toBe(false);

    pinned = togglePinned(pinned, "ICs", "supply_voltage");
    expect(isPinned(pinned, "ICs", "supply_voltage")).toBe(false);
  });

  it("drops a category that has no pins left rather than keeping an empty list", () => {
    const one = togglePinned({}, "ICs", "supply_voltage");
    expect(Object.keys(togglePinned(one, "ICs", "supply_voltage"))).toEqual([]);
  });

  it("never mutates the map it was given, so a pointless write is still detectable", () => {
    const before: PinnedSpecs = { ics: ["supply_voltage"] };
    const after = togglePinned(before, "ICs", "output_current");
    expect(before).toEqual({ ics: ["supply_voltage"] });
    expect(after).toEqual({ ics: ["supply_voltage", "output_current"] });
  });

  it("ignores a key that is only whitespace", () => {
    expect(togglePinned({}, "ICs", "   ")).toEqual({});
  });
});

describe("reading a preference somebody may have edited", () => {
  it("degrades to nothing pinned rather than throwing on a malformed mirror", () => {
    expect(normalizePinnedSpecs(null)).toEqual({});
    expect(normalizePinnedSpecs(undefined)).toEqual({});
    expect(normalizePinnedSpecs([] as unknown as PinnedSpecs)).toEqual({});
    expect(normalizePinnedSpecs({ ics: "supply_voltage" } as unknown as PinnedSpecs)).toEqual({});
  });

  it("keeps the entries it can read and drops the ones it cannot", () => {
    expect(
      normalizePinnedSpecs({
        "Integrated Circuits": ["supply_voltage", 7, "", "supply_voltage"],
        "": ["output_current"],
      } as unknown as PinnedSpecs),
    ).toEqual({ integrated_circuits: ["supply_voltage"] });
  });
});
