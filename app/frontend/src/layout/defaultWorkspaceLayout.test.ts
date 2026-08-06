/**
 * The shipped workspace, as a document: is the transcription faithful, and does it stay faithful.
 *
 * These are the gates plan 1.6 says the arrangement tests eventually become. They bind the document
 * to the modules it transcribes rather than to numbers typed twice - the column geometry is
 * compared against `lib/workspaceColumns`'s own constants and against `resolveColumnWidths`'s own
 * output, the CAD order against `cadAssetSet`, the sourcing order against `sourcingSections`, and
 * the piece partition against the registry both ways round, in the style of the `devIds` parity
 * tests.
 */
import { describe, expect, it } from "vitest";
import { REPRESENTATION_KINDS } from "../components/component-workspace/cadAssetSet";
import { COLLAPSIBLE_SOURCING_SECTIONS } from "../components/component-workspace/sourcingSections";
import { DEV_ID_BY_ID } from "../lib/devIds";
import {
  columnMinimums,
  resolveColumnWidths,
  SPLITTER_KEY_STEP,
  SPLITTER_NEIGHBOURS,
  WORKSPACE_COLUMN_FRACTION,
  WORKSPACE_COLUMN_FRACTION_SPARSE,
  WORKSPACE_COLUMN_IDS,
  WORKSPACE_COLUMNS_STORAGE_KEY,
  type WorkspaceSplitterId,
} from "../lib/workspaceColumns";
import {
  DEFAULT_WORKSPACE_LAYOUT,
  sourcingFillCondition,
  WORKSPACE_COLUMN_REGION,
  WORKSPACE_CONDITION,
  workspaceColumnFractions,
  workspaceColumnMinimums,
} from "./defaultWorkspaceLayout";
import {
  findPlacement,
  findRegion,
  layoutPlacements,
  layoutRegions,
  LAYOUT_SCHEMA_VERSION,
  placedPieceIds,
  validateLayout,
  type LayoutDocument,
} from "./document";
import {
  WORKSPACE_PIECE_DUPLICATES,
  WORKSPACE_PIECE_REGISTRY,
  WORKSPACE_PIECES,
} from "./workspacePieces";

/**
 * App source as raw strings, the same way `devIds.parity.test.ts` reads it: through Vite's raw
 * glob, never node:fs, which breaks `tsc -b`.
 */
const RAW = import.meta.glob("/src/**/*.tsx", {
  query: "?raw",
  eager: true,
  import: "default",
}) as Record<string, string>;

const SOURCE_TEXT = Object.entries(RAW)
  .filter(([path]) => !/\.(test|spec)\.tsx?$/.test(path))
  .map(([, text]) => text)
  .join("\n");

