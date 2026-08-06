/**
 * THE EDIT OPERATIONS: one layout document in, the next one out, and nothing else.
 *
 * Phase 3's editor is a surface over these four functions. They are the whole of what an arrangement
 * edit MEANS - move a placement, collapse it, hide it, resize a region - stated as pure data
 * transforms so that the drag handles (3B) and the property panel (3C) contain no arrangement logic
 * of their own, and so the commit pipeline (Phase 4) can replay an edit outside a browser.
 *
 * FOUR PROPERTIES THIS MODULE EXISTS TO GUARANTEE. `editOperations.test.ts` asserts each of them
 * across a battery of documents, the shipped one and several deliberately odd ones.
 *
 *   A NEW DOCUMENT, ALWAYS. Nothing here mutates its input, not even a nested slot array. The
 *   returned document shares every untouched subtree with the input by reference - which is what
 *   keeps a drag cheap and keeps React's identity rules (`LayoutRenderer`: identity follows the
 *   document) intact for the parts of the tree the edit did not reach.
 *
 *   AN UNKNOWN REF IS A NO-OP. Every operation that cannot find what it was pointed at returns the
 *   INPUT DOCUMENT, by reference. Warn, never block (plan decision 3): bad input degrades to nothing
 *   happening, and nothing here throws for a data problem. The same is true of a ref that is
 *   ambiguous - a piece id placed three times names no single placement, so it names none.
 *
 *   NEVER WORSE THAN WHAT AROSE. `validateLayout` must not report MORE of any issue code after an
 *   operation than before it. That is a stronger promise than "the result is valid", because an
 *   operation is often applied to a document that already has an issue (an owner is mid-edit, or a
 *   layout came from a newer build), and the promise that matters there is that editing does not
 *   make it worse. Two consequences are visible in the code below: a slot LEAVES ITS REGION WITH ITS
 *   CONTENT rather than being emptied (an emptied slot is a fresh `orphan-slot`), and a splitter that
 *   named the departing slot is PRUNED (a splitter pointing at a slot that left is a fresh
 *   `splitter-unknown-slot`).
 *
 *   SERIALISABLE OUT, SERIALISABLE IN. Every result survives `JSON.parse(JSON.stringify(...))`
 *   unchanged: no `undefined`-valued keys are written, and a setting turned OFF is DELETED rather
 *   than written as `false`. A committed layout travels to source and back through exactly that round
 *   trip, and the shipped default document sets none of these fields - so neither does an edit that
 *   returns a placement to its default state.
 *
 * WHAT IS NOT HERE, deliberately. No React, no storage, no registry: a piece id that no registry
 * knows is moved exactly like one it does, because `validateLayout` is the module that reports an
 * unknown piece and an editor that refused to move one would be refusing to edit a layout an older
 * build wrote. No region or slot is created or destroyed either - 3B moves content between the
 * regions a document already has; composing NEW regions is the composer's job (plan Phase 5).
 *
 * THE ONE IMPORT OUTSIDE THIS FOLDER is `components/typography.ts`, and it is a DATA table rather
 * than a component: `TYPOGRAPHY_SCALE` is the closed set of role names, and `setPlacementStyleRole`
 * below refuses anything that is not one of them. Naming the vocabulary at the operation is the only
 * place a refusal can be complete - a picker that offered the right options would still let a
 * hand-written document, an older build or a bad merge introduce a role that names nothing.
 */
import { TYPOGRAPHY_SCALE, type TypographyRoleName } from "../components/typography";
import {
  findRegion,
  layoutPlacements,
  layoutSlots,
  type AxisSize,
  type AxisSizeOverride,
  type LayoutDocument,
  type LayoutRegion,
  type LayoutSlot,
  type PiecePlacement,
} from "./document";

/* -------------------------------------------------------------------------- */
/*  naming a placement                                                         */
/* -------------------------------------------------------------------------- */

/**
 * Which placement an operation is about.
 *
 * A bare string is read as a PLACEMENT ID first and as a PIECE ID second, because a placement id is
 * the exact name and a piece id is the one an editing surface has when a piece is placed once (the
 * status bar, the search box). The explicit forms exist for the case where the two vocabularies
 * collide, and for a caller that wants to be told it guessed wrong rather than served a fallback.
 */
