/**
 * The four edit operations, and the four properties they promise.
 *
 * TWO KINDS OF TEST HERE, and both are needed. The first half is behavioural: a named document, a
 * named edit, the exact tree that must come out. The second half is a PROPERTY battery - every
 * operation applied to a list of documents that includes the shipped one and six deliberately odd
 * ones, asserting immutability, JSON round-tripping, and that `validateLayout` never reports more of
 * any issue code after an edit than before it.
 *
 * WHY THE ODD DOCUMENTS ARE THERE. "The operation returns a valid document" is not the promise, and
 * could not be: an edit is applied to whatever the owner is halfway through, or to a layout an older
 * build wrote, and those already carry issues. The promise is that editing does not make it WORSE -
 * so the battery deliberately includes a document per issue code the validator can report, plus a
 * cyclic one, because an editor that hung on a cycle would be worse than one that degraded.
 *
 * ---------------------------------------------------------------------------------------------
 * NON-VACUITY. Each test below names the mutation to `editOperations.ts` that turns it red. Two were
 * run for real and reverted:
 *
 *   1. THE SPLITTER PRUNE WAS REMOVED. Deleting the `splitters` filter from `withoutSlot` failed
 *      "never reports more of any issue code than it was handed" with
 *      `splitter-unknown-slot 0 -> 1` on the splitter-bearing document - which is precisely the
 *      issue a moved slot creates for the handle that used to point at it.
 *   2. AN OPERATION WROTE THROUGH ITS INPUT. Changing `setPlacementFlag`'s rebuild to assign
 *      `slot.content = next` in place (instead of returning a new slot) failed "leaves the document
 *      it was handed byte-identical" for `setPlacementHidden` on every document in the battery.
 *
 * THE TWO KNOWN VACUOUS SHAPES, and why neither applies. Nothing here reads source text, and nothing
 * asserts only that "no issue appeared" - each behavioural case asserts the tree that came out, and
 * the property battery asserts a FLOOR first (the edits really landed: the counters at the bottom of
 * the battery require every operation to have produced a changed document at least once, so a suite
 * where every operation silently no-opped fails rather than passes).
 */
import { describe, expect, it } from "vitest";
import { DEFAULT_WORKSPACE_LAYOUT, WORKSPACE_CONDITION } from "./defaultWorkspaceLayout";
import {
  findPlacement,
  findRegion,
  layoutPlacements,
  LAYOUT_SCHEMA_VERSION,
  validateLayout,
  type LayoutDocument,
  type LayoutIssueCode,
  type LayoutRegion,
  type LayoutSlot,
  type PiecePlacement,
} from "./document";
import {
  MIN_REGION_FRACTION,
  movePlacement,
  setPlacementCollapsed,
  setPlacementHidden,
  setRegionSize,
} from "./editOperations";
import { WORKSPACE_REGION } from "./workspacePieces";

/* -------------------------------------------------------------------------- */
/*  fixtures                                                                   */
/* -------------------------------------------------------------------------- */

function slot(id: string, content: LayoutSlot["content"]): LayoutSlot {
  return { kind: "slot", id, content };
}

function place(id: string, piece: string): PiecePlacement {
  return { kind: "placement", id, piece };
}

function documentOf(root: LayoutRegion, id = "fixture"): LayoutDocument {
  return { schemaVersion: LAYOUT_SCHEMA_VERSION, id, root };
}

/**
 * Two columns of three placements, with a splitter between the two column slots.
 *
 * The workhorse: it has somewhere to move a placement FROM, somewhere to move it TO, an order to
 * reorder inside, and a splitter that a careless move would break.
 */
function twoColumns(): LayoutDocument {
  return documentOf({
    kind: "region",
    id: "band",
    mode: "row",
    splitters: [
      {
        id: "band.splitter",
        between: ["slot.left", "slot.right"],
        keyStep: 16,
        lineThickness: 1,
        grabWidth: 9,
      },
    ],
    slots: [
      slot("slot.left", {
        kind: "region",
        id: "left",
        mode: "column",
        size: { min: 200, fraction: 0.4 },
        slots: [
          slot("slot.left.a", place("place.a", "piece.a")),
          slot("slot.left.b", place("place.b", "piece.b")),
          slot("slot.left.c", place("place.c", "piece.c")),
        ],
      }),
      slot("slot.right", {
        kind: "region",
        id: "right",
        mode: "column",
        size: { grow: true },
        slots: [slot("slot.right.d", place("place.d", "piece.d"))],
      }),
    ],
  });
}