describe("the default workspace layout as a document", () => {
  it("survives a JSON round trip unchanged, byte for byte", () => {
    // A committed layout travels to source and back through exactly this. Fails the moment a field
    // holds a Map, a Date, a function or an `undefined` - all of which typecheck and none of which
    // survive serialisation.
    const text = JSON.stringify(DEFAULT_WORKSPACE_LAYOUT);
    const parsed = JSON.parse(text) as LayoutDocument;
    expect(parsed).toStrictEqual(DEFAULT_WORKSPACE_LAYOUT);
    expect(JSON.stringify(parsed)).toBe(text);
  });

  it("declares the schema version this module reads", () => {
    expect(DEFAULT_WORKSPACE_LAYOUT.schemaVersion).toBe(LAYOUT_SCHEMA_VERSION);
  });

  it("validates clean against the workspace registry", () => {
    // The transcription's own gate: no duplicate id, no empty slot, no splitter pointing at a slot
    // that is not its region's, no placement naming a piece nobody registered, and no two scrollers
    // fighting over one axis.
    expect(validateLayout(DEFAULT_WORKSPACE_LAYOUT, WORKSPACE_PIECE_REGISTRY)).toEqual([]);
  });

  it("registers every manifest exactly once", () => {
    expect(WORKSPACE_PIECE_DUPLICATES).toEqual([]);
    expect(WORKSPACE_PIECE_REGISTRY.list()).toHaveLength(WORKSPACE_PIECES.length);
  });

  it("places every registered piece, and registers every placed piece", () => {
    // Exact partition, both directions, like the devIds parity gate. Adding a manifest without
    // placing it fails one half; placing an id nobody registered fails the other.
    const placed = [...placedPieceIds(DEFAULT_WORKSPACE_LAYOUT)].sort();
    const registered = WORKSPACE_PIECE_REGISTRY.list()
      .map((manifest) => manifest.id)
      .sort();
    expect(placed).toEqual(registered);
  });

  it("points every manifest's home hint at a region that exists", () => {
    // Auto-placement (plan decision 6) resolves a new piece's home from these. A hint naming a
    // region the document does not have would place the piece nowhere and report nothing.
    for (const manifest of WORKSPACE_PIECES) {
      expect(
        findRegion(DEFAULT_WORKSPACE_LAYOUT, manifest.home.regionId),
        `${manifest.id} homes at ${manifest.home.regionId}`,
      ).not.toBeNull();
    }
  });

  it("carries no per-placement overrides, because the current arrangement has none", () => {
    // The default document IS the shipped design: nothing in it is collapsed, hidden, resized or
    // restyled. Fails if a transcription smuggles an opinion in as an override.
    for (const { node } of layoutPlacements(DEFAULT_WORKSPACE_LAYOUT)) {
      expect(node.collapsed, node.id).toBeUndefined();
      expect(node.hidden, node.id).toBeUndefined();
      expect(node.size, node.id).toBeUndefined();
      expect(node.styleRoles, node.id).toBeUndefined();
    }
  });

  /**
   * Reframed for Phase 2: this pinned the RENDERED arrangement - `ComponentWorkspace.test.tsx` opened
   * the workspace and read the three `[data-workspace-column]` elements back in order - and now it
   * pins the default layout DOCUMENT, because the arrangement is the document's to state. The truth is
   * unchanged: three columns, always all three, in this order, with these identities. A committed
   * redesign that reorders them is a different document and no longer fails a render test that had
   * nothing to do with it, while a regression in THIS document still fails here. That the renderer
   * then draws a band's columns in whatever order its slots name is the engine invariant
   * `engineInvariants.test.tsx` holds, for any document rather than only for this one.
   */
  it("names three column regions, in the order the band draws them", () => {
    const band = findRegion(DEFAULT_WORKSPACE_LAYOUT, "workspace.column-band");
    const columns = (band?.slots ?? []).map((slot) =>
      slot.content?.kind === "region" ? slot.content : null,
    );
    expect(columns.map((region) => region?.id)).toEqual(
      WORKSPACE_COLUMN_IDS.map((id) => WORKSPACE_COLUMN_REGION[id]),
    );
    // The identities the three columns render, which is what a reader (and the coverage gate)
    // recognises them by.
    expect(columns.map((region) => region?.devId)).toEqual([
      "component-browser.column-cad",
      "component-browser.column-specifications",
      "component-browser.column-sourcing",
    ]);
    // Side by side, never stacked and never behind tabs: the band is a ROW.
    expect(band?.mode).toBe("row");
  });

  /**
   * Reframed for Phase 2: this was `ComponentWorkspace.test.tsx`'s "gives every column its own
   * scrollbar and never lets the workspace root scroll", which opened the workspace and read the
   * overflow classes off the rendered elements. The ownership half is the document's, and is stated
   * here; that the RENDERER honours it - one axis per scroller, no page scroll, whatever the document
   * says - is `engineInvariants.test.tsx`, which holds it for arbitrary documents including
   * deliberately rearranged ones.
   */
  it("gives each column region exactly one scroller, and the root none", () => {
    for (const id of WORKSPACE_COLUMN_IDS) {
      const column = findRegion(DEFAULT_WORKSPACE_LAYOUT, WORKSPACE_COLUMN_REGION[id]);
      expect(column?.scroll, `${id} column frame`).toBeUndefined();
      const owners = layoutRegions({ ...DEFAULT_WORKSPACE_LAYOUT, root: column! })
        .filter((visit) => visit.node.scroll !== undefined)
        .map((visit) => [visit.node.id, visit.node.scroll]);
      // Exactly one, and it is the body: the column FRAME is clipped, so a long list cannot push the
      // column's own title strip off the top.
      expect(owners, `${id} column scroll owners`).toEqual([
        [`${WORKSPACE_COLUMN_REGION[id]}-body`, "vertical"],
      ]);
    }
    // The workspace root scrolls nothing at all - the whole no-page-scroll contract begins here.
    expect(DEFAULT_WORKSPACE_LAYOUT.root.scroll).toBeUndefined();
  });

  it("gives each column exactly one scroll owner and the band its sideways overflow", () => {
    // Three scroll owners, one per column, and nothing else - the arrangement contract from
    // ComponentWorkspace.tsx. Fails if a fourth scroller is introduced or a column loses its own.
    const scrollers = layoutRegions(DEFAULT_WORKSPACE_LAYOUT)
      .filter((visit) => visit.node.scroll !== undefined)
      .map((visit) => [visit.node.id, visit.node.scroll]);
    expect(scrollers).toEqual([
      ["workspace.column-band", "horizontal"],
      ["workspace.column-cad-body", "vertical"],
      ["workspace.column-specifications-body", "vertical"],
      ["workspace.column-sourcing-body", "vertical"],
    ]);
  });
});

