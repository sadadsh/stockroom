/**
 * THE LAYOUT DOCUMENT: the arrangement of a surface, as data rather than as JSX.
 *
 * Today the workspace's three bands, its three columns and every section in them are hardcoded
 * composition. A builder cannot edit code; it can edit a document. So the arrangement becomes a
 * versioned, serialisable tree of three node kinds - REGION (a container with a layout mode, size
 * constraints and splitter behaviour), SLOT (an ordered position inside a region) and PLACEMENT (a
 * reference to a registered piece plus the settings that apply to THAT appearance of it).
 *
 * Three properties this module exists to guarantee:
 *
 *   SERIALISABLE. Every field is a string, a number, a boolean, a plain object or an array. No
 *   functions, no class instances, no Maps, no Dates. `JSON.parse(JSON.stringify(document))` is the
 *   same document, byte for byte, because a committed layout travels to source and back through
 *   exactly that round trip.
 *
 *   PURE. Nothing here imports React, touches storage or reads the DOM. The renderer that turns a
 *   document into elements is somebody else's module; this one has to run in any JavaScript
 *   environment, including the commit pipeline that will one day write it back to disk.
 *
 *   WARN, NEVER BLOCK. `validateLayout` REPORTS. It returns typed issues and it never throws for a
 *   data problem - not for an unknown layout mode, not for a duplicate id, not for a placement
 *   naming a piece nobody registered. The owner decides what to do about an issue; a validator that
 *   refused would be the editor arguing with the person editing.
 *
 * The document deliberately holds NO runtime state. Whether the sourcing column is sparse, whether
 * a section has content, whether the reader has asked to see the blank ones - all of that is an
 * input to the renderer, not an edit to the document. Conditions are named here (as ids on a size
 * override or on a placement's visibility) and evaluated there, so the same committed document
 * describes a component with forty offers and a component with none.
 */

/** Bumped when a stored document can no longer be read by this module without translation. */
export const LAYOUT_SCHEMA_VERSION = 1;

/**
 * How a region arranges what is in it.
 *
 * `row` and `column` are the two flex directions the workspace already uses; `stack` is one slot
 * over another on the same footprint (a preview stage over its empty state, a dialog over its
 * host). The main axis follows the mode: horizontal for `row`, vertical for `column`, and for
 * `stack` there is none, which is why a stack cannot carry a splitter.
 */
export type RegionLayoutMode = "row" | "column" | "stack";

export const REGION_LAYOUT_MODES: readonly RegionLayoutMode[] = ["row", "column", "stack"];

/** Which axis a scrolling node owns. `both` owns each of them, and conflicts with either. */
export type ScrollAxis = "vertical" | "horizontal" | "both";

/**
 * A size on the parent region's MAIN axis, in the parent's own terms.
 *
 * `min` is pixels and is only ever set where the source states a number. `fraction` is the share of
 * the parent's main axis a node opens at. `grow` marks the node that absorbs whatever is left.
 */
export interface AxisSizeOverride {
  min?: number;
  preferred?: number;
  fraction?: number;
}

export interface AxisSize extends AxisSizeOverride {
  grow?: boolean;
  /**
   * The same three numbers under a NAMED RUNTIME CONDITION, keyed by condition id.
   *
   * This is how a constant document describes an arrangement whose geometry follows content. The
   * three-column band carries both of `lib/workspaceColumns`'s fraction sets and both of its
   * sourcing minimums; which set is in force is decided per render by the condition, and no edit is
   * made to the document either way.
   */
  when?: Readonly<Record<string, AxisSizeOverride>>;
}

/**
 * One draggable boundary between two of a region's slots.
 *
 * A splitter is a ZERO-SUM contract between exactly two neighbours - the maths lives in
 * `lib/workspaceColumns.moveSplitter` and is not restated here. What the document carries is which
 * two slots the handle sits between, how far a key press moves it, how thick the drawn line is
 * against how wide the grab area is, and where the result is remembered.
 */
export interface SplitterSpec {
  id: string;
  /** The two slot ids this handle moves between. A drag never touches a third. */
  between: readonly [string, string];
  /** Pixels per arrow-key press. */
  keyStep: number;
  /** The rendered rule. */
  lineThickness: number;
  /** The transparent hit region straddling the rule, which is what a pointer can actually catch. */
  grabWidth: number;
  /** Where a dragged position is remembered, or absent for a boundary that is not remembered. */
  persistenceKey?: string;
}