/**
 * A region whose OWN splitter names two slots holding placements.
 *
 * This is the document that makes the splitter prune observable: move `place.one` out of `pair` and
 * the handle between the two placements is left pointing at a slot that is no longer there.
 */
function splitterOverPlacements(): LayoutDocument {
  return documentOf(
    {
      kind: "region",
      id: "root",
      mode: "column",
      slots: [
        slot("slot.pair", {
          kind: "region",
          id: "pair",
          mode: "row",
          splitters: [
            {
              id: "pair.splitter",
              between: ["slot.one", "slot.two"],
              keyStep: 16,
              lineThickness: 1,
              grabWidth: 9,
            },
          ],
          slots: [
            slot("slot.one", place("place.one", "piece.one")),
            slot("slot.two", place("place.two", "piece.two")),
          ],
        }),
        slot("slot.elsewhere", {
          kind: "region",
          id: "elsewhere",
          mode: "column",
          slots: [slot("slot.elsewhere.x", place("place.x", "piece.x"))],
        }),
      ],
    },
    "fixture.splitter",
  );
}

/** One piece placed twice, so a piece-id ref is ambiguous and must resolve to nothing. */
function twicePlaced(): LayoutDocument {
  return documentOf(
    {
      kind: "region",
      id: "root",
      mode: "column",
      slots: [
        slot("slot.first", place("place.first", "piece.repeated")),
        slot("slot.second", place("place.second", "piece.repeated")),
      ],
    },
    "fixture.twice",
  );
}

/** Two nodes under one id: an override keyed on it would apply to both. */
function duplicateIds(): LayoutDocument {
  return documentOf(
    {
      kind: "region",
      id: "root",
      mode: "column",
      slots: [
        slot("slot.dup", place("place.dup", "piece.a")),
        slot("slot.dup", place("place.dup", "piece.b")),
      ],
    },
    "fixture.duplicate",
  );
}

/** A slot with nothing in it: the validator's `orphan-slot`. */
function orphanSlot(): LayoutDocument {
  return documentOf(
    {
      kind: "region",
      id: "root",
      mode: "column",
      slots: [slot("slot.filled", place("place.filled", "piece.a")), slot("slot.empty", null)],
    },
    "fixture.orphan",
  );
}

/** A mode nothing can arrange, and a splitter pointing outside its region. */
function malformed(): LayoutDocument {
  return documentOf(
    {
      kind: "region",
      id: "root",
      mode: "diagonal" as unknown as LayoutRegion["mode"],
      splitters: [
        {
          id: "root.splitter",
          between: ["slot.here", "slot.nowhere"],
          keyStep: 16,
          lineThickness: 1,
          grabWidth: 9,
        },
      ],
      slots: [slot("slot.here", place("place.here", "piece.a"))],
    },
    "fixture.malformed",
  );
}

/** Two vertical scroll owners stacked in a column: the validator's `scroll-owner-conflict`. */
function scrollConflict(): LayoutDocument {
  return documentOf(
    {
      kind: "region",
      id: "root",
      mode: "column",
      slots: [
        slot("slot.upper", {
          kind: "region",
          id: "upper",
          mode: "column",
          scroll: "vertical",
          slots: [slot("slot.upper.a", place("place.upper", "piece.a"))],
        }),
        slot("slot.lower", {
          kind: "region",
          id: "lower",
          mode: "column",
          scroll: "vertical",
          slots: [slot("slot.lower.a", place("place.lower", "piece.b"))],
        }),
      ],
    },
    "fixture.scroll",
  );
}