describe("the three-column geometry the document expresses", () => {
  it("states the same minimums as lib/workspaceColumns, in both content states", () => {
    // Imported and compared, never retyped. Fails if a floor in the document drifts from the one
    // the running layout clamps to.
    expect(workspaceColumnMinimums(DEFAULT_WORKSPACE_LAYOUT, false)).toEqual(
      columnMinimums(false),
    );
    expect(workspaceColumnMinimums(DEFAULT_WORKSPACE_LAYOUT, true)).toEqual(columnMinimums(true));
    // The sparse state changes exactly one floor, and it is sourcing's.
    expect(columnMinimums(false).sourcing).not.toBe(columnMinimums(true).sourcing);
  });

  it("carries BOTH fraction sets at once, so the condition is a runtime input", () => {
    // The whole conditional-geometry claim: one constant document, two geometries, chosen per
    // render. Fails if the document only carries the resting set, or if the sparse set is stored
    // anywhere other than under the sparse-sourcing condition.
    expect(workspaceColumnFractions(DEFAULT_WORKSPACE_LAYOUT, false)).toEqual(
      WORKSPACE_COLUMN_FRACTION,
    );
    expect(workspaceColumnFractions(DEFAULT_WORKSPACE_LAYOUT, true)).toEqual(
      WORKSPACE_COLUMN_FRACTION_SPARSE,
    );
    for (const id of WORKSPACE_COLUMN_IDS) {
      const region = findRegion(DEFAULT_WORKSPACE_LAYOUT, WORKSPACE_COLUMN_REGION[id]);
      expect(region?.size?.when?.[WORKSPACE_CONDITION.sparseSourcing]?.fraction).toBe(
        WORKSPACE_COLUMN_FRACTION_SPARSE[id],
      );
    }
  });

  it("resolves to the same pixel widths the running layout resolves to", () => {
    // The behavioural tie, not just a constant comparison: hand the document's own fractions to the
    // module that owns the maths and it must land where the untouched default lands.
    for (const total of [1366, 1600, 1920, 600]) {
      expect(
        resolveColumnWidths(total, workspaceColumnFractions(DEFAULT_WORKSPACE_LAYOUT, false), false),
      ).toEqual(resolveColumnWidths(total, null, false));
      expect(
        resolveColumnWidths(total, workspaceColumnFractions(DEFAULT_WORKSPACE_LAYOUT, true), true),
      ).toEqual(resolveColumnWidths(total, null, true));
    }
  });

  it("declares the two splitters between the right slots, with the source's own key step", () => {
    // Built from SPLITTER_NEIGHBOURS, so a third column or a re-pairing arrives here automatically.
    const band = findRegion(DEFAULT_WORKSPACE_LAYOUT, "workspace.column-band");
    const splitters = band?.splitters ?? [];
    expect(splitters.map((splitter) => splitter.id)).toEqual(Object.keys(SPLITTER_NEIGHBOURS));
    for (const splitter of splitters) {
      const [left, right] = SPLITTER_NEIGHBOURS[splitter.id as WorkspaceSplitterId];
      const slotOf = (column: string) => `workspace.slot.column-${column}`;
      expect(splitter.between).toEqual([slotOf(left), slotOf(right)]);
      expect(splitter.keyStep).toBe(SPLITTER_KEY_STEP);
      expect(splitter.persistenceKey).toBe(WORKSPACE_COLUMNS_STORAGE_KEY);
      // The drawn rule is 1px; the grab area straddling it is not.
      expect(splitter.lineThickness).toBe(1);
      expect(splitter.grabWidth).toBeGreaterThan(splitter.lineThickness);
    }
    // Every splitter neighbour is a slot of the band itself, which is what validation enforces and
    // this states directly.
    const bandSlots = (band?.slots ?? []).map((slot) => slot.id);
    for (const splitter of splitters) {
      for (const neighbour of splitter.between) expect(bandSlots).toContain(neighbour);
    }
  });
});