export type PlacementRef = string | { placement: string } | { piece: string };

interface ResolvedPlacement {
  placement: PiecePlacement;
  /** The slot holding it, and the region holding that slot. */
  slotId: string;
  regionId: string;
}

/**
 * The one placement this ref names, or `null`.
 *
 * A PIECE id that is placed more than once resolves to nothing at all. The three CAD modules are
 * three placements of one piece, so `"workspace.cad-asset-module"` cannot mean any of them - and
 * moving "one of the three, whichever comes first" is not an edit anybody asked for.
 */
function resolvePlacement(
  document: LayoutDocument,
  ref: PlacementRef,
): ResolvedPlacement | null {
  const visits = layoutPlacements(document);
  const byPlacementId = (id: string) => visits.find((visit) => visit.node.id === id);
  const byPieceId = (piece: string) => {
    const matches = visits.filter((visit) => visit.node.piece === piece);
    return matches.length === 1 ? matches[0] : undefined;
  };

  const visit =
    typeof ref === "string"
      ? byPlacementId(ref) ?? byPieceId(ref)
      : "placement" in ref
        ? byPlacementId(ref.placement)
        : byPieceId(ref.piece);

  if (!visit || !visit.slotId || !visit.parentRegionId) return null;
  return { placement: visit.node, slotId: visit.slotId, regionId: visit.parentRegionId };
}

/* -------------------------------------------------------------------------- */
/*  rebuilding the tree                                                        */
/* -------------------------------------------------------------------------- */

/**
 * Rebuild every region of a document bottom-up, replacing only what the transform changes.
 *
 * The transform is handed a region whose own children have already been rebuilt, and returns either
 * that same object (nothing to do here) or a new one. Returning the same reference is how identity
 * propagates: a document no transform touched comes back BY REFERENCE, which is what makes a no-op
 * edit free and a React re-render avoidable.
 *
 * A DOCUMENT THAT IS NOT A TREE IS NOT EDITED. A document arrives from JSON, from an editor mid-drag
 * or from a bad merge, and one where a region is reachable twice - its own descendant, or one object
 * placed in two slots - is not a tree. Two things follow, and the second is why the first is not
 * enough. First, the walk must not recurse into a region it has already rebuilt, or it hangs the
 * editor rather than degrading. Second, it must ABANDON the edit and hand back the input document:
 * rebuilding one of the two appearances forks the shared object into two distinct nodes under one id,
 * which is a `duplicate-id` the input did not have - an edit that made the document worse, which is
 * the one thing these operations promise never to do. So the arrangement is left exactly as it was
 * found, and `validateLayout` stays the place a broken document is reported.
 */
function rebuildRegions(
  document: LayoutDocument,
  transform: (region: LayoutRegion) => LayoutRegion,
): LayoutDocument {
  const seen = new Set<object>();
  let shared = false;

  const walk = (region: LayoutRegion): LayoutRegion => {
    if (seen.has(region)) {
      shared = true;
      return region;
    }
    seen.add(region);
    let changed = false;
    const slots = region.slots.map((slot) => {
      const content = slot.content;
      if (!content || content.kind !== "region") return slot;
      const next = walk(content);
      if (next === content) return slot;
      changed = true;
      return { ...slot, content: next };
    });
    return transform(changed ? { ...region, slots } : region);
  };

  const root = walk(document.root);
  if (shared || root === document.root) return document;
  return { ...document, root };
}

/* -------------------------------------------------------------------------- */
/*  1. move a placement                                                        */
/* -------------------------------------------------------------------------- */

/** Where in a region's slot order a moved slot lands. */
function clampIndex(index: number, length: number): number {
  if (!Number.isFinite(index)) return length;
  return Math.max(0, Math.min(length, Math.trunc(index)));
}

