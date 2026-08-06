/**
 * STRUCTURE: the two things plan 1.4 asks for that the document alone cannot answer.
 *
 * `document.ts`'s `validateLayout` already reports everything checkable from the tree by itself - a
 * duplicate id, an empty slot, an unknown mode, a splitter pointing at a slot that left, two REGIONS
 * scrolling the axis their parent stacks them along. This module is deliberately the small remainder:
 * the checks that need the REGISTRY, because they compare what the arrangement gives a piece against
 * what the piece's own manifest says it needs. Nothing here restates a check `validateLayout` makes.
 *
 * TWO CHECKS, and then three things that are deliberately absent.
 *
 * 1. A PIECE BELOW ITS MINIMUM. Only where BOTH SIDES STATE A NUMBER. A manifest carries a min only
 *    where the source it transcribes states one (`registry.ts`: "Absent beats invented"), and a
 *    region carries a min only where `lib/workspaceColumns` states one, so the check runs on the
 *    intersection and is silent everywhere else. No default is invented to make it fire: a
 *    validator that guessed a floor would report the guess, not the design.
 *
 *    Which number is the floor: `AxisSize.min` is stated in the PARENT region's own terms - a
 *    column's `min` inside a row band is a width - so the nearest enclosing node that states a min
 *    on the axis in question is the one that governs, and an outer floor cannot rescue an inner one.
 *    CONDITIONAL FLOORS COUNT, and the smallest wins: the sourcing column's floor is 300 normally
 *    and 220 under `workspace.sparse-sourcing`, so a piece needing 260 there is a real warning about
 *    a real state the reader reaches, and the condition travels in `detail.condition` so the row
 *    says when.
 *
 * 2. A SCROLL CONFLICT A PLACEMENT CAUSES. `validateLayout` reads scroll off REGIONS, which is all
 *    the document states; a PIECE's scroll ownership lives in its manifest (the offers table and the
 *    provenance ledger each own a horizontal axis) and no structural check can see it. Two shapes
 *    are reported and one similar-looking shape deliberately is not:
 *
 *      TWO SIBLING PIECES owning the axis their region stacks them along - the same conflict
 *      `validateLayout` reports between regions, one level down.
 *
 *      A PIECE OWNING AN AXIS ITS OWN REGION ALSO OWNS, on any axis. Nested scrollers on one axis
 *      are the shape where the outer container decides which of them the wheel reaches and the
 *      arrangement cannot predict which.
 *
 *      NOT REPORTED: two pieces owning an axis their region does NOT stack along. The offers table
 *      and the provenance ledger both scroll sideways inside one vertical column and that is the
 *      shipped design - four columns of named facts do not fit a 300px column, and each table
 *      scrolling itself is what keeps its width off the column's. This is the same judgement
 *      `validateLayout` makes about three columns each owning a vertical scrollbar side by side.
 *
 * WHAT IS NOT HERE, deliberately:
 *
 *   OVERLAPPING PIECES cannot be expressed. A slot holds exactly one node (`LayoutSlot.content`), so
 *   the only overlap a document can describe is a `stack` region, where overlap is the mode's whole
 *   purpose - a preview stage over its empty state. There is nothing to report.
 *
 *   FOCUS-ORDER COHERENCE is already an engine invariant, held by `engineInvariants.test.tsx`'s
 *   "focus order follows document order" suite, which renders a document and walks the real tab
 *   order rather than reasoning about it. A pure function over the document could only restate the
 *   tree order it was handed; the invariant that matters is that the RENDERER preserves it, and that
 *   is what that suite measures. Duplicating it here would be a second, weaker copy.
 *
 *   REGION-versus-REGION scroll conflicts are `validateLayout`'s, and are not re-derived.
 */
import type {
  AxisSize,
  LayoutDocument,
  LayoutRegion,
  PiecePlacement,
  RegionLayoutMode,
  ScrollAxis,
} from "./document";
import { layoutRegions, walkLayout } from "./document";
import type { PieceManifest } from "./registry";
import { validatorIssue, type ValidatorIssue } from "./validatorIssues";

/** The minimum a structural check needs of a registry: resolve a piece id to its manifest. */
export interface PieceManifestLookup {
  get(id: string): PieceManifest | undefined;
}

type SizeAxis = "width" | "height";

/** The axis a region stacks its children along. A stack has none. */
function mainAxis(mode: RegionLayoutMode): "vertical" | "horizontal" | null {
  if (mode === "column") return "vertical";
  if (mode === "row") return "horizontal";
  return null;
}

/** Which of a child's two dimensions this parent's `min` is stated in. */
function parentSizeAxis(mode: RegionLayoutMode): SizeAxis | null {
  if (mode === "row") return "width";
  if (mode === "column") return "height";
  // A stack sizes its children on neither axis: they share the footprint, and `AxisSize` is
  // explicitly "a size on the parent region's MAIN axis", which a stack does not have.
  return null;
}

/** The smallest floor a size states on its own axis, base and conditional, or `null` for none. */
function smallestStatedMin(size: AxisSize | undefined): { min: number; condition?: string } | null {
  if (!size) return null;
  let best: { min: number; condition?: string } | null =
    typeof size.min === "number" ? { min: size.min } : null;
  for (const [condition, override] of Object.entries(size.when ?? {})) {
    if (typeof override.min !== "number") continue;
    if (best === null || override.min < best.min) best = { min: override.min, condition };
  }
  return best;
}

function ownsAxis(scroll: ScrollAxis | undefined, axis: "vertical" | "horizontal"): boolean {
  return scroll === "both" || scroll === axis;
}

