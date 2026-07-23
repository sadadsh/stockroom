import { describe, it, expect } from "vitest";
import type { AltiumStatusRow } from "../api/types";
import { matchAltiumFilesToParts } from "./altiumBulk";

function row(mpn: string): AltiumStatusRow {
  return {
    id: mpn.toLowerCase() || "blank",
    display_name: mpn || "Unnamed",
    category: "ICs",
    mpn,
    value: "",
    symbol: "",
    footprint: "",
    ready: false,
  };
}

describe("matchAltiumFilesToParts", () => {
  it("matches a part by a single .IntLib named for its MPN", () => {
    const plan = matchAltiumFilesToParts(
      [row("TPS62130")],
      ["C:/assets/TPS62130.IntLib"],
    );
    expect(plan.matched).toEqual([{ row: row("TPS62130"), paths: ["C:/assets/TPS62130.IntLib"] }]);
    expect(plan.unmatched).toEqual([]);
  });

  it("matches a part by a complete .SchLib + .PcbLib pair", () => {
    const plan = matchAltiumFilesToParts(
      [row("LM358")],
      ["/lib/LM358.SchLib", "/lib/LM358.PcbLib"],
    );
    expect(plan.matched).toHaveLength(1);
    expect(plan.matched[0].paths.sort()).toEqual(["/lib/LM358.PcbLib", "/lib/LM358.SchLib"]);
    expect(plan.unmatched).toEqual([]);
  });

  it("reports a part with only half the Sch/Pcb pair as unmatched, never half-attached", () => {
    const plan = matchAltiumFilesToParts([row("R100K")], ["/lib/R100K.SchLib"]);
    expect(plan.matched).toEqual([]);
    expect(plan.unmatched).toEqual([row("R100K")]);
  });

  it("matches by MPN stem case-insensitively", () => {
    const plan = matchAltiumFilesToParts([row("Tps62130")], ["/x/TPS62130.intlib"]);
    expect(plan.matched).toHaveLength(1);
    expect(plan.matched[0].row.mpn).toBe("Tps62130");
  });

  it("prefers the single .IntLib when both it and a Sch/Pcb pair are present", () => {
    const plan = matchAltiumFilesToParts(
      [row("PART1")],
      ["/x/PART1.IntLib", "/x/PART1.SchLib", "/x/PART1.PcbLib"],
    );
    expect(plan.matched[0].paths).toEqual(["/x/PART1.IntLib"]);
  });

  it("ignores unrelated files and reports parts with no file as unmatched", () => {
    const plan = matchAltiumFilesToParts(
      [row("HAVE"), row("MISSING")],
      ["/x/HAVE.IntLib", "/x/notes.txt", "/x/random.pdf"],
    );
    expect(plan.matched.map((m) => m.row.mpn)).toEqual(["HAVE"]);
    expect(plan.unmatched.map((r) => r.mpn)).toEqual(["MISSING"]);
  });

  it("never matches a row with no MPN", () => {
    const plan = matchAltiumFilesToParts([row("")], ["/x/.IntLib", "/x/anything.IntLib"]);
    expect(plan.matched).toEqual([]);
    expect(plan.unmatched).toHaveLength(1);
  });
});