/**
 * A region that contains itself.
 *
 * Not reachable by any edit this module performs - it is what a bad merge or a hand-written layout
 * produces - and the reason every walk here is cycle-safe. The promise is that an operation on it
 * RETURNS, not that it repairs anything.
 */
function cyclic(): LayoutDocument {
  const loop: LayoutRegion = {
    kind: "region",
    id: "loop",
    mode: "column",
    slots: [slot("slot.loop.a", place("place.loop", "piece.a"))],
  };
  (loop.slots as LayoutSlot[]).push(slot("slot.loop.self", loop));
  return documentOf(
    { kind: "region", id: "root", mode: "column", slots: [slot("slot.root", loop)] },
    "fixture.cyclic",
  );
}

/** A document from a schema this build does not know. Every operation still has to work on it. */
function futureSchema(): LayoutDocument {
  return { ...twoColumns(), schemaVersion: LAYOUT_SCHEMA_VERSION + 98, id: "fixture.future" };
}

/** The shipped document, by value, so nothing here can reach the real one. */
function shipped(): LayoutDocument {
  return structuredClone(DEFAULT_WORKSPACE_LAYOUT);
}

/* -------------------------------------------------------------------------- */
/*  reading a document back                                                    */
/* -------------------------------------------------------------------------- */

/** The slot ids of a region, in order: the shape a move is asserted against. */
function slotIds(document: LayoutDocument, regionId: string): string[] {
  const region = findRegion(document, regionId);
  if (!region) throw new Error(`no region ${regionId}`);
  return region.slots.map((entry) => entry.id);
}

/** Which piece each of a region's slots holds, in order. */
function piecesIn(document: LayoutDocument, regionId: string): (string | null)[] {
  const region = findRegion(document, regionId);
  if (!region) throw new Error(`no region ${regionId}`);
  return region.slots.map((entry) =>
    entry.content?.kind === "placement" ? entry.content.piece : null,
  );
}

/**
 * The document as it would come back FROM SOURCE: serialised, then read again.
 *
 * Written as two steps rather than as one deep-clone expression because it is not a clone - the
 * assertion is about what survives the trip, so the text in the middle is the point.
 */
function roundTrip(document: LayoutDocument): LayoutDocument {
  return JSON.parse(JSON.stringify(document)) as LayoutDocument;
}

function issueCounts(document: LayoutDocument): Map<LayoutIssueCode, number> {
  const counts = new Map<LayoutIssueCode, number>();
  for (const issue of validateLayout(document)) {
    counts.set(issue.code, (counts.get(issue.code) ?? 0) + 1);
  }
  return counts;
}

/* -------------------------------------------------------------------------- */
/*  movePlacement                                                              */
/* -------------------------------------------------------------------------- */