/** A container. Regions nest, and every leaf of the tree is a placement. */
export interface LayoutRegion {
  kind: "region";
  id: string;
  mode: RegionLayoutMode;
  /** The `data-dev-id` this region renders as, where the current arrangement gives it one. */
  devId?: string;
  size?: AxisSize;
  /** Set only where this region is the scroll owner. Most regions own nothing. */
  scroll?: ScrollAxis;
  splitters?: readonly SplitterSpec[];
  /** Only an explicitly declared free region accepts x/y placement edits. */
  positioning?: "free";
  /** Optional finite grid contract for placements assigned to a grid slot. */
  grid?: { columns: number; rows?: number };
  slots: readonly LayoutSlot[];
}

/** An ordered position inside a region. Order is the array's; a slot holds exactly one node. */
export interface LayoutSlot {
  kind: "slot";
  id: string;
  /** `null` is a slot with nothing in it, which validation reports and rendering skips. */
  content: LayoutNode | null;
}

/** Which runtime conditions put a placement on screen. Any one of them is enough. */
export interface PlacementVisibility {
  /**
   * Condition ids, evaluated by the renderer, never by the document.
   *
   * The sourcing column's five conditional sections are `[<the section has content>, <this
   * workstation has asked to see the blank ones>]`, which is exactly `fill[id] || showEmpty` in
   * `SourcingColumn.tsx`. An empty array is not written; a placement with no `visibility` always
   * draws.
   */
  anyOf: readonly string[];
}

/** A placement rendered once per item of a runtime collection, in the collection's own order. */
export interface PlacementRepeat {
  /** The collection's path, in the same vocabulary as a manifest's data needs. */
  over: string;
}

/**
 * A reference to a registered piece, plus everything that is true of THIS appearance of it.
 *
 * Per-placement settings are the difference between "the Documents section" and "the Documents
 * section, here, collapsed, at this width, with this heading role". The shipped default document
 * sets none of them - it is the current arrangement, and the current arrangement has no overrides -
 * but the fields exist because Phase 3 edits produce exactly these.
 */
export interface PiecePlacement {
  kind: "placement";
  id: string;
  /** The registered piece id. Validation reports one that no registry knows. */
  piece: string;
  collapsed?: boolean;
  hidden?: boolean;
  size?: AxisSize & { width?: number; height?: number };
  position?: { x: number; y: number };
  gridSlot?: { column: number; row: number };
  /** Style-role overrides scoped to this placement, keyed by the role this piece exposes. */
  styleRoles?: Readonly<Record<string, string>>;
  /** Parameters that distinguish sibling placements of one piece, e.g. which CAD asset kind. */
  params?: Readonly<Record<string, string | number | boolean>>;
  visibility?: PlacementVisibility;
  repeat?: PlacementRepeat;
}

export type LayoutNode = LayoutRegion | PiecePlacement;

export interface LayoutDocument {
  schemaVersion: number;
  /** The surface this document arranges. */
  id: string;
  root: LayoutRegion;
}

/* -------------------------------------------------------------------------- */
/*  walking the tree                                                           */
/* -------------------------------------------------------------------------- */

/** One node, with where it was found. `path` runs from the root's id to this node's, inclusive. */
export interface LayoutVisit<T = LayoutRegion | LayoutSlot | PiecePlacement> {
  node: T;
  path: readonly string[];
  depth: number;
  /** The region this node sits in, or `null` for the root. */
  parentRegionId: string | null;
  /** The slot this node fills, or `null` for the root and for slots themselves. */
  slotId: string | null;
}

/**
 * Every node in document order: a region, then each of its slots, then what each slot holds.
 *
 * Iterative and cycle-safe. A document is a tree by construction, but a document arrives from JSON,
 * from an editor mid-drag or from a bad merge, and a walk that recursed into a node it had already
 * visited would hang the editor rather than report the problem. A node reached twice is walked
 * once; `validateLayout` reports the duplicate id that reaching it twice implies.
 */