/** The axis a piece's manifest says it scrolls, or `null` when it owns nothing. */
function pieceScrollAxis(manifest: PieceManifest | undefined): "vertical" | "horizontal" | null {
  if (!manifest || !manifest.scroll.owns) return null;
  return manifest.scroll.axis ?? null;
}

/* -------------------------------------------------------------------------- */

/**
 * Everything the registry knows that the document contradicts.
 *
 * Hidden placements are skipped throughout: a piece that is not on screen is neither too small nor
 * in a scroll fight with anything.
 */
export function validateStructure(
  document: LayoutDocument,
  registry: PieceManifestLookup,
): ValidatorIssue[] {
  return [...minimumSizeIssues(document, registry), ...scrollIssues(document, registry)];
}

/* -------------------------------------------------------------------------- */
/*  1. a piece below its minimum                                               */
/* -------------------------------------------------------------------------- */

function minimumSizeIssues(
  document: LayoutDocument,
  registry: PieceManifestLookup,
): ValidatorIssue[] {
  const issues: ValidatorIssue[] = [];

  // The chain of ancestors, so the nearest node stating a floor on each axis can be found without
  // re-walking the tree per placement. `walkLayout` yields document order, so a node's ancestors are
  // always already on the stack.
  const parentRegion = new Map<string, LayoutRegion>();
  for (const visit of layoutRegions(document)) {
    for (const slot of visit.node.slots) {
      const content = slot.content;
      if (content) parentRegion.set(content.id, visit.node);
    }
  }

  for (const visit of walkLayout(document)) {
    if (visit.node.kind !== "placement") continue;
    const placement: PiecePlacement = visit.node;
    if (placement.hidden === true) continue;

    const manifest = registry.get(placement.piece);
    if (!manifest) continue;

    for (const axis of ["width", "height"] as const) {
      const needed = axis === "width" ? manifest.minWidth : manifest.minHeight;
      if (typeof needed !== "number") continue;

      const floor = nearestFloor(placement, parentRegion, axis);
      if (!floor || floor.min >= needed) continue;

      issues.push(
        validatorIssue(
          "piece-below-minimum",
          { kind: "placement", id: placement.id },
          {
            path: visit.path,
            detail: {
              axis,
              piece: placement.piece,
              minimum: needed,
              floor: floor.min,
              from: floor.from,
              ...(floor.condition ? { condition: floor.condition } : {}),
            },
          },
        ),
      );
    }
  }
  return issues;
}

interface Floor {
  min: number;
  /** The node whose size states this floor. */
  from: string;
  condition?: string;
}

/**
 * The floor that actually governs this placement on one axis: the nearest node that states one.
 *
 * Walks outward from the placement itself. A node's own `size.min` is only a floor on this axis when
 * its PARENT stacks along that axis, which is what `parentSizeAxis` decides; a node whose parent
 * sizes the other axis is skipped rather than mis-read.
 */
function nearestFloor(
  placement: PiecePlacement,
  parentRegion: ReadonlyMap<string, LayoutRegion>,
  axis: SizeAxis,
): Floor | null {
  let node: { id: string; size?: AxisSize } = placement;
  let parent = parentRegion.get(placement.id);
  const seen = new Set<string>([placement.id]);

  while (parent) {
    if (parentSizeAxis(parent.mode) === axis) {
      const stated = smallestStatedMin(node.size);
      if (stated) return { min: stated.min, from: node.id, condition: stated.condition };
    }
    if (seen.has(parent.id)) break;
    seen.add(parent.id);
    node = parent;
    parent = parentRegion.get(parent.id);
  }
  return null;
}

/* -------------------------------------------------------------------------- */
/*  2. a scroll conflict a placement causes                                    */
/* -------------------------------------------------------------------------- */

function scrollIssues(
  document: LayoutDocument,
  registry: PieceManifestLookup,
): ValidatorIssue[] {
  const issues: ValidatorIssue[] = [];

  for (const visit of layoutRegions(document)) {
    const region = visit.node;
    // One pass over the slots rather than a map-filter-filter chain and a second loop over the
    // result: the question is only ever "which axis does this child own", and a region's slots are
    // walked for every region of every document the editor validates on every keystroke.
    const byAxis = new Map<"vertical" | "horizontal", string[]>();
    for (const slot of region.slots) {
      const child = slot.content;
      if (child?.kind !== "placement" || child.hidden === true) continue;
      const axis = pieceScrollAxis(registry.get(child.piece));
      if (!axis) continue;
      const owners = byAxis.get(axis);
      if (owners) owners.push(child.id);
      else byAxis.set(axis, [child.id]);
    }
    if (byAxis.size === 0) continue;

    const stacked = mainAxis(region.mode);
    for (const [axis, owners] of byAxis) {
      // A stack has no main axis, so - exactly as `validateLayout` reasons - a collision on EITHER
      // axis counts there, because the children share one footprint.
      const collides = stacked === null || stacked === axis;
      if (collides && owners.length > 1) {
        issues.push(
          validatorIssue(
            "piece-scroll-conflict",
            { kind: "region", id: region.id },
            {
              path: visit.path,
              detail: { axis, owners: [...owners].sort().join(" "), shape: "siblings" },
            },
          ),
        );
      }
      // Nesting is a conflict on ANY axis, main or not: the region and the piece inside it both
      // scrolling one direction is the shape where the outer container decides which of them the
      // wheel reaches, and no arrangement can say which.
      if (ownsAxis(region.scroll, axis)) {
        issues.push(
          validatorIssue(
            "piece-scroll-conflict",
            { kind: "region", id: region.id },
            {
              path: visit.path,
              detail: { axis, owners: [...owners].sort().join(" "), shape: "nested" },
            },
          ),
        );
      }
    }
  }
  return issues;
}