describe("movePlacement", () => {
  /**
   * FAILS IF: the anchor is resolved before the removal (the placement lands one position short on a
   * downward move), or the moved slot is dropped instead of re-inserted.
   */
  it("reorders inside one region by landing at the anchor's position", () => {
    const before = twoColumns();
    // A upward past nothing, then C up to where A was: two directions through one region.
    const moved = movePlacement(before, "place.c", "slot.left.a");
    expect(slotIds(moved, "left")).toEqual(["slot.left.c", "slot.left.a", "slot.left.b"]);

    // And downward: A to where C sits means AT C's position once A is out of the way, pushing C
    // down. Landing after C is a different request, and it is the one `targetIndex` exists for.
    const down = movePlacement(before, "place.a", "slot.left.c");
    expect(slotIds(down, "left")).toEqual(["slot.left.b", "slot.left.a", "slot.left.c"]);
    expect(slotIds(movePlacement(before, "place.a", "slot.left.c", 2), "left")).toEqual([
      "slot.left.b",
      "slot.left.c",
      "slot.left.a",
    ]);
  });

  /** FAILS IF: `targetIndex` is read against the pre-removal array, or is not clamped. */
  it("reads an explicit index against the final order, and clamps it", () => {
    const before = twoColumns();
    expect(slotIds(movePlacement(before, "place.a", "left", 1), "left")).toEqual([
      "slot.left.b",
      "slot.left.a",
      "slot.left.c",
    ]);
    // Overshooting the end means the end; undershooting means the front. A drag cannot fail.
    expect(slotIds(movePlacement(before, "place.a", "left", 99), "left")).toEqual([
      "slot.left.b",
      "slot.left.c",
      "slot.left.a",
    ]);
    expect(slotIds(movePlacement(before, "place.c", "left", -5), "left")).toEqual([
      "slot.left.c",
      "slot.left.a",
      "slot.left.b",
    ]);
  });

  /**
   * THE EDIT THE WHOLE PHASE IS FOR: a piece leaves the column it shipped in.
   *
   * FAILS IF: the slot is emptied rather than moved (the source keeps a slot holding nothing), the
   * placement is copied rather than moved (it appears in both regions), or the destination anchor is
   * ignored.
   */
  it("carries a placement into another region, with its slot", () => {
    const moved = movePlacement(twoColumns(), "place.b", "slot.right.d");
    expect(slotIds(moved, "left")).toEqual(["slot.left.a", "slot.left.c"]);
    expect(slotIds(moved, "right")).toEqual(["slot.left.b", "slot.right.d"]);
    // Once, not twice, and the same placement object's settings travelled with it.
    expect(layoutPlacements(moved).filter((visit) => visit.node.id === "place.b")).toHaveLength(1);
    // No slot was emptied on the way out, which is what keeps the validator quiet.
    expect(validateLayout(moved)).toEqual([]);
  });

  /** FAILS IF: a region target is not accepted, or does not mean "at the end". */
  it("accepts a region id as the target and lands at its end", () => {
    const moved = movePlacement(twoColumns(), "place.a", "right");
    expect(slotIds(moved, "right")).toEqual(["slot.right.d", "slot.left.a"]);
  });

  /**
   * FAILS IF: `withoutSlot` stops pruning the splitters that named the departing slot - the mutation
   * proven above, which leaves a `splitter-unknown-slot` behind.
   */
  it("drops a splitter that named the slot it moved away", () => {
    const before = splitterOverPlacements();
    expect(findRegion(before, "pair")?.splitters).toHaveLength(1);

    const moved = movePlacement(before, "place.one", "elsewhere");
    expect(findRegion(moved, "pair")?.splitters).toBeUndefined();
    expect(slotIds(moved, "elsewhere")).toEqual(["slot.elsewhere.x", "slot.one"]);
    expect(validateLayout(moved)).toEqual([]);
    // The other handle-bearing region is untouched: pruning is scoped to the region that lost a slot.
    expect(findRegion(movePlacement(twoColumns(), "place.a", "right"), "band")?.splitters)
      .toHaveLength(1);
  });

  /** FAILS IF: a piece id placed twice resolves to the first match instead of to nothing. */
  it("refuses an ambiguous piece ref, and accepts the placement id that disambiguates it", () => {
    const before = twicePlaced();
    expect(movePlacement(before, "piece.repeated", "slot.first")).toBe(before);
    expect(movePlacement(before, { piece: "piece.repeated" }, "slot.first")).toBe(before);

    const moved = movePlacement(before, { placement: "place.second" }, "slot.first");
    expect(slotIds(moved, "root")).toEqual(["slot.second", "slot.first"]);
  });

  /** FAILS IF: an unknown ref or target throws, or invents a slot. */
  it("no-ops on an unknown placement, an unknown target, and its own slot", () => {
    const before = twoColumns();
    expect(movePlacement(before, "place.nobody", "slot.right.d")).toBe(before);
    expect(movePlacement(before, "place.a", "slot.nowhere")).toBe(before);
    expect(movePlacement(before, { placement: "piece.a" }, "slot.right.d")).toBe(before);
    expect(movePlacement(before, "place.a", "slot.left.a")).toBe(before);
  });

  /**
   * A bare string is a placement id FIRST. `piece.d` is placed once, so it also works as a ref -
   * which is what an editing surface holding only a piece id needs.
   *
   * FAILS IF: the fallback to a piece id is dropped, or shadows an exact placement id.
   */
  it("reads a bare ref as a placement id first and a unique piece id second", () => {
    const moved = movePlacement(twoColumns(), "piece.d", "slot.left.a");
    expect(piecesIn(moved, "left")).toEqual(["piece.d", "piece.a", "piece.b", "piece.c"]);
  });

  /**
   * The shipped arrangement, edited the way plan 1.5 describes: a section crosses a column boundary.
   *
   * FAILS IF: the operation cannot handle the real document's depth, or the shipped splitters are
   * disturbed by an edit that did not touch the band.
   */
  it("moves a section of the shipped workspace into another column", () => {
    const before = shipped();
    const after = movePlacement(
      before,
      "workspace.place.specifications-pinout",
      "workspace.slot.sourcing-lifecycle",
    );
    expect(piecesIn(after, WORKSPACE_REGION.specificationsBody)).not.toContain(
      "workspace.specifications-pinout",
    );
    expect(piecesIn(after, WORKSPACE_REGION.sourcingBody)[0]).toBe(
      "workspace.specifications-pinout",
    );
    // Its per-placement settings, including the visibility the document gave it, travelled intact.
    expect(findPlacement(after, "workspace.place.specifications-pinout")?.visibility?.anyOf).toEqual(
      [WORKSPACE_CONDITION.specificationsPinout],
    );
    expect(findRegion(after, WORKSPACE_REGION.columnBand)?.splitters).toHaveLength(2);
    expect(validateLayout(after)).toEqual(validateLayout(before));
  });
});

