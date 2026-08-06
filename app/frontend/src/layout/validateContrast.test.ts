/**
 * Contrast: the shipped design passing its own gate, and three ways of proving that is not vacuous.
 *
 * THE ANCHOR is the first test: the shipped document measured against the shipped token defaults, in
 * both themes, produces NO warning. A validator that always returned an empty list would pass it,
 * which is why the three proofs after it matter and why one of them uses real shipped values rather
 * than a fabricated palette:
 *
 *   A DELIBERATELY BROKEN TOKEN. The primary text tier set to the workspace colour it is drawn on -
 *   a 1.00 ratio, the worst a pairing can be.
 *
 *   A REAL FAILING PAIRING THE WORKSPACE DOES NOT USE. `--c-active` carries the label tier at 4.43
 *   in light theme, under the 4.5 a word answers to. Nothing is invented: those are the shipped
 *   values, and the reason the pairing is absent from the table is that the workspace paints no text
 *   on that surface. Adding it produces a genuine warning from the shipped palette.
 *
 *   A DRAFT VALUE THAT CANNOT BE MEASURED, which is what a style panel produces the moment somebody
 *   types a translucent colour into a text tier.
 */
import { describe, expect, it } from "vitest";
import { DEFAULT_WORKSPACE_LAYOUT } from "./defaultWorkspaceLayout";
import { walkLayout, type LayoutDocument } from "./document";
import {
  contrastRatio,
  CONTRAST_FLOOR,
  devTokenValues,
  parseColor,
  shippedThemeTokens,
  validateContrast,
  WORKSPACE_CONTRAST_PAIRINGS,
  WORKSPACE_TEXT_SURFACES,
  type ContrastPairing,
  type ThemeTokens,
} from "./validateContrast";

function clone(document: LayoutDocument): LayoutDocument {
  // `structuredClone` rather than a JSON round trip: the document is serialisable either way, and
  // the structured algorithm does not depend on that fact holding.
  return structuredClone(document);
}

/** Every placement hidden: the arrangement with nothing on screen. */
function allHidden(): LayoutDocument {
  const copy = clone(DEFAULT_WORKSPACE_LAYOUT);
  for (const visit of walkLayout(copy)) {
    if (visit.node.kind === "placement") (visit.node as { hidden?: boolean }).hidden = true;
  }
  return copy;
}

const shipped = shippedThemeTokens();
const warnings = (issues: ReturnType<typeof validateContrast>) =>
  issues.filter((issue) => issue.severity === "warning");

describe("the shipped design passes its own gate", () => {
  it("warns about nothing, in either theme", () => {
    // THE ANCHOR.
    expect(validateContrast(DEFAULT_WORKSPACE_LAYOUT, shipped)).toEqual([]);
  });

  it("measured a large table to get there", () => {
    // Guards the anchor against an empty table or an empty palette. Both would produce the same
    // empty list for the opposite reason.
    expect(WORKSPACE_CONTRAST_PAIRINGS.length).toBeGreaterThan(100);
    expect(new Set(WORKSPACE_CONTRAST_PAIRINGS.map((p) => p.bar))).toEqual(new Set(["text", "non-text"]));
    expect(shipped.map((t) => t.theme)).toEqual(["dark", "light"]);
    for (const theme of shipped) {
      for (const pairing of WORKSPACE_CONTRAST_PAIRINGS) {
        expect(theme.values[pairing.ink], `${theme.theme} ${pairing.ink}`).toBeDefined();
        expect(theme.values[pairing.surface], `${theme.theme} ${pairing.surface}`).toBeDefined();
      }
    }
  });

  it("clears each floor with room, rather than sitting on it", () => {
    // The shipped values' actual margins, so a token nudged by a point is caught by the anchor
    // rather than by a person noticing later. The tightest pairing in the whole table is 4.55.
    let tightest = Number.POSITIVE_INFINITY;
    for (const theme of shipped) {
      for (const pairing of WORKSPACE_CONTRAST_PAIRINGS) {
        const ratio = contrastRatio(theme.values[pairing.ink], theme.values[pairing.surface]);
        expect(ratio, `${theme.theme} ${pairing.ink} on ${pairing.surface}`).not.toBeNull();
        const margin = (ratio ?? 0) - CONTRAST_FLOOR[pairing.bar];
        if (margin < tightest) tightest = margin;
      }
    }
    expect(tightest).toBeGreaterThan(0);
    expect(tightest).toBeLessThan(0.5);
  });
});

