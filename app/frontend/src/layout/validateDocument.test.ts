/**
 * The composed issues list.
 *
 * THE ANCHOR, and the reason this file exists: the shipped document, over the shipped registry, with
 * the shipped token defaults, produces an EMPTY list. Not "no errors" - nothing at all. Every
 * warning the editor ever shows is therefore a consequence of an edit, which is the only footing on
 * which a warn-never-block guardrail is worth reading.
 *
 * Everything after it either breaks that in one place, or proves the composition itself: that all
 * four layers reach the list, that the order is stable, and that the informational layer reports
 * only what it was given or what the document itself holds.
 */
import { describe, expect, it } from "vitest";
import { DEFAULT_WORKSPACE_LAYOUT } from "./defaultWorkspaceLayout";
import { walkLayout, type LayoutDocument, type LayoutSlot } from "./document";
import { devTokenValues, shippedThemeTokens, type ThemeTokens } from "./validateContrast";
import { validateDocument, type AutoPlacementRecord } from "./validateDocument";
import { compareIssues, type ValidatorIssue } from "./validatorIssues";
import { WORKSPACE_PIECE_REGISTRY } from "./workspacePieces";

function clone(document: LayoutDocument): LayoutDocument {
  // `structuredClone` rather than a JSON round trip: the document is serialisable either way, and
  // the structured algorithm does not depend on that fact holding.
  return structuredClone(document);
}

const codes = (issues: readonly ValidatorIssue[]) => issues.map((issue) => issue.code);

describe("the shipped arrangement", () => {
  it("produces an empty issues list", () => {
    // THE ANCHOR.
    expect(validateDocument(DEFAULT_WORKSPACE_LAYOUT, WORKSPACE_PIECE_REGISTRY)).toEqual([]);
  });

  it("produces it from a real amount of work rather than from an early return", () => {
    // Guards the anchor. Each of these is a count the anchor depends on being non-zero: pieces to
    // check, actions to reach, placements to size, and palettes to measure.
    expect(WORKSPACE_PIECE_REGISTRY.list().length).toBeGreaterThan(20);
    expect(walkLayout(DEFAULT_WORKSPACE_LAYOUT).filter((v) => v.node.kind === "placement").length)
      .toBeGreaterThan(20);
    expect(shippedThemeTokens()).toHaveLength(2);
  });
});

describe("every layer reaches the list", () => {
  /** The shipped document broken in four different places at once. */
  function broken(): LayoutDocument {
    const copy = clone(DEFAULT_WORKSPACE_LAYOUT);
    for (const visit of walkLayout(copy)) {
      // Reachability: the header's action group, hidden. Fourteen commands go with it.
      if (visit.node.kind === "placement" && visit.node.id === "workspace.place.header-actions") {
        (visit.node as { hidden?: boolean }).hidden = true;
      }
      // Provenance: a role scoped to one instance, which is what the style panel writes for
      // "only here".
      if (visit.node.kind === "placement" && visit.node.id === "workspace.place.status-bar") {
        (visit.node as { styleRoles?: Record<string, string> }).styleRoles = { heading: "meta" };
      }
      // Structure, the layer `validateLayout` owns: a slot with nothing in it.
      if (visit.node.kind === "slot" && visit.node.id === "workspace.slot.sourcing-lifecycle") {
        (visit.node as LayoutSlot).content = null;
      }
    }
    return copy;
  }

  /** Visibility: the label tier set to the surface it sits on. */
  const brokenPalette: ThemeTokens[] = [
    { theme: "dark", values: { ...devTokenValues("dark"), "--c-t3": devTokenValues("dark")["--c-band"] } },
  ];

  it("carries a row from each of the four layers", () => {
    // Killing mutation: drop any one of the four calls in `validateDocument`. Each layer contributes
    // a code no other layer can produce, so removing one is visible here rather than only in that
    // layer's own suite.
    const issues = validateDocument(broken(), WORKSPACE_PIECE_REGISTRY, brokenPalette);
    expect(codes(issues)).toContain("action-unreachable"); // reachability
    expect(codes(issues)).toContain("orphan-slot"); // validateLayout, folded
    expect(codes(issues)).toContain("contrast-below-text-floor"); // visibility
    expect(codes(issues)).toContain("style-role-exception"); // provenance
  });

  it("folds the structural tier without letting an error through", () => {
    // Nothing blocks, so nothing is graded as an error - but the original tier travels with the row.
    const issues = validateDocument(broken(), WORKSPACE_PIECE_REGISTRY, brokenPalette);
    expect(issues.map((issue) => issue.severity)).not.toContain("error");
    const orphan = issues.find((issue) => issue.code === "orphan-slot");
    expect(orphan?.severity).toBe("warning");
    expect(orphan?.detail?.tier).toBe("warning");
  });

  it("can be asked to leave the structural layer out, and includes it otherwise", () => {
    // Killing mutation: default `includeLayoutIssues` to false. A panel would then silently drop
    // "this slot holds nothing", which is the more dishonest of the two lists.
    const withLayout = validateDocument(broken(), WORKSPACE_PIECE_REGISTRY, brokenPalette);
    const without = validateDocument(broken(), WORKSPACE_PIECE_REGISTRY, brokenPalette, {
      includeLayoutIssues: false,
    });
    expect(codes(withLayout)).toContain("orphan-slot");
    expect(codes(without)).not.toContain("orphan-slot");
    expect(without.length).toBeLessThan(withLayout.length);
  });

  it("is ordered, and orders the same list the same way twice", () => {
    // Killing mutation: return the concatenation unsorted. The list would then follow the order the
    // four layers happened to run in, and a committed layout's issues could not be diffed.
    const issues = validateDocument(broken(), WORKSPACE_PIECE_REGISTRY, brokenPalette);
    expect(issues.length).toBeGreaterThan(3);
    for (let i = 1; i < issues.length; i += 1) {
      expect(compareIssues(issues[i - 1], issues[i]), `${issues[i - 1].code} then ${issues[i].code}`)
        .toBeLessThanOrEqual(0);
    }
    // Every warning precedes every informational row.
    const firstInfo = issues.findIndex((issue) => issue.severity === "info");
    if (firstInfo >= 0) {
      expect(issues.slice(firstInfo).every((issue) => issue.severity === "info")).toBe(true);
    }
    const again = validateDocument(broken(), WORKSPACE_PIECE_REGISTRY, brokenPalette);
    expect(JSON.stringify(again)).toBe(JSON.stringify(issues));
  });
});