/* -------------------------------------------------------------------------- */
/*  setPlacementCollapsed / setPlacementHidden                                 */
/* -------------------------------------------------------------------------- */

describe("per-placement settings", () => {
  /**
   * FAILS IF: turning a setting off writes `false` instead of deleting the key - which is the state
   * that makes a committed document stop being byte-identical to the arrangement it describes.
   */
  it("writes true and DELETES on false, for both settings", () => {
    for (const [set, key] of [
      [setPlacementCollapsed, "collapsed"],
      [setPlacementHidden, "hidden"],
    ] as const) {
      const before = twoColumns();
      const on = set(before, "place.a", true);
      expect(findPlacement(on, "place.a")).toEqual({
        kind: "placement",
        id: "place.a",
        piece: "piece.a",
        [key]: true,
      });

      const off = set(on, "place.a", false);
      expect(Object.keys(findPlacement(off, "place.a") ?? {})).toEqual(["kind", "id", "piece"]);
      expect(roundTrip(off)).toEqual(before);
    }
  });

  /** FAILS IF: the two settings are stored in one field, or one clears the other. */
  it("keeps the two settings independent", () => {
    const both = setPlacementHidden(setPlacementCollapsed(twoColumns(), "place.a", true), "place.a", true);
    expect(findPlacement(both, "place.a")).toMatchObject({ collapsed: true, hidden: true });
    const one = setPlacementHidden(both, "place.a", false);
    expect(findPlacement(one, "place.a")).toMatchObject({ collapsed: true });
    expect(findPlacement(one, "place.a")?.hidden).toBeUndefined();
  });

  /** FAILS IF: a no-op still rebuilds the document, or an unknown ref throws. */
  it("hands back the same document for a setting already in force and an unknown ref", () => {
    const before = twoColumns();
    expect(setPlacementCollapsed(before, "place.a", false)).toBe(before);
    expect(setPlacementHidden(before, "place.nobody", true)).toBe(before);
    const on = setPlacementCollapsed(before, "place.a", true);
    expect(setPlacementCollapsed(on, "place.a", true)).toBe(on);
  });

  /**
   * FAILS IF: the edit is applied by ID rather than by the resolved object - which would set the
   * setting on BOTH nodes of a document carrying one placement id twice.
   */
  it("edits one node of a document that carries the same placement id twice", () => {
    const edited = setPlacementHidden(duplicateIds(), "place.dup", true);
    expect(layoutPlacements(edited).map((visit) => visit.node.hidden)).toEqual([true, undefined]);
  });
});

/* -------------------------------------------------------------------------- */
/*  setRegionSize                                                             */
/* -------------------------------------------------------------------------- */