export function walkLayout(document: LayoutDocument): LayoutVisit[] {
  const visits: LayoutVisit[] = [];
  const seen = new Set<object>();

  const visitNode = (
    node: LayoutNode,
    path: readonly string[],
    depth: number,
    parentRegionId: string | null,
    slotId: string | null,
  ): void => {
    if (seen.has(node)) return;
    seen.add(node);
    const here = [...path, node.id];
    visits.push({ node, path: here, depth, parentRegionId, slotId });
    if (node.kind !== "region") return;
    for (const slot of node.slots) {
      if (seen.has(slot)) continue;
      seen.add(slot);
      const slotPath = [...here, slot.id];
      visits.push({
        node: slot,
        path: slotPath,
        depth: depth + 1,
        parentRegionId: node.id,
        slotId: null,
      });
      if (slot.content) visitNode(slot.content, slotPath, depth + 2, node.id, slot.id);
    }
  };

  visitNode(document.root, [], 0, null, null);
  return visits;
}

export function layoutRegions(document: LayoutDocument): LayoutVisit<LayoutRegion>[] {
  return walkLayout(document).filter(
    (visit): visit is LayoutVisit<LayoutRegion> => visit.node.kind === "region",
  );
}

export function layoutSlots(document: LayoutDocument): LayoutVisit<LayoutSlot>[] {
  return walkLayout(document).filter(
    (visit): visit is LayoutVisit<LayoutSlot> => visit.node.kind === "slot",
  );
}

export function layoutPlacements(document: LayoutDocument): LayoutVisit<PiecePlacement>[] {
  return walkLayout(document).filter(
    (visit): visit is LayoutVisit<PiecePlacement> => visit.node.kind === "placement",
  );
}

/** The region with this id, or `null`. Ids are unique in a valid document; the first one wins. */
export function findRegion(document: LayoutDocument, id: string): LayoutRegion | null {
  return layoutRegions(document).find((visit) => visit.node.id === id)?.node ?? null;
}

export function findSlot(document: LayoutDocument, id: string): LayoutSlot | null {
  return layoutSlots(document).find((visit) => visit.node.id === id)?.node ?? null;
}

export function findPlacement(document: LayoutDocument, id: string): PiecePlacement | null {
  return layoutPlacements(document).find((visit) => visit.node.id === id)?.node ?? null;
}

/** Any node by id, whichever of the three kinds it is. */
export function findLayoutNode(
  document: LayoutDocument,
  id: string,
): LayoutRegion | LayoutSlot | PiecePlacement | null {
  return walkLayout(document).find((visit) => visit.node.id === id)?.node ?? null;
}

/**
 * Every piece id this document places, once each, in document order.
 *
 * The three CAD modules are three placements of ONE piece, so this list is shorter than the
 * placement list, and that is the point: it answers "which pieces does this layout use", which is
 * the question the registry coverage gate asks.
 */
export function placedPieceIds(document: LayoutDocument): string[] {
  const ids: string[] = [];
  const seen = new Set<string>();
  for (const visit of layoutPlacements(document)) {
    const piece = visit.node.piece;
    if (seen.has(piece)) continue;
    seen.add(piece);
    ids.push(piece);
  }
  return ids;
}

/* -------------------------------------------------------------------------- */
/*  validation - reports, never refuses                                        */
/* -------------------------------------------------------------------------- */

export type LayoutIssueCode =
  /** The document was written by a schema this module does not know. */
  | "unsupported-schema-version"
  /** A region's mode is not one of the three. */
  | "unknown-layout-mode"
  /** Two nodes share an id, so an override keyed on it would apply to both. */
  | "duplicate-id"
  /** A slot holds nothing. It renders as a gap and can never be the target of an edit. */
  | "orphan-slot"
  /** A placement names a piece the provided registry does not know. */
  | "unknown-piece"
  /** A splitter names a slot that is not one of its region's own. */
  | "splitter-unknown-slot"
  /** Two children of one region scroll the same axis the region stacks them along. */
  | "scroll-owner-conflict";

export interface LayoutIssue {
  code: LayoutIssueCode;
  /** Nothing here blocks. The tier orders the list; it does not gate anything. */
  severity: "error" | "warning" | "info";
  /** The node the issue is about. */
  nodeId: string;
  path: readonly string[];
  /** Machine-readable specifics. Never display prose - the interface names its own issues. */
  detail?: Readonly<Record<string, string | number>>;
}

/**
 * The minimum a validator needs of a registry: can it resolve this piece id.
 *
 * Declared here rather than imported so `document.ts` and `registry.ts` stay independent modules,
 * and so a test can hand validation a two-line stub instead of a populated registry.
 */
export interface PieceLookup {
  has(id: string): boolean;
}

/**
 * Does this scroll declaration own that axis. `both` owns each of them.
 *
 * A predicate rather than "build the list of axes and search it": the question is only ever asked
 * one axis at a time, inside a loop over a region's children, and allocating a two-element array per
 * child to run `includes` over it is work with no answer in it.
 */