/**
 * A region with one slot gone, and any splitter that named it gone with it.
 *
 * PRUNING THE SPLITTER IS NOT TIDINESS. A `SplitterSpec` is a contract between two of a region's OWN
 * slots; one naming a slot that has left is exactly the `splitter-unknown-slot` error the validator
 * reports, so leaving it would make an edit produce a document the validator likes less than the one
 * it was handed. Dropping a constraint can only ever remove issues.
 */
function withoutSlot(region: LayoutRegion, placement: PiecePlacement, slotId: string): LayoutRegion {
  const slots = region.slots.filter((slot) => slot.content !== placement);
  if (slots.length === region.slots.length) return region;
  const next: LayoutRegion = { ...region, slots };
  const splitters = (region.splitters ?? []).filter(
    (splitter) => !splitter.between.includes(slotId),
  );
  if (splitters.length !== (region.splitters ?? []).length) {
    if (splitters.length > 0) next.splitters = splitters;
    else delete next.splitters;
  }
  return next;
}

function withSlotAt(region: LayoutRegion, slot: LayoutSlot, index: number): LayoutRegion {
  const slots = [...region.slots];
  slots.splice(clampIndex(index, slots.length), 0, slot);
  return { ...region, slots };
}

/**
 * Move a placement to another slot's position, or to another region, or elsewhere in its own.
 *
 * THE SLOT TRAVELS WITH THE CONTENT. A slot holds exactly one node, so "put this placement where
 * that one is" cannot mean "into that slot" without evicting whatever is already there. What moves
 * is therefore the placement TOGETHER WITH ITS OWN SLOT: the source region loses that slot, the
 * destination region gains it, no slot is emptied, no slot is invented, and every slot id in the
 * document is still exactly the set it was. That is what keeps the operation free of the two issues
 * the alternatives create - an `orphan-slot` where the placement used to be, or a second placement
 * displaced to nowhere.
 *
 * `targetSlotId` may name either:
 *
 *   A SLOT - the moved slot lands AT that slot's position, pushing it down. This is the drop-above
 *   gesture 3B will produce, and the reason the anchor is resolved AFTER the removal: dragging a
 *   section down past two of its siblings has to land it past two of its siblings.
 *
 *   A REGION - the moved slot lands at the END of that region's slots, which is the drop-into-empty
 *   -space gesture and the only way to move a placement into a region that has no slots left to
 *   anchor against.
 *
 * `targetIndex`, when given, WINS over the anchor and is read as the index in the destination
 * region's FINAL slot order, clamped into it. Out-of-range is clamped rather than refused; a drag
 * that overshoots the last section means the last position.
 *
 * A NO-OP (the input document, by reference) when: the ref names no single placement, the target
 * names neither a slot nor a region, or the target is the placement's own slot with no index given.
 */
export function movePlacement(
  document: LayoutDocument,
  ref: PlacementRef,
  targetSlotId: string,
  targetIndex?: number,
): LayoutDocument {
  const resolved = resolvePlacement(document, ref);
  if (!resolved) return document;
  // Pointed at its own slot with nothing else said: there is no position being asked for.
  if (targetSlotId === resolved.slotId && targetIndex === undefined) return document;

  const targetSlot = layoutSlots(document).find((visit) => visit.node.id === targetSlotId);
  const destinationId = targetSlot?.parentRegionId ?? targetSlotId;
  const destination = findRegion(document, destinationId);
  if (!destination) return document;

  const source = findRegion(document, resolved.regionId);
  const movedSlot = source?.slots.find((slot) => slot.content === resolved.placement);
  if (!source || !movedSlot) return document;

  const sameRegion = destinationId === resolved.regionId;
  // Where the anchor sits once the moved slot is out of the way, so a downward drag counts the
  // siblings it passed rather than the ones it started above.
  const anchorIn = (slots: readonly LayoutSlot[]): number => {
    if (!targetSlot) return slots.length;
    const at = slots.findIndex((slot) => slot.id === targetSlotId);
    return at >= 0 ? at : slots.length;
  };

  // A malformed document can carry two regions under one id. Both the removal and the insertion
  // happen exactly once, to the first region that matches, so a duplicate id cannot turn one move
  // into two placements or two removals.
  let removed = false;
  let inserted = false;

  return rebuildRegions(document, (region) => {
    if (sameRegion) {
      if (removed || region.id !== destinationId) return region;
      const remaining = region.slots.filter((slot) => slot.content !== resolved.placement);
      if (remaining.length === region.slots.length) return region;
      removed = true;
      inserted = true;
      const index = targetIndex ?? anchorIn(remaining);
      const slots = [...remaining];
      slots.splice(clampIndex(index, slots.length), 0, movedSlot);
      return { ...region, slots };
    }
    if (!removed && region.id === resolved.regionId) {
      const next = withoutSlot(region, resolved.placement, resolved.slotId);
      if (next !== region) removed = true;
      return next;
    }
    if (!inserted && region.id === destinationId) {
      inserted = true;
      return withSlotAt(region, movedSlot, targetIndex ?? anchorIn(region.slots));
    }
    return region;
  });
}