describe("the sections each column stacks", () => {
  /**
   * Reframed for Phase 2: the four identity lines' ORDER was pinned in
   * `ComponentWorkspace.test.tsx` by comparing two rendered elements with
   * `compareDocumentPosition` ("never puts a generated name before it"). The order is the document's,
   * so it is stated here; what stayed in the render test is the part that is not about arrangement at
   * all - which line carries the MPN's type role, and that nothing else on the surface claims it.
   */
  it("stacks the identity header's lines in their reading order", () => {
    const lines = findRegion(DEFAULT_WORKSPACE_LAYOUT, "workspace.header-lines");
    expect(
      (lines?.slots ?? []).map((slot) =>
        slot.content?.kind === "placement" ? slot.content.piece : null,
      ),
    ).toEqual([
      "workspace.header-identity",
      "workspace.header-description",
      "workspace.header-classification",
      "workspace.header-key-facts",
      "workspace.header-quality-summary",
    ]);
    // The lines take the band's elastic width; the action group is the band's second slot and takes
    // what it needs.
    expect(lines?.mode).toBe("column");
    expect(lines?.size?.grow).toBe(true);
    const band = findRegion(DEFAULT_WORKSPACE_LAYOUT, "workspace.header-band");
    expect(
      (band?.slots ?? []).map((slot) =>
        slot.content?.kind === "placement" ? slot.content.piece : slot.content?.id,
      ),
    ).toEqual(["workspace.header-lines", "workspace.header-actions"]);
  });

  /**
   * Reframed for Phase 2: `SourcingColumn.test.tsx` opened the workspace and read the six section
   * dev ids back out of the rendered column ("asks the six questions in the order a person asks them,
   * ledger last"). That order is the document's, and this is the one place it is written out in full -
   * the test below it compares the same list against `COLLAPSIBLE_SOURCING_SECTIONS`, so the two
   * together say both "this is the reading order" and "the document did not retype it".
   */
  it("asks the six sourcing questions in the order a person asks them, ledger last", () => {
    const body = findRegion(DEFAULT_WORKSPACE_LAYOUT, "workspace.column-sourcing-body");
    expect(
      (body?.slots ?? []).map((slot) =>
        slot.content?.kind === "placement" ? slot.content.piece : null,
      ),
    ).toEqual([
      "workspace.sourcing-lifecycle",
      "workspace.sourcing-offers",
      "workspace.sourcing-pricing",
      "workspace.sourcing-documents",
      "workspace.sourcing-related",
      "workspace.sourcing-provenance",
      // Last, under everything it accounts for.
      "workspace.sourcing-empty-sections",
    ]);
  });

  /**
   * Reframed for Phase 2: `SpecificationsColumn.test.tsx` asserted the search box's POSITION by
   * walking the rendered tree up to the column ("a real inline input in the column's own toolbar").
   * Where the toolbar sits, and what is on it, is the document's; the render test keeps what the
   * search box IS - an inline input that narrows the list rather than opening a surface.
   */
  it("puts the specifications toolbar above the scroller, with search, filters and anchors on it", () => {
    const column = findRegion(DEFAULT_WORKSPACE_LAYOUT, "workspace.column-specifications");
    expect(
      (column?.slots ?? []).map((slot) =>
        slot.content?.kind === "region" ? slot.content.id : slot.content?.id,
      ),
    ).toEqual([
      "workspace.place.specifications-title",
      "workspace.column-specifications-toolbar",
      // The one scroller, BELOW the toolbar rather than under it - which is what keeps the toolbar and
      // the anchor strip on screen for the whole length of the list.
      "workspace.column-specifications-body",
    ]);
    const toolbar = findRegion(DEFAULT_WORKSPACE_LAYOUT, "workspace.column-specifications-toolbar");
    expect(toolbar?.scroll).toBeUndefined();
    expect(
      (toolbar?.slots ?? []).map((slot) =>
        slot.content?.kind === "placement" ? slot.content.piece : null,
      ),
    ).toEqual([
      "workspace.specifications-search",
      "workspace.specifications-filters",
      "workspace.specifications-anchors",
    ]);
  });

  it("places the three CAD modules as one piece in cadAssetSet's reading order", () => {
    // 3D Model, then Footprint, then Symbol - imported, not restated. Fails if the document
    // reorders them or splits one piece into three manifests.
    const body = findRegion(DEFAULT_WORKSPACE_LAYOUT, "workspace.column-cad-body");
    const placements = (body?.slots ?? []).map((slot) => slot.content);
    expect(placements.map((node) => (node?.kind === "placement" ? node.piece : null))).toEqual(
      REPRESENTATION_KINDS.map(() => "workspace.cad-asset-module"),
    );
    expect(
      placements.map((node) => (node?.kind === "placement" ? node.params?.representation : null)),
    ).toEqual([...REPRESENTATION_KINDS]);
  });

  it("places the sourcing sections in sourcingSections' fixed order, lifecycle first", () => {
    // The order a person asks the questions in. Fails if the document hard-codes an order that
    // drifts from COLLAPSIBLE_SOURCING_SECTIONS.
    const body = findRegion(DEFAULT_WORKSPACE_LAYOUT, "workspace.column-sourcing-body");
    const pieces = (body?.slots ?? []).map((slot) =>
      slot.content?.kind === "placement" ? slot.content.piece : null,
    );
    expect(pieces).toEqual([
      "workspace.sourcing-lifecycle",
      ...COLLAPSIBLE_SOURCING_SECTIONS.map((id) => `workspace.sourcing-${id}`),
      "workspace.sourcing-empty-sections",
    ]);
  });

  it("makes each collapsible sourcing section's visibility content OR the reveal preference", () => {
    // `fill[id] || showEmpty` in SourcingColumn.tsx, as data. Fails if a section is made
    // unconditional, or if the reveal preference is dropped from one of them - which would make
    // revealing the blank sections show four of the five.
    for (const id of COLLAPSIBLE_SOURCING_SECTIONS) {
      const placement = findPlacement(DEFAULT_WORKSPACE_LAYOUT, `workspace.place.sourcing-${id}`);
      expect(placement?.visibility?.anyOf, id).toEqual([
        sourcingFillCondition(id),
        WORKSPACE_CONDITION.sourcingShowEmpty,
      ]);
    }
  });

  it("leaves the lifecycle section unconditional, because it never collapses", () => {
    // sourcingSections.ts states this as a rule; the document has to state it as an absence.
    const lifecycle = findPlacement(
      DEFAULT_WORKSPACE_LAYOUT,
      "workspace.place.sourcing-lifecycle",
    );
    expect(lifecycle?.visibility).toBeUndefined();
  });

  it("repeats the specification groups over the dossier rather than naming them", () => {
    // A category schema decides which groups exist, so naming them would be a document per
    // category - which plan decision 2 rules out.
    const groups = findPlacement(
      DEFAULT_WORKSPACE_LAYOUT,
      "workspace.place.specifications-groups",
    );
    expect(groups?.repeat).toEqual({ over: "dossier.specificationGroups" });
  });
});