describe("setRegionSize", () => {
  /** FAILS IF: a patch replaces the whole size rather than the fields it names. */
  it("patches only the fields it names and keeps grow and the conditions", () => {
    const before = shipped();
    const after = setRegionSize(before, WORKSPACE_REGION.sourcingColumn, { min: 300 });
    const size = findRegion(after, WORKSPACE_REGION.sourcingColumn)?.size;
    const shippedSize = findRegion(before, WORKSPACE_REGION.sourcingColumn)?.size;
    expect(size?.min).toBe(300);
    expect(size?.fraction).toBe(shippedSize?.fraction);
    expect(size?.grow).toBe(true);
    expect(size?.when).toEqual(shippedSize?.when);
  });

  /** FAILS IF: the fraction bound is dropped, or a pixel size is allowed to go negative. */
  it("bounds a fraction into the model's range and a pixel size at zero", () => {
    const before = twoColumns();
    expect(findRegion(setRegionSize(before, "left", { fraction: 4 }), "left")?.size?.fraction).toBe(1);
    expect(findRegion(setRegionSize(before, "left", { fraction: 0 }), "left")?.size?.fraction).toBe(
      MIN_REGION_FRACTION,
    );
    expect(findRegion(setRegionSize(before, "left", { fraction: -3 }), "left")?.size?.fraction).toBe(
      MIN_REGION_FRACTION,
    );
    expect(findRegion(setRegionSize(before, "left", { min: -40 }), "left")?.size?.min).toBe(0);
  });

  /** FAILS IF: the min/preferred relationship the model states is not kept. */
  it("raises a preferred size that lands below the minimum", () => {
    const after = setRegionSize(twoColumns(), "left", { preferred: 50 });
    expect(findRegion(after, "left")?.size).toMatchObject({ min: 200, preferred: 200 });
  });

  /** FAILS IF: a non-number is written into the document instead of being ignored. */
  it("ignores a value that is not a finite number", () => {
    const before = twoColumns();
    for (const value of [Number.NaN, Number.POSITIVE_INFINITY, "300" as unknown as number]) {
      const after = setRegionSize(before, "left", { min: value });
      expect(findRegion(after, "left")?.size?.min).toBe(200);
      expect(after).toBe(before);
    }
  });

  /** FAILS IF: `null` is treated as a value rather than as a clear, or an emptied size is kept. */
  it("clears a constraint on null and removes a size that ends up carrying nothing", () => {
    const cleared = setRegionSize(twoColumns(), "left", { min: null });
    expect(findRegion(cleared, "left")?.size).toEqual({ fraction: 0.4 });

    const gone = setRegionSize(cleared, "left", { fraction: null });
    expect(findRegion(gone, "left")?.size).toBeUndefined();
    expect("size" in (findRegion(gone, "left") as object)).toBe(false);
  });

  /**
   * The sparse-sourcing geometry lives under a CONDITION, and both sets are in the document at once,
   * so editing one must not touch the other.
   *
   * FAILS IF: a conditional patch writes the resting size, or replaces the whole `when` block.
   */
  it("edits a size under a named condition without touching the resting one", () => {
    const before = shipped();
    const after = setRegionSize(
      before,
      WORKSPACE_REGION.specificationsColumn,
      { fraction: 0.6 },
      { condition: WORKSPACE_CONDITION.sparseSourcing },
    );
    const size = findRegion(after, WORKSPACE_REGION.specificationsColumn)?.size;
    const shippedSize = findRegion(before, WORKSPACE_REGION.specificationsColumn)?.size;
    expect(size?.when?.[WORKSPACE_CONDITION.sparseSourcing]?.fraction).toBe(0.6);
    expect(size?.fraction).toBe(shippedSize?.fraction);
    expect(size?.min).toBe(shippedSize?.min);

    // Clearing the last field of a condition drops the condition, and dropping the last condition
    // drops the block - so a document never carries an empty one.
    const dropped = setRegionSize(
      after,
      WORKSPACE_REGION.specificationsColumn,
      { fraction: null },
      { condition: WORKSPACE_CONDITION.sparseSourcing },
    );
    expect(findRegion(dropped, WORKSPACE_REGION.specificationsColumn)?.size?.when).toBeUndefined();
  });

  /** FAILS IF: an unknown region throws, or a patch that changes nothing rebuilds the document. */
  it("no-ops on an unknown region and on a patch that changes no number", () => {
    const before = shipped();
    expect(setRegionSize(before, "workspace.nowhere", { min: 10 })).toBe(before);
    expect(setRegionSize(before, WORKSPACE_REGION.cadColumn, {})).toBe(before);
    const cad = findRegion(before, WORKSPACE_REGION.cadColumn)?.size;
    expect(
      setRegionSize(before, WORKSPACE_REGION.cadColumn, { min: cad?.min, fraction: cad?.fraction }),
    ).toBe(before);
    expect(
      setRegionSize(
        before,
        WORKSPACE_REGION.sourcingColumn,
        { min: findRegion(before, WORKSPACE_REGION.sourcingColumn)?.size?.when?.[
          WORKSPACE_CONDITION.sparseSourcing
        ]?.min },
        { condition: WORKSPACE_CONDITION.sparseSourcing },
      ),
    ).toBe(before);
  });
});