/* -------------------------------------------------------------------------- */
/*  2. per-placement settings                                                  */
/* -------------------------------------------------------------------------- */

/**
 * Write one of a placement's boolean settings, or REMOVE it when it is turned off.
 *
 * `collapsed: false` and no `collapsed` at all mean the same thing to the renderer, and the shipped
 * default document writes neither. So turning a setting off deletes the key: a committed document
 * stays the smallest description of the arrangement it is, and a placement returned to its default
 * is byte-identical to one that was never touched.
 */
/**
 * Swap one placement object for another, wherever in the tree it sits.
 *
 * By object identity, not by id: a document carrying the same placement id twice gets ONE of them
 * edited - the one that was resolved - rather than both.
 */
function replacePlacement(
  document: LayoutDocument,
  target: PiecePlacement,
  next: PiecePlacement,
): LayoutDocument {
  let done = false;
  return rebuildRegions(document, (region) => {
    if (done) return region;
    let changed = false;
    const slots = region.slots.map((slot) => {
      if (slot.content !== target) return slot;
      changed = true;
      done = true;
      return { ...slot, content: next };
    });
    return changed ? { ...region, slots } : region;
  });
}

function setPlacementFlag(
  document: LayoutDocument,
  ref: PlacementRef,
  key: "collapsed" | "hidden",
  value: boolean,
): LayoutDocument {
  const resolved = resolvePlacement(document, ref);
  if (!resolved) return document;
  if ((resolved.placement[key] === true) === value) return document;

  const next: PiecePlacement = { ...resolved.placement };
  if (value) next[key] = true;
  else delete next[key];

  return replacePlacement(document, resolved.placement, next);
}

/** Collapse or expand THIS appearance of a piece. */
export function setPlacementCollapsed(
  document: LayoutDocument,
  ref: PlacementRef,
  value: boolean,
): LayoutDocument {
  return setPlacementFlag(document, ref, "collapsed", value);
}

/**
 * Take THIS appearance of a piece off the screen, or put it back.
 *
 * Hiding is not deleting, and that is the point: the placement keeps its id, its slot and its
 * position, so the piece comes back exactly where it was and the validator still counts it when it
 * asks which pieces this layout places.
 */
export function setPlacementHidden(
  document: LayoutDocument,
  ref: PlacementRef,
  value: boolean,
): LayoutDocument {
  return setPlacementFlag(document, ref, "hidden", value);
}

/* -------------------------------------------------------------------------- */
/*  3. region size                                                             */
/* -------------------------------------------------------------------------- */

/**
 * A region's floor as a share of its parent's main axis.
 *
 * Not zero. `fraction: 0` is a region with no width that no pointer can find and no splitter can
 * drag back out, which is a layout an editor cannot undo by editing - so the bound exists in the
 * operation rather than in a warning. Hiding a piece is what `setPlacementHidden` is for.
 */
export const MIN_REGION_FRACTION = 0.01;

/**
 * What to change about a region's size. A `null` CLEARS the constraint; an absent key leaves it
 * alone. Those are different requests and the patch keeps them different.
 */
export interface RegionSizePatch {
  min?: number | null;
  preferred?: number | null;
  fraction?: number | null;
}