describe("the manifests against the id systems that already exist", () => {
  it("names only dev ids the catalogue knows", () => {
    // The piece partition is a coarsening of the dev-id partition. Fails if a manifest claims an
    // element that does not exist, or misspells one.
    const unknown = WORKSPACE_PIECES.flatMap((manifest) =>
      manifest.devIds.filter((id) => !DEV_ID_BY_ID.has(id)).map((id) => `${manifest.id}: ${id}`),
    );
    expect(unknown).toEqual([]);
  });

  it("gives every dev id to at most one piece", () => {
    // Two pieces claiming one element would make an edit ambiguous.
    const seen = new Map<string, string>();
    const collisions: string[] = [];
    for (const manifest of WORKSPACE_PIECES) {
      for (const id of manifest.devIds) {
        const owner = seen.get(id);
        if (owner) collisions.push(`${id}: ${owner} and ${manifest.id}`);
        else seen.set(id, manifest.id);
      }
    }
    expect(collisions).toEqual([]);
  });

  it("names only dev ids the regions actually render", () => {
    const unknown = layoutRegions(DEFAULT_WORKSPACE_LAYOUT)
      .map((visit) => visit.node.devId)
      .filter((id): id is string => typeof id === "string")
      .filter((id) => !DEV_ID_BY_ID.has(id));
    expect(unknown).toEqual([]);
  });

  it("names only copy ids that exist in the interface", () => {
    // A display name is a copy id, never prose. Fails if a manifest invents an id the copy layer
    // has never seen, which would render as nothing at all.
    const missing = WORKSPACE_PIECES.filter(
      (manifest) => manifest.nameCopyId && !SOURCE_TEXT.includes(`"${manifest.nameCopyId}"`),
    ).map((manifest) => `${manifest.id}: ${manifest.nameCopyId}`);
    expect(missing).toEqual([]);
  });

  it("states a size only where a source file states a number", () => {
    // "Do not invent numbers." The only pieces with an intrinsic size are the three 24px column
    // title strips and the 22px status bar, both of which are literal heights in source.
    const sized = WORKSPACE_PIECES.filter(
      (manifest) =>
        manifest.minWidth !== undefined ||
        manifest.minHeight !== undefined ||
        manifest.preferredWidth !== undefined ||
        manifest.preferredHeight !== undefined,
    ).map((manifest) => [manifest.id, manifest.preferredHeight]);
    expect(sized).toEqual([
      ["workspace.cad-title-strip", 24],
      ["workspace.specifications-title-strip", 24],
      ["workspace.sourcing-title-strip", 24],
      ["workspace.status-bar", 22],
    ]);
  });

  it("declares the two piece-level scroll owners, and names their axis", () => {
    // TWO wide tables scroll inside a piece, and both scroll SIDEWAYS: the distributor offers table
    // and the provenance ledger's `Source | Fields Used | Retrieved | State` table. Fails if a piece
    // claims a scroll it does not own, or renders one it does not declare - the second half of which
    // `engineInvariants.test.tsx` holds against the rendered DOM.
    const owners = WORKSPACE_PIECES.filter((manifest) => manifest.scroll.owns);
    expect(owners.map((manifest) => [manifest.id, manifest.scroll.axis])).toEqual([
      ["workspace.sourcing-offers", "horizontal"],
      ["workspace.sourcing-provenance", "horizontal"],
    ]);
    // NO piece scrolls vertically, and that is the load-bearing half: vertical scrolling belongs to
    // the three column bodies, and a piece that took an axis one of them already owns would put two
    // vertical scrollers inside one column with nothing to say which the wheel moves.
    expect(owners.every((manifest) => manifest.scroll.axis === "horizontal")).toBe(true);
    for (const manifest of WORKSPACE_PIECES) {
      if (!manifest.scroll.owns) expect(manifest.scroll.axis, manifest.id).toBeUndefined();
    }
  });
});
