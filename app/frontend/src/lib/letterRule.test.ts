/**
 * The shared letter-rule judgement.
 *
 * `copy.letterRule.test.ts` is the GATE - it reads source and fails the build - and it now imports
 * its judgement from `letterRule.ts` so Design Mode's copy editor can run the identical rule on text
 * the owner types (plan 1.5). This file tests that judgement as a function, which is the part the
 * gate cannot reach: the gate only ever sees strings that happen to be in the tree, and every one of
 * them is clean, so nothing there exercises what the rule does with an offender.
 *
 * NON-VACUITY. Each case names its killing mutation. The floor throughout is that a CLEAN string
 * comes back clean and an OFFENDING one comes back named - a rule that answered the same way to both
 * fails every case here.
 */
import { describe, expect, it } from "vitest";
import { INDUSTRY_TERMS } from "./interfaceTerms";
import { ALLOWED_TERMS, judgedText, letterRuleOffences, PROPER_NAMES } from "./letterRule";

describe("the allowlist", () => {
  /**
   * FAILS IF: either category is dropped from the union - the editor would then report a trade name
   * or a standardised term as an offence, which is the rule overruling the two exemptions that were
   * argued for rather than enforcing the one that was.
   */
  it("is both categories and nothing else", () => {
    expect(ALLOWED_TERMS).toEqual([...PROPER_NAMES, ...INDUSTRY_TERMS.map((entry) => entry.term)]);
    expect(ALLOWED_TERMS.length).toBeGreaterThan(1);
  });

  /**
   * WHOLE WORD, BOTH WAYS. FAILS IF: the matcher drops its `\b` anchors, in which case `Layered`
   * launders through `Layer` and the rule stops binding a word nobody exempted.
   */
  it("exempts a term and its plural, and launders nothing longer", () => {
    expect(letterRuleOffences("Symbol")).toEqual([]);
    expect(letterRuleOffences("Symbols")).toEqual([]);
    expect(letterRuleOffences("symbol")).toEqual([]);
    expect(letterRuleOffences("Layered")).toEqual(["Layered"]);
    expect(letterRuleOffences("DigiKeyed")).toEqual(["DigiKeyed"]);
  });
});

describe("what the rule judges", () => {
  /**
   * FAILS IF: placeholders are judged rather than blanked. `{quantity}` is a code identifier wired to
   * a values object, and reporting it would tell the owner to reword something no reader ever sees.
   */
  it("blanks a placeholder and judges the words around it", () => {
    expect(judgedText("Holds {quantity} parts")).not.toContain("quantity");
    expect(letterRuleOffences("Holds {quantity} parts")).toEqual([]);
    expect(letterRuleOffences("Apply to {quantity} parts")).toEqual(["Apply"]);
  });

  /**
   * FAILS IF: the offences are returned as a boolean or as the whole string - a warning that says
   * only "there is a problem" leaves the owner hunting one character through a sentence.
   */
  it("names each offending word once, in the order it appears", () => {
    expect(letterRuleOffences("Apply the Category, then apply it")).toEqual([
      "Apply",
      "Category",
      "apply",
    ]);
    expect(letterRuleOffences("Set the state")).toEqual([]);
  });

  /**
   * THE GATE'S OWN CASE FOLDING, matched deliberately. The gate tests for the lower-case codepoint
   * and only it, so a warning that fired on the capital would be reporting an offence that nothing
   * downstream reports.
   *
   * FAILS IF: the check is case-folded, which would make the editor stricter than the build.
   */
  it("answers for the lower-case codepoint alone, exactly as the gate does", () => {
    expect(letterRuleOffences("APPLY")).toEqual([]);
    expect(letterRuleOffences("Apply")).toEqual(["Apply"]);
  });
});
