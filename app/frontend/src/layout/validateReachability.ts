/**
 * REACHABILITY: can a person still get at everything the application can do.
 *
 * This is the check plan 1.4 leads with, and the canonical case it names is a warning about
 * `component-browser.delete`: the owner hides the identity header's action group, the Manage menu
 * goes with it, and Delete Component becomes a command the build still ships and nobody can invoke.
 * Nothing refuses the edit (plan decision 3) - a row appears, and the owner decides.
 *
 * THE QUESTION, stated exactly. Every action id declared by ANY manifest in the registry must be
 * declared by at least one piece that the document places in a placement that is not hidden. The two
 * halves are deliberately asymmetric:
 *
 *   DECLARED is registry-wide, not document-wide. The set of things the application can do is a
 *   property of the build, not of the arrangement; a piece that exists and is not placed at all
 *   takes its actions out of reach exactly as thoroughly as one that is placed and hidden, and the
 *   warning has to fire for both. (`detail.reason` says which, because the fix differs: one is a
 *   piece to unhide, the other is a piece to place.)
 *
 *   EXPOSED is per-placement, because `hidden` is a per-placement setting. One placement of a piece
 *   being hidden says nothing about another; the three CAD modules are three placements of one
 *   piece, and hiding the Symbol module does not put `component-browser.open-full-preview` out of
 *   reach while the 3D Model module is still on screen.
 *
 * WHAT COUNTS AS ON SCREEN, and the two judgements inside that:
 *
 *   A PLACEMENT BEHIND A VISIBILITY CONDITION COUNTS. Five of the sourcing sections carry
 *   `visibility.anyOf`, and a component with no offers draws none of them - but `refresh` is not
 *   unreachable, it is unreachable FOR THAT COMPONENT, which is the arrangement working as designed
 *   rather than a defect in the design. A validator that walked conditions would warn on every
 *   sparse part and the list would be noise on the surface it is meant to make trustworthy.
 *   CONDITION-AWARENESS IS HONEST SCOPE FOR PHASE 5. When the action registry (plan 1.3) lands with
 *   each action's required context, "reachable only while the offers section has content" becomes a
 *   statement the validator can make precisely instead of a distinction it has to duck; the shape
 *   that will need is a per-action condition set intersected with the placement's own, and nothing
 *   in this module's signature has to change to carry it.
 *
 *   A COLLAPSED PLACEMENT COUNTS. Collapsing folds a section's body and leaves its heading, so the
 *   action is one click further away rather than gone. `hidden` is the setting that removes a piece
 *   from the arrangement, and it is the only one this check reads.
 *
 * ALSO PHASE 5, and deliberately not attempted here: plan 1.4's second reachability clause, "a
 * destructive action's confirmation intact". Destructiveness is a property the ACTION REGISTRY
 * declares, and there is no action registry - a manifest's `actions` are declared name strings and
 * nothing more (see the header of `registry.ts`). Inventing a destructive-action list here would be
 * this module asserting a fact about the application that no module owns yet.
 */
import type { LayoutDocument } from "./document";
import { layoutPlacements } from "./document";
import type { PieceManifest } from "./registry";
import { validatorIssue, type ValidatorIssue } from "./validatorIssues";

/**
 * The minimum a reachability check needs of a registry.
 *
 * Declared structurally rather than imported as `PieceRegistry`, for the reason `document.ts`
 * declares `PieceLookup`: a test hands this a two-line stub, and the real registry satisfies it
 * without either module importing the other's implementation.
 */
export interface PieceCatalogue {
  get(id: string): PieceManifest | undefined;
  list(): readonly PieceManifest[];
}

/** Why an action is out of reach, which is what decides the fix. */
export type UnreachableReason = "unplaced" | "hidden";

/**
 * Every action the registry declares that the document does not expose.
 *
 * Ordered by action id, so two runs over one document produce the same list in the same sequence.
 */
export function validateReachability(
  document: LayoutDocument,
  registry: PieceCatalogue,
): ValidatorIssue[] {
  /** action id -> the pieces that declare it, in registration order. */
  const declaredBy = new Map<string, string[]>();
  for (const manifest of registry.list()) {
    for (const action of manifest.actions) {
      const pieces = declaredBy.get(action);
      if (pieces) pieces.push(manifest.id);
      else declaredBy.set(action, [manifest.id]);
    }
  }

  /** Pieces this document places at all, and pieces it places somewhere not hidden. */
  const placed = new Set<string>();
  const exposed = new Set<string>();
  for (const visit of layoutPlacements(document)) {
    placed.add(visit.node.piece);
    if (visit.node.hidden !== true) exposed.add(visit.node.piece);
  }

  const issues: ValidatorIssue[] = [];
  for (const action of [...declaredBy.keys()].sort()) {
    const pieces = declaredBy.get(action) ?? [];
    if (pieces.some((piece) => exposed.has(piece))) continue;

    // Placed-somewhere but hidden everywhere is a different fix from never placed, and the owner
    // can act on the difference: one is a setting on a placement, the other is a piece to drop in.
    const reason: UnreachableReason = pieces.some((piece) => placed.has(piece))
      ? "hidden"
      : "unplaced";

    issues.push(
      validatorIssue(
        "action-unreachable",
        { kind: "action", id: action },
        { detail: { reason, declaredBy: pieces.join(" ") } },
      ),
    );
  }
  return issues;
}