function ownsScrollAxis(
  scroll: ScrollAxis | undefined,
  axis: "vertical" | "horizontal",
): boolean {
  return scroll === "both" || scroll === axis;
}

/** The axis a region stacks its children along. A stack has none, so nothing can collide on it. */
function mainAxis(mode: RegionLayoutMode): "vertical" | "horizontal" | null {
  if (mode === "column") return "vertical";
  if (mode === "row") return "horizontal";
  return null;
}

/**
 * Everything structurally wrong with this document, as a list.
 *
 * `registry` is optional: without one, placements are not checked against anything, which is the
 * right answer for a document being validated before its pieces are known. With one, a placement
 * naming an unregistered piece is reported - and reported, not removed. A layout that references a
 * piece a build has not shipped yet is a real state (an older machine opening a newer layout), and
 * deleting the placement to "fix" it would silently discard the owner's arrangement.
 */
export function validateLayout(
  document: LayoutDocument,
  registry?: PieceLookup,
): LayoutIssue[] {
  const issues: LayoutIssue[] = [];

  if (document.schemaVersion !== LAYOUT_SCHEMA_VERSION) {
    issues.push({
      code: "unsupported-schema-version",
      severity: "warning",
      nodeId: document.id,
      path: [document.id],
      detail: { found: document.schemaVersion, expected: LAYOUT_SCHEMA_VERSION },
    });
  }

  const visits = walkLayout(document);
  const idsSeen = new Set<string>();

  for (const visit of visits) {
    const { node, path } = visit;

    if (idsSeen.has(node.id)) {
      issues.push({
        code: "duplicate-id",
        severity: "error",
        nodeId: node.id,
        path,
        detail: { kind: node.kind },
      });
    }
    idsSeen.add(node.id);

    if (node.kind === "slot" && node.content === null) {
      issues.push({
        code: "orphan-slot",
        severity: "warning",
        nodeId: node.id,
        path,
        detail: { region: visit.parentRegionId ?? "" },
      });
      continue;
    }

    if (node.kind === "placement") {
      if (registry && !registry.has(node.piece)) {
        issues.push({
          code: "unknown-piece",
          severity: "error",
          nodeId: node.id,
          path,
          detail: { piece: node.piece },
        });
      }
      continue;
    }

    if (node.kind !== "region") continue;

    if (!REGION_LAYOUT_MODES.includes(node.mode)) {
      issues.push({
        code: "unknown-layout-mode",
        severity: "error",
        nodeId: node.id,
        path,
        detail: { mode: String(node.mode) },
      });
    }

    const ownSlots = new Set(node.slots.map((slot) => slot.id));
    for (const splitter of node.splitters ?? []) {
      for (const neighbour of splitter.between) {
        if (ownSlots.has(neighbour)) continue;
        issues.push({
          code: "splitter-unknown-slot",
          severity: "error",
          nodeId: splitter.id,
          path: [...path, splitter.id],
          detail: { slot: neighbour, region: node.id },
        });
      }
    }

    // TWO SCROLL OWNERS ON THE AXIS THIS REGION STACKS ALONG is the conflict. Three columns each
    // owning their own vertical scrollbar side by side is not one - that is the workspace's whole
    // arrangement - because a row does not stack its children vertically. Two vertical scrollers
    // one above the other in a column IS one: the outer one decides which of them the wheel
    // reaches, and neither can be predicted from the layout.
    const axis = mainAxis(node.mode);
    const children = node.slots
      .map((slot) => slot.content)
      .filter((content): content is LayoutRegion => content?.kind === "region");
    if (axis) {
      const owners = children.filter((child) => ownsScrollAxis(child.scroll, axis));
      if (owners.length > 1) {
        issues.push({
          code: "scroll-owner-conflict",
          severity: "warning",
          nodeId: node.id,
          path,
          detail: { axis, owners: owners.map((child) => child.id).join(" ") },
        });
      }
    } else {
      for (const candidate of ["vertical", "horizontal"] as const) {
        const owners = children.filter((child) => ownsScrollAxis(child.scroll, candidate));
        if (owners.length > 1) {
          issues.push({
            code: "scroll-owner-conflict",
            severity: "warning",
            nodeId: node.id,
            path,
            detail: { axis: candidate, owners: owners.map((child) => child.id).join(" ") },
          });
        }
      }
    }
  }

  return issues;
}