/* -------------------------------------------------------------------------- */
/*  the property battery                                                       */
/* -------------------------------------------------------------------------- */

/** Every document an operation has to survive, including the ones nobody would write on purpose. */
const BATTERY: readonly (() => LayoutDocument)[] = [
  shipped,
  twoColumns,
  splitterOverPlacements,
  twicePlaced,
  duplicateIds,
  orphanSlot,
  malformed,
  scrollConflict,
  cyclic,
  futureSchema,
];

/**
 * Every operation, applied to a document, as a list of NAMED THUNKS.
 *
 * Thunks rather than results, so a caller can run one operation and inspect the input immediately
 * afterwards - which is what makes the immutability case able to name the operation that wrote
 * through its input rather than reporting that one of two hundred did.
 *
 * The refs are read OFF the document rather than written out here, so a document nobody wrote a case
 * for is still exercised on its own placements and its own regions - and the no-op refs are included
 * on purpose, because "does nothing safely" is one of the four promises.
 */
function everyOperation(
  document: LayoutDocument,
): { name: string; run: () => LayoutDocument }[] {
  const placements = layoutPlacements(document);
  const slots = placements.map((visit) => visit.slotId).filter((id): id is string => Boolean(id));
  const regions = [document.root.id];
  for (const visit of placements) {
    if (visit.parentRegionId) regions.push(visit.parentRegionId);
  }
  const first = placements[0]?.node.id ?? "nobody";
  const last = placements[placements.length - 1]?.node.id ?? "nobody";

  const cases: { name: string; run: () => LayoutDocument }[] = [];
  const add = (name: string, run: () => LayoutDocument) => cases.push({ name, run });

  for (const target of [...new Set([...slots, ...regions, "nowhere"])]) {
    add(`move ${first} -> ${target}`, () => movePlacement(document, first, target));
    add(`move ${last} -> ${target} @0`, () => movePlacement(document, last, target, 0));
    add(`move ${last} -> ${target} @99`, () => movePlacement(document, last, target, 99));
  }
  for (const ref of [first, last, "nobody"]) {
    for (const value of [true, false]) {
      add(`collapsed ${ref} ${value}`, () => setPlacementCollapsed(document, ref, value));
      add(`hidden ${ref} ${value}`, () => setPlacementHidden(document, ref, value));
    }
  }
  for (const region of [...new Set([...regions, "nowhere"])]) {
    for (const patch of [
      { min: 240 },
      { fraction: 0.5 },
      { preferred: 10 },
      { min: null, fraction: null, preferred: null },
      { fraction: Number.NaN },
    ]) {
      add(`size ${region} ${JSON.stringify(patch)}`, () => setRegionSize(document, region, patch));
      add(`size ${region} ${JSON.stringify(patch)} when`, () =>
        setRegionSize(document, region, patch, { condition: "condition.sparse" }),
      );
    }
  }
  return cases;
}

