import { describe, expect, it } from "vitest";
import { DEV_IDS, DEV_ID_AREAS, DEV_ID_BY_ID } from "./devIds";

// The catalogue is the single source of truth for the dev-mode ID system, so these
// tests guard it against accidental drops, duplicate ids, area drift, and a stale
// by-id map — the four ways the hand-authored list could silently rot.
describe("devIds catalogue", () => {
  it("has exactly 196 entries carrying only id/label/area", () => {
    expect(DEV_IDS).toHaveLength(196);
    for (const entry of DEV_IDS) {
      expect(Object.keys(entry).sort()).toEqual(["area", "id", "label"]);
      expect(typeof entry.id).toBe("string");
      expect(typeof entry.label).toBe("string");
      expect(typeof entry.area).toBe("string");
      expect(entry.id.length).toBeGreaterThan(0);
      expect(entry.label.length).toBeGreaterThan(0);
    }
  });

  it("has unique ids whose first dot-segment equals the area", () => {
    const seen = new Set<string>();
    for (const entry of DEV_IDS) {
      expect(seen.has(entry.id)).toBe(false);
      seen.add(entry.id);
      expect(entry.id.split(".")[0]).toBe(entry.area);
    }
    expect(seen.size).toBe(196);
  });

  it("enumerates the 15 areas in first-appearance order, and every entry is a member", () => {
    expect(DEV_ID_AREAS).toEqual([
      "rail",
      "about",
      "components",
      "detail",
      "search",
      "addpart",
      "ingest",
      "projects",
      "settings",
      "altiumdb",
      "complete",
      "preview",
      "diff",
      "confirm",
      "shell",
    ]);
    expect(DEV_ID_AREAS).toHaveLength(15);

    // Every catalogued area is declared in DEV_ID_AREAS...
    const declared = new Set(DEV_ID_AREAS);
    for (const entry of DEV_IDS) {
      expect(declared.has(entry.area)).toBe(true);
    }
    // ...and DEV_ID_AREAS is exactly the areas in first-appearance order (no extras).
    const firstSeen: string[] = [];
    for (const entry of DEV_IDS) {
      if (!firstSeen.includes(entry.area)) firstSeen.push(entry.area);
    }
    expect(DEV_ID_AREAS).toEqual(firstSeen);
  });

  it("DEV_ID_BY_ID round-trips every entry", () => {
    expect(DEV_ID_BY_ID.size).toBe(196);
    for (const entry of DEV_IDS) {
      expect(DEV_ID_BY_ID.get(entry.id)).toBe(entry);
    }
  });
});