describe("provenance", () => {
  it("fabricates no auto-placement when it was handed none", () => {
    // Plan decision 6's mitigation is a RECORD of what the placer did. The placer is Phase 5, so the
    // honest list is empty - and a validator that invented an entry to fill the section would be
    // reporting an event that never happened.
    //
    // Killing mutation: derive an auto-placement from a piece's home hint matching its region. Every
    // shipped placement matches its own hint, so the whole workspace would appear auto-placed.
    expect(validateDocument(DEFAULT_WORKSPACE_LAYOUT, WORKSPACE_PIECE_REGISTRY)).toEqual([]);
  });

  it("reports the records it IS handed, as information", () => {
    const records: AutoPlacementRecord[] = [
      {
        piece: "workspace.sourcing-related",
        regionId: "workspace.column-sourcing-body",
        siblingGroup: "workspace.sourcing-sections",
        at: "2026-08-06T09:00:00Z",
      },
    ];
    const issues = validateDocument(DEFAULT_WORKSPACE_LAYOUT, WORKSPACE_PIECE_REGISTRY, undefined, {
      provenance: records,
    });
    expect(issues).toHaveLength(1);
    expect(issues[0].code).toBe("auto-placed");
    expect(issues[0].severity).toBe("info");
    expect(issues[0].subject).toEqual({ kind: "piece", id: "workspace.sourcing-related" });
    expect(issues[0].detail).toEqual({
      region: "workspace.column-sourcing-body",
      group: "workspace.sourcing-sections",
      at: "2026-08-06T09:00:00Z",
    });
  });

  it("reads a style-role exception out of the document rather than remembering it", () => {
    // Killing mutation: report an exception for every placement. The shipped document sets no
    // `styleRoles` at all, so the anchor would fail - which is what makes this derivation safe.
    const copy = clone(DEFAULT_WORKSPACE_LAYOUT);
    for (const visit of walkLayout(copy)) {
      if (visit.node.kind === "placement" && visit.node.id === "workspace.place.cad-title") {
        (visit.node as { styleRoles?: Record<string, string> }).styleRoles = {
          heading: "meta",
          count: "label",
        };
      }
    }
    const issues = validateDocument(copy, WORKSPACE_PIECE_REGISTRY);
    expect(issues).toHaveLength(1);
    expect(issues[0].code).toBe("style-role-exception");
    expect(issues[0].subject).toEqual({ kind: "placement", id: "workspace.place.cad-title" });
    expect(issues[0].detail).toEqual({ piece: "workspace.cad-title-strip", roles: "count heading" });
    expect(issues[0].path?.[0]).toBe("workspace.root");
  });

  it("ignores an empty style-role object, which is not an exception", () => {
    const copy = clone(DEFAULT_WORKSPACE_LAYOUT);
    for (const visit of walkLayout(copy)) {
      if (visit.node.kind === "placement" && visit.node.id === "workspace.place.cad-title") {
        (visit.node as { styleRoles?: Record<string, string> }).styleRoles = {};
      }
    }
    expect(validateDocument(copy, WORKSPACE_PIECE_REGISTRY)).toEqual([]);
  });
});