describe("the non-vacuity proofs", () => {
  it("warns when a text tier is set to the surface it is drawn on", () => {
    // THE MANDATORY PROOF. A draft palette in which the primary tier IS the workspace colour.
    // Killing mutation: return the empty list, skip the floor comparison, or compare with `<=` on a
    // ratio that can never be under 1.
    const broken: ThemeTokens[] = [
      {
        theme: "dark",
        values: { ...devTokenValues("dark"), "--c-t1": devTokenValues("dark")["--c-canvas"] },
      },
    ];
    const issues = warnings(validateContrast(DEFAULT_WORKSPACE_LAYOUT, broken));
    expect(issues.length).toBeGreaterThan(0);
    const onCanvas = issues.find((issue) => issue.subject.id === "dark:--c-t1:--c-canvas");
    expect(onCanvas?.code).toBe("contrast-below-text-floor");
    expect(onCanvas?.copy.id).toBe("layout-issues.contrast-below-text-floor");
    expect(onCanvas?.detail).toEqual({ ratio: 1, floor: 4.5, bar: "text" });
    // And only the tier that was broken is reported: the rest of the palette is untouched.
    expect(issues.every((issue) => issue.subject.id.includes("--c-t1"))).toBe(true);
  });

  it("warns on a real shipped pairing the workspace happens not to use", () => {
    // `--c-active` at the label tier measures 4.43 in light theme. Real values, real failure - the
    // table omits the pairing because no workspace piece paints text on that surface, not because
    // the values pass.
    //
    // Killing mutation: any change that makes the floor comparison never fire.
    const pairings: ContrastPairing[] = [{ ink: "--c-t3", surface: "--c-active", bar: "text" }];
    const issues = warnings(validateContrast(DEFAULT_WORKSPACE_LAYOUT, shipped, { pairings }));
    expect(issues).toHaveLength(1);
    expect(issues[0].subject).toMatchObject({
      kind: "token-pair",
      theme: "light",
      ink: "--c-t3",
      surface: "--c-active",
    });
    expect(issues[0].detail?.ratio).toBeCloseTo(4.43, 2);
    // The same pairing clears the floor in dark theme, which is why one row appears and not two.
    expect(contrastRatio(devTokenValues("dark")["--c-t3"], devTokenValues("dark")["--c-active"]))
      .toBeGreaterThan(CONTRAST_FLOOR.text);
    expect(WORKSPACE_TEXT_SURFACES).not.toContain("--c-active");
  });

  it("reports a value it cannot measure rather than guessing one", () => {
    // What a style panel produces the moment a translucent colour lands in a text tier: a wash over
    // an unknown backing has no contrast ratio at all.
    //
    // Killing mutation: fall back to treating an unparseable value as black. Every such pairing
    // would then measure as passing on a dark surface and failing on a light one, which is a
    // fabricated answer wearing the same shape as a real one.
    const draft: ThemeTokens[] = [
      {
        theme: "dark",
        values: { ...devTokenValues("dark"), "--c-t2": "rgba(255, 255, 255, 0.3)" },
      },
    ];
    const issues = validateContrast(DEFAULT_WORKSPACE_LAYOUT, draft);
    expect(warnings(issues)).toEqual([]);
    const unmeasured = issues.filter((issue) => issue.code === "contrast-not-measured");
    expect(unmeasured.length).toBe(WORKSPACE_TEXT_SURFACES.length);
    expect(unmeasured[0].severity).toBe("info");
    expect(unmeasured[0].detail).toEqual({
      reason: "unreadable",
      token: "--c-t2",
      value: "rgba(255, 255, 255, 0.3)",
    });
  });

  it("reports an absent value as absent", () => {
    const partial: ThemeTokens[] = [{ theme: "dark", values: { "--c-t1": "#ffffff" } }];
    const issues = validateContrast(DEFAULT_WORKSPACE_LAYOUT, partial);
    expect(warnings(issues)).toEqual([]);
    expect(issues.every((issue) => issue.code === "contrast-not-measured")).toBe(true);
    expect(issues[0].detail?.reason).toBe("absent");
  });
});

describe("the document decides which pairings are live", () => {
  it("measures nothing when the arrangement puts nothing on screen", () => {
    // Killing mutation: ignore the document entirely. A surface with no text on it has no contrast
    // question, and a validator that answered one anyway would report a design nobody is looking at.
    const broken: ThemeTokens[] = [
      { theme: "dark", values: { ...devTokenValues("dark"), "--c-t1": devTokenValues("dark")["--c-canvas"] } },
    ];
    expect(validateContrast(allHidden(), broken)).toEqual([]);
    // ...and the same palette against the same document, unhidden, does warn.
    expect(warnings(validateContrast(DEFAULT_WORKSPACE_LAYOUT, broken)).length).toBeGreaterThan(0);
  });

  it("skips a pairing scoped to a piece the arrangement has hidden", () => {
    // The mechanism the composer (plan Phase 5) needs: a piece that brings its own pairings stops
    // being measured when it stops being placed.
    const pairings: ContrastPairing[] = [
      { ink: "--c-t3", surface: "--c-active", bar: "text", pieces: ["workspace.sourcing-offers"] },
    ];
    expect(warnings(validateContrast(DEFAULT_WORKSPACE_LAYOUT, shipped, { pairings }))).toHaveLength(1);

    const hidden = clone(DEFAULT_WORKSPACE_LAYOUT);
    for (const visit of walkLayout(hidden)) {
      if (visit.node.kind === "placement" && visit.node.piece === "workspace.sourcing-offers") {
        (visit.node as { hidden?: boolean }).hidden = true;
      }
    }
    expect(validateContrast(hidden, shipped, { pairings })).toEqual([]);
  });
});

describe("the measurement itself", () => {
  it("puts black on white at 21 and any colour on itself at 1", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 10);
    expect(contrastRatio("#2a2c2f", "#2a2c2f")).toBeCloseTo(1, 10);
  });

  it("is symmetric, because a ratio has no foreground", () => {
    expect(contrastRatio("#1f2022", "#e5e7ea")).toBe(contrastRatio("#e5e7ea", "#1f2022"));
  });

  it("reads the short hex form as the same colour and refuses everything else", () => {
    // Killing mutation: accept `rgba(...)` by stripping its alpha. See the header on why a wash has
    // no measurable contrast.
    expect(parseColor("#abc")).toEqual(parseColor("#aabbcc"));
    expect(parseColor(" #AABBCC ")).toEqual([170, 187, 204]);
    expect(parseColor("rgba(0, 0, 0, 0.5)")).toBeNull();
    expect(parseColor("var(--c-t1)")).toBeNull();
    expect(parseColor("white")).toBeNull();
    expect(contrastRatio("#ffffff", "not a colour")).toBeNull();
  });
});