export interface SetRegionSizeOptions {
  /**
   * Edit the size the region takes UNDER A NAMED CONDITION (`AxisSize.when`) rather than its resting
   * one - which is how the three columns' sparse-sourcing geometry is edited, since both sets live
   * in the document at once and a render picks between them.
   */
  condition?: string;
}

/**
 * One size field, bounded by what the MODEL says the field is.
 *
 * `fraction` is a share, so it lives in `[MIN_REGION_FRACTION, 1]`. `min` and `preferred` are
 * pixels, so they cannot be negative. Anything that is not a finite number - `NaN` from an empty
 * input box, an `Infinity` from a division - leaves the field as it was: warn, never block means the
 * edit degrades to no change, never to a document carrying a size nothing can resolve.
 */
function patchField(
  current: number | undefined,
  requested: number | null | undefined,
  kind: "fraction" | "pixels",
): number | undefined {
  if (requested === undefined) return current;
  if (requested === null) return undefined;
  if (typeof requested !== "number" || !Number.isFinite(requested)) return current;
  return kind === "fraction"
    ? Math.min(1, Math.max(MIN_REGION_FRACTION, requested))
    : Math.max(0, requested);
}

/** The three numbers after the patch, in the order the model states them. */
function patchedNumbers(current: AxisSizeOverride | undefined, patch: RegionSizePatch): AxisSizeOverride {
  const min = patchField(current?.min, patch.min, "pixels");
  let preferred = patchField(current?.preferred, patch.preferred, "pixels");
  const fraction = patchField(current?.fraction, patch.fraction, "fraction");
  // A preferred size below the minimum is not a size anything can honour, so the minimum wins. The
  // model states the relationship; the operation keeps it rather than reporting it later.
  if (min != null && preferred != null && preferred < min) preferred = min;
  const next: AxisSizeOverride = {};
  if (min != null) next.min = min;
  if (preferred != null) next.preferred = preferred;
  if (fraction != null) next.fraction = fraction;
  return next;
}

/**
 * A size reduced to the values it MEANS, for comparing two of them.
 *
 * Key order is not meaning: the shipped document happens to write the sourcing column's sparse
 * override as `{ fraction, min }` and this module builds one as `{ min, fraction }`, and a textual
 * comparison would call those two different sizes and rewrite the document for nothing. Compared
 * positionally instead, so only a changed NUMBER counts as a change.
 */
function canonicalSize(size: AxisSize | undefined): string {
  if (!size) return "";
  const parts: unknown[] = [size.min, size.preferred, size.fraction, size.grow];
  const when = size.when ?? {};
  for (const key of Object.keys(when).sort()) {
    parts.push(key, when[key]?.min, when[key]?.preferred, when[key]?.fraction);
  }
  return JSON.stringify(parts);
}

/**
 * Adjust a region's size constraints, at rest or under one of its named conditions.
 *
 * A size that ends up carrying nothing at all is REMOVED rather than left as `{}`: an empty size
 * object and no size object mean the same thing to the renderer, and only one of them survives a
 * round trip to source looking like what was meant.
 *
 * A NO-OP (the input document, by reference) when: no region carries `regionId`, or the patch asks
 * for what is already there.
 */
export function setRegionSize(
  document: LayoutDocument,
  regionId: string,
  patch: RegionSizePatch,
  options?: SetRegionSizeOptions,
): LayoutDocument {
  const region = findRegion(document, regionId);
  if (!region) return document;

  const current = region.size;
  const condition = options?.condition;
  let nextSize: AxisSize;

  if (condition) {
    const when: Record<string, AxisSizeOverride> = { ...(current?.when ?? {}) };
    const patched = patchedNumbers(when[condition], patch);
    if (Object.keys(patched).length > 0) when[condition] = patched;
    else delete when[condition];
    nextSize = {};
    if (current?.min != null) nextSize.min = current.min;
    if (current?.preferred != null) nextSize.preferred = current.preferred;
    if (current?.fraction != null) nextSize.fraction = current.fraction;
    if (current?.grow !== undefined) nextSize.grow = current.grow;
    if (Object.keys(when).length > 0) nextSize.when = when;
  } else {
    nextSize = patchedNumbers(current, patch);
    if (current?.grow !== undefined) nextSize.grow = current.grow;
    if (current?.when !== undefined) nextSize.when = current.when;
  }

  const empty = Object.keys(nextSize).length === 0;
  // An edit that changed no number hands back the document it was given.
  if (canonicalSize(empty ? undefined : nextSize) === canonicalSize(current)) return document;

  let done = false;
  return rebuildRegions(document, (candidate) => {
    if (done || candidate.id !== regionId) return candidate;
    done = true;
    const next: LayoutRegion = { ...candidate };
    if (empty) delete next.size;
    else next.size = nextSize;
    return next;
  });
}