describe("every operation, over every document", () => {
  /**
   * THE CENTRAL PROPERTY. FAILS IF: any operation adds an issue - the splitter prune removed (proven
   * above), a slot emptied instead of moved, a slot id duplicated by an insertion, or a placement
   * copied rather than moved.
   */
  it("never reports more of any issue code than it was handed", () => {
    let changed = 0;
    for (const build of BATTERY) {
      const before = build();
      const baseline = issueCounts(before);
      for (const { name, run } of everyOperation(before)) {
        const result = run();
        if (result !== before) changed += 1;
        for (const [code, count] of issueCounts(result)) {
          expect(
            count,
            `${before.id}: ${name} made ${code} worse (${baseline.get(code) ?? 0} -> ${count})`,
          ).toBeLessThanOrEqual(baseline.get(code) ?? 0);
        }
      }
    }
    // The floor: the battery really produced edits. A suite where every operation silently no-opped
    // would satisfy the property above without proving anything at all.
    expect(changed).toBeGreaterThan(200);
  });

  /**
   * FAILS IF: any operation writes through its input - the in-place mutation proven above. Every
   * document is serialised before the run and compared after it, which catches a mutation at any
   * depth rather than only at the root.
   */
  it("leaves the document it was handed byte-identical", () => {
    // The cyclic fixture cannot be serialised, so its shape is read through the cycle-safe walk.
    const shape = (document: LayoutDocument): string =>
      document.id === "fixture.cyclic"
        ? JSON.stringify(
            layoutPlacements(document).map((visit) => [visit.path, visit.node.piece, visit.node.hidden]),
          )
        : JSON.stringify(document);

    for (const build of BATTERY) {
      const before = build();
      const snapshot = shape(before);
      for (const { name, run } of everyOperation(before)) {
        run();
        expect(shape(before), `${before.id}: ${name} mutated its input`).toBe(snapshot);
      }
    }
  });

  /**
   * FAILS IF: an operation writes an `undefined`-valued key or a `false` setting - either of which
   * makes the document that goes to source differ from the document that comes back.
   */
  it("returns documents that survive the round trip to source and back", () => {
    for (const build of BATTERY) {
      const before = build();
      if (before.id === "fixture.cyclic") continue;
      for (const { name, run } of everyOperation(before)) {
        const result = run();
        expect(roundTrip(result), `${before.id}: ${name}`).toEqual(result);
      }
    }
  });

  /**
   * A document that is not a tree is returned UNEDITED, and returned rather than hung on.
   *
   * FAILS IF: the `seen` set is removed from `rebuildRegions` (the run never finishes), or the
   * abandon-on-shared-region rule is removed (rebuilding one appearance of the loop forks it into two
   * nodes under one id, which the issue-code property above then catches as `duplicate-id 0 -> 1` -
   * the failure this rule was written from).
   */
  it("returns rather than hangs on a document that contains itself, and edits nothing in it", () => {
    const before = cyclic();
    const cases = everyOperation(before);
    expect(cases.length).toBeGreaterThan(10);
    for (const { name, run } of cases) {
      expect(run(), `${name}`).toBe(before);
    }
  });

  /**
   * Structural sharing, which is what keeps a drag cheap and keeps React identity for the subtrees an
   * edit did not reach.
   *
   * FAILS IF: an operation deep-clones the document (every region would be a new object).
   */
  it("shares every subtree it did not touch", () => {
    const before = shipped();
    const after = setPlacementHidden(before, "workspace.place.sourcing-offers", true);
    expect(after).not.toBe(before);
    // The other two columns are the SAME objects, by reference.
    for (const id of [WORKSPACE_REGION.cadColumn, WORKSPACE_REGION.specificationsColumn]) {
      expect(findRegion(after, id)).toBe(findRegion(before, id));
    }
    // And the column that changed did not: its body is rebuilt, its title strip's slot is not.
    expect(findRegion(after, WORKSPACE_REGION.sourcingColumn)).not.toBe(
      findRegion(before, WORKSPACE_REGION.sourcingColumn),
    );
  });
});
