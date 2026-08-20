import { describe, expect, it } from "vitest";
import { sanitizeIconBody } from "../components/iconResolve";
import { fontAwesomeEntries, searchIconCatalog } from "./fontAwesomeRegistry";

describe("fontAwesomeRegistry", () => {
  it("indexes every bundled Font Awesome icon without network access", () => {
    const entries = fontAwesomeEntries();

    expect(entries.length).toBeGreaterThan(1000);
    expect(entries.every((entry) => entry.body && entry.viewBox)).toBe(true);
    expect(entries.every((entry) => entry.body === sanitizeIconBody(entry.body))).toBe(true);
    expect(entries.every((entry) => entry.family === "solid" || entry.family === "regular")).toBe(true);
  });

  it("searches an icon's label, terms, and family", () => {
    const matches = searchIconCatalog("address book regular");

    expect(matches.some((entry) => entry.label === "address-book" && entry.family === "regular")).toBe(true);
  });

  it("never offers technical CAD preview geometry as an interface icon", () => {
    expect(searchIconCatalog("footprint copper polygon").some((item) => item.family === "cad-content")).toBe(false);
  });
});