/* -------------------------------------------------------------------------- */
/*  4. a placement's text roles                                                */
/* -------------------------------------------------------------------------- */

/**
 * THE TWO SCOPES, and which one this operation is.
 *
 * Plan 1.5 gives a style edit two scopes and makes the wider one the default: "everywhere (class)"
 * against "only here recorded as a tracked exception". The wider scope IS ALREADY BUILT AND IS NOT
 * REBUILT HERE. A role is a class in `styles/index.css` fed by the tokens in `lib/devTokens.ts`, so
 * editing the role everywhere is what the Design panel's Tokens rows do, and reshaping one element's
 * box everywhere it appears is what the Box tab does against a `data-dev-role`. Both write the same
 * override draft, both already save back to source, and a second editor over the same tokens would
 * be a second answer to one question.
 *
 * What had no home is the NARROW scope: this placement, and no other appearance of the same piece.
 * `PiecePlacement.styleRoles` is where the document holds it, and this is the only function that
 * writes it. There is no separate ledger of exceptions, because the document IS the ledger -
 * `validateDocument`'s provenance layer reads `styleRoles` straight back out as a
 * `style-role-exception` info row, so an exception is tracked by virtue of existing rather than by
 * anybody remembering to record it.
 *
 * A ROLE, NOT A STRING. Both the role being overridden and the role it takes must name an entry in
 * `TYPOGRAPHY_SCALE`; anything else is a no-op returning the input document, warn-never-block style.
 * The scale is the whole vocabulary of the type system and a role outside it resolves to no class at
 * all, so accepting one would write a document that silently draws nothing different.
 */
export const STYLE_ROLE_NAMES: readonly TypographyRoleName[] = Object.keys(
  TYPOGRAPHY_SCALE,
) as TypographyRoleName[];

/** True when this string names a role the type system defines. */
export function isStyleRole(name: string): name is TypographyRoleName {
  return Object.prototype.hasOwnProperty.call(TYPOGRAPHY_SCALE, name);
}

/**
 * Give THIS appearance of a piece a different text role, or drop the exception.
 *
 * `becomes` of `null` clears the entry, and clearing the last entry DELETES `styleRoles` outright
 * rather than leaving `{}` behind - the same serialisable-out rule the boolean settings follow, and
 * the reason `validateDocument` can treat an empty object as "no exception" without either module
 * knowing about the other.
 *
 * A NO-OP (the input document, by reference) when: either name is not a role, the ref names no
 * single placement, or the placement already holds exactly what was asked for.
 */
export function setPlacementStyleRole(
  document: LayoutDocument,
  ref: PlacementRef,
  role: string,
  becomes: string | null,
): LayoutDocument {
  if (!isStyleRole(role)) return document;
  if (becomes !== null && !isStyleRole(becomes)) return document;

  const resolved = resolvePlacement(document, ref);
  if (!resolved) return document;

  const current = resolved.placement.styleRoles;
  if ((current?.[role] ?? null) === becomes) return document;

  const roles: Record<string, string> = { ...(current ?? {}) };
  if (becomes === null) delete roles[role];
  else roles[role] = becomes;

  const next: PiecePlacement = { ...resolved.placement };
  if (Object.keys(roles).length > 0) next.styleRoles = roles;
  else delete next.styleRoles;

  return replacePlacement(document, resolved.placement, next);
}
