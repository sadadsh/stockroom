/**
 * THE OPENED COMPONENT, AS IT SHIPS TODAY, TRANSCRIBED AS A DOCUMENT.
 *
 * This is not a proposal. Every region, slot and placement below describes an arrangement that is
 * already on the screen: `ComponentWorkspace.tsx`'s three bands, `WorkspaceColumns.tsx`'s three
 * columns and two splitters, and the sections each column stacks. A custom layout is an edit of
 * this document; it is never a fork of the components.
 *
 * WHAT IS OUT OF SCOPE, deliberately. The application shell - the rail, the parts picker and the
 * window's own status bar - is plan Phase 6 and is not modelled here. Neither are the surfaces that
 * open OVER the workspace (`WorkspaceSurfaces`, the datasheet viewer, the dialogs): they are Phase
 * 7. The workspace's loading, failure and empty states are not placements either; they replace the
 * whole workspace rather than sitting in it.
 *
 * THE GEOMETRY IS REFERENCED, NEVER COPIED. Every column minimum, every fraction, the sparse
 * sourcing floor, the splitter neighbours and the keyboard step are imported from
 * `lib/workspaceColumns`, and the reading order of the CAD modules and the order of the conditional
 * sourcing sections are imported from the modules that decide them. A number typed twice is a
 * number that will disagree with itself; the only literals here are the ones this file is the first
 * to state (the splitter's drawn thickness and grab width, read off `WorkspaceColumns.tsx`).
 *
 * HOW CONDITIONS ARE MODELLED - the single most important thing in this file.
 *
 * The document is CONSTANT. The workspace's arrangement changes with the component in front of the
 * reader (a part nobody has sourced draws four fewer sections and narrows a column), and none of
 * that is an edit. So every condition is NAMED here and EVALUATED by the renderer:
 *
 *   VISIBILITY. A placement carries `visibility.anyOf`, a list of condition ids; the renderer draws
 *   the placement when any of them holds. The five conditional sourcing sections are
 *   `[<this section has content>, <this workstation asked to see the blank ones>]`, which is
 *   exactly `fill[id] || showEmpty` in `SourcingColumn.tsx`. The section that never collapses -
 *   lifecycle - carries no visibility at all, which is how the document states that rule.
 *
 *   SPARSE SOURCING. The column band's three regions each carry BOTH of `lib/workspaceColumns`'s
 *   fraction sets and the sourcing column carries both of its minimums, under the condition id
 *   `WORKSPACE_CONDITION.sparseSourcing`. Which set is in force is decided per render from the
 *   projection (`sourcingIsSparse(sourcingSectionFill(...))`), and a stored splitter preference
 *   overrides both - all of which is `resolveColumnWidths`'s job and none of which is the
 *   document's. Nothing here is rewritten when a component with no offers is opened.
 *
 *   REPETITION. A specification group is one placement with a `repeat`, because which groups exist
 *   is the category schema's answer for THIS component. Naming them in the document would produce
 *   a document per category, which plan decision 2 rules out.
 */
import {
  REPRESENTATION_KINDS,
} from "../components/component-workspace/cadAssetSet";
import {
  COLLAPSIBLE_SOURCING_SECTIONS,
  SOURCING_EMPTY_STORAGE_KEY,
  type SourcingSectionId,
} from "../components/component-workspace/sourcingSections";
import {
  SPLITTER_KEY_STEP,
  SPLITTER_NEIGHBOURS,
  WORKSPACE_COLUMN_FRACTION,
  WORKSPACE_COLUMN_FRACTION_SPARSE,
  WORKSPACE_COLUMN_MIN,
  WORKSPACE_COLUMNS_STORAGE_KEY,
  WORKSPACE_SOURCING_SPARSE_MIN,
  type StoredColumnFractions,
  type WorkspaceColumnId,
  type WorkspaceColumnWidths,
  type WorkspaceSplitterId,
} from "../lib/workspaceColumns";
import {
  findRegion,
  LAYOUT_SCHEMA_VERSION,
  type LayoutDocument,
  type LayoutRegion,
  type LayoutSlot,
  type PiecePlacement,
  type SplitterSpec,
} from "./document";
import { WORKSPACE_REGION } from "./workspacePieces";

/**
 * Every runtime condition the workspace document names.
 *
 * A condition id is a QUESTION THE RENDERER CAN ANSWER from the projection, the ui session or a
 * workstation preference - never a value the document stores. Each one below names where its
 * answer comes from.
 */
export const WORKSPACE_CONDITION = {
  /** `sourcingIsSparse(sourcingSectionFill(dossier, developerMode))` - sourcingSections.ts. */
  sparseSourcing: "workspace.sparse-sourcing",
  /** `qualitySummary.description || identity.manufacturer` - ComponentHeader.tsx. */
  headerDescription: "workspace.header-description-present",
  /** `classificationLine(...)` returned something - componentIdentity.ts. */
  headerClassification: "workspace.header-classification-present",
  /** `keyFacts(...)` returned at least one fact - componentIdentity.ts. */
  headerKeyFacts: "workspace.header-key-facts-present",
  /** The key block survived the current filter and search - SpecificationsColumn.tsx. */
  specificationsKeyBlock: "workspace.specifications-key-block-present",
  /** At least one group survived the current filter and search - specificationRows.filterGroups. */
  specificationsGroup: "workspace.specifications-group-present",
  /**
   * NOTHING survived: no key row and no group - SpecificationsColumn's own empty state.
   *
   * Deliberately not the negation of `specificationsGroup`. The column draws its empty state only
   * when the key block is absent TOO, so a filter that left the key rows standing and emptied every
   * group draws the key block and no message, which is what the source does.
   */
  specificationsEmpty: "workspace.specifications-empty",
  /** At least two headings are on screen, so a jump strip has somewhere to go. */
  specificationsAnchors: "workspace.specifications-anchors-available",
  /** `diagnostics.pinCount > 0` - SpecificationsColumn.tsx. */
  specificationsPinout: "workspace.specifications-pinout-present",
  /** This workstation asked for the blank sourcing sections - `readShowEmptySections()`. */
  sourcingShowEmpty: `workspace.preference.${SOURCING_EMPTY_STORAGE_KEY}`,
  /** At least one sourcing section is blank, so the reveal control has something to reveal. */
  sourcingHasEmptySections: "workspace.sourcing-has-empty-sections",
} as const;

/** This sourcing section has content: `sourcingSectionFill(dossier, developerMode)[id]`. */
export function sourcingFillCondition(id: SourcingSectionId): string {
  return `workspace.sourcing-fill.${id}`;
}

/** Which piece draws each conditional sourcing section. */
const SOURCING_SECTION_PIECE: Record<SourcingSectionId, string> = {
  offers: "workspace.sourcing-offers",
  "official-api": "workspace.sourcing-official-api",
  documents: "workspace.sourcing-documents",
  related: "workspace.sourcing-related",
  provenance: "workspace.sourcing-provenance",
};

/** The region each column of `lib/workspaceColumns` is, so geometry can be read back out. */
export const WORKSPACE_COLUMN_REGION: Record<WorkspaceColumnId, string> = {
  cad: WORKSPACE_REGION.cadColumn,
  specifications: WORKSPACE_REGION.specificationsColumn,
  sourcing: WORKSPACE_REGION.sourcingColumn,
};

/** The slot each column occupies in the band, so a splitter can name its two neighbours. */
const WORKSPACE_COLUMN_SLOT: Record<WorkspaceColumnId, string> = {
  cad: "workspace.slot.column-cad",
  specifications: "workspace.slot.column-specifications",
  sourcing: "workspace.slot.column-sourcing",
};

/* -------------------------------------------------------------------------- */
/*  small constructors, so the tree below reads as the screen does             */
/* -------------------------------------------------------------------------- */

function slot(id: string, content: LayoutRegion | PiecePlacement): LayoutSlot {
  return { kind: "slot", id, content };
}

function place(id: string, piece: string): PiecePlacement {
  return { kind: "placement", id, piece };
}

/** A placement the renderer draws only when one of these conditions holds. */
function placeWhen(id: string, piece: string, anyOf: readonly string[]): PiecePlacement {
  return { kind: "placement", id, piece, visibility: { anyOf } };
}

/* -------------------------------------------------------------------------- */
/*  the identity header band - ComponentHeader.tsx                             */
/* -------------------------------------------------------------------------- */

const headerBand: LayoutRegion = {
  kind: "region",
  id: WORKSPACE_REGION.headerBand,
  mode: "row",
  devId: "component-browser.header",
  slots: [
    slot("workspace.slot.header-lines", {
      kind: "region",
      id: WORKSPACE_REGION.headerLines,
      mode: "column",
      // `flex min-w-0 flex-1 flex-col` - the lines take the band's elastic width and the action
      // group takes what it needs.
      size: { grow: true },
      slots: [
        slot(
          "workspace.slot.header-identity",
          place("workspace.place.header-identity", "workspace.header-identity"),
        ),
        slot(
          "workspace.slot.header-description",
          placeWhen(
            "workspace.place.header-description",
            "workspace.header-description",
            [WORKSPACE_CONDITION.headerDescription],
          ),
        ),
        slot(
          "workspace.slot.header-classification",
          placeWhen(
            "workspace.place.header-classification",
            "workspace.header-classification",
            [WORKSPACE_CONDITION.headerClassification],
          ),
        ),
        slot(
          "workspace.slot.header-key-facts",
          placeWhen("workspace.place.header-key-facts", "workspace.header-key-facts", [
            WORKSPACE_CONDITION.headerKeyFacts,
          ]),
        ),
        slot(
          "workspace.slot.header-quality",
          place("workspace.place.header-quality", "workspace.header-quality-summary"),
        ),
      ],
    }),
    slot(
      "workspace.slot.header-actions",
      place("workspace.place.header-actions", "workspace.header-actions"),
    ),
  ],
};

/* -------------------------------------------------------------------------- */
/*  the three-column band - WorkspaceColumns.tsx + lib/workspaceColumns.ts     */
/* -------------------------------------------------------------------------- */

/**
 * One column's size, carrying BOTH geometries at once.
 *
 * The resting numbers are `WORKSPACE_COLUMN_MIN` and `WORKSPACE_COLUMN_FRACTION`; the sparse set is
 * `WORKSPACE_COLUMN_FRACTION_SPARSE`, plus - for sourcing alone - `WORKSPACE_SOURCING_SPARSE_MIN`.
 * Both live in the document at the same time and neither is written by a render.
 */
function columnSize(id: WorkspaceColumnId): LayoutRegion["size"] {
  const sparse: { min?: number; fraction: number } = {
    fraction: WORKSPACE_COLUMN_FRACTION_SPARSE[id],
  };
  // Only the sourcing column has a second floor: it is the one column whose reason for its
  // minimum (a provider name beside a price) can be absent from the component itself.
  if (id === "sourcing") sparse.min = WORKSPACE_SOURCING_SPARSE_MIN;
  return {
    min: WORKSPACE_COLUMN_MIN[id],
    fraction: WORKSPACE_COLUMN_FRACTION[id],
    // The band gives the LAST column the remainder (`flex-1` with a minimum) while the first two
    // are `flex-none` at a computed width - WorkspaceColumns.tsx.
    ...(id === "sourcing" ? { grow: true } : {}),
    when: { [WORKSPACE_CONDITION.sparseSourcing]: sparse },
  };
}

/** The CAD column: title strip, the preferred-source row, then the three modules that scroll. */
const cadColumn: LayoutRegion = {
  kind: "region",
  id: WORKSPACE_REGION.cadColumn,
  mode: "column",
  devId: "component-browser.column-cad",
  size: columnSize("cad"),
  slots: [
    slot(
      "workspace.slot.cad-title",
      place("workspace.place.cad-title", "workspace.cad-title-strip"),
    ),
    slot(
      "workspace.slot.cad-toolbar",
      place("workspace.place.cad-preferred-source", "workspace.cad-preferred-source"),
    ),
    slot("workspace.slot.cad-body", {
      kind: "region",
      id: WORKSPACE_REGION.cadBody,
      mode: "column",
      size: { grow: true },
      // The column owns exactly one scrollbar, and this is it.
      scroll: "vertical",
      // Three placements of ONE piece, in `cadAssetSet.REPRESENTATION_KINDS` order: 3D Model, then
      // Footprint, then Symbol - the inspection order, imported rather than restated.
      slots: REPRESENTATION_KINDS.map((kind) =>
        slot(`workspace.slot.cad-${kind}`, {
          kind: "placement",
          id: `workspace.place.cad-${kind}`,
          piece: "workspace.cad-asset-module",
          params: { representation: kind },
        }),
      ),
    }),
  ],
};

/** The Specifications column: title strip, the toolbar rows, then the sections that scroll. */
const specificationsColumn: LayoutRegion = {
  kind: "region",
  id: WORKSPACE_REGION.specificationsColumn,
  mode: "column",
  devId: "component-browser.column-specifications",
  size: columnSize("specifications"),
  slots: [
    slot(
      "workspace.slot.specifications-title",
      place("workspace.place.specifications-title", "workspace.specifications-title-strip"),
    ),
    slot("workspace.slot.specifications-toolbar", {
      kind: "region",
      id: WORKSPACE_REGION.specificationsToolbar,
      mode: "column",
      // ABOVE the scroller, not sticky inside it: the column has exactly one scroll container and
      // this is what keeps it that way.
      slots: [
        slot(
          "workspace.slot.specifications-search",
          place("workspace.place.specifications-search", "workspace.specifications-search"),
        ),
        slot(
          "workspace.slot.specifications-filters",
          place("workspace.place.specifications-filters", "workspace.specifications-filters"),
        ),
        slot(
          "workspace.slot.specifications-anchors",
          placeWhen(
            "workspace.place.specifications-anchors",
            "workspace.specifications-anchors",
            [WORKSPACE_CONDITION.specificationsAnchors],
          ),
        ),
      ],
    }),
    slot("workspace.slot.specifications-body", {
      kind: "region",
      id: WORKSPACE_REGION.specificationsBody,
      mode: "column",
      size: { grow: true },
      scroll: "vertical",
      slots: [
        slot(
          "workspace.slot.specifications-key-block",
          placeWhen(
            "workspace.place.specifications-key-block",
            "workspace.specifications-key-block",
            [WORKSPACE_CONDITION.specificationsKeyBlock],
          ),
        ),
        slot("workspace.slot.specifications-groups", {
          kind: "placement",
          id: "workspace.place.specifications-groups",
          piece: "workspace.specifications-group",
          visibility: { anyOf: [WORKSPACE_CONDITION.specificationsGroup] },
          repeat: { over: "dossier.specificationGroups" },
        }),
        // The column's own empty state, which is a PLACEMENT rather than something the scroller
        // draws by itself: it sits between the groups and the pinout in the current arrangement,
        // and a message with a position is something a redesign has to be able to move.
        slot(
          "workspace.slot.specifications-empty",
          placeWhen("workspace.place.specifications-empty", "workspace.specifications-empty", [
            WORKSPACE_CONDITION.specificationsEmpty,
          ]),
        ),
        slot(
          "workspace.slot.specifications-pinout",
          placeWhen("workspace.place.specifications-pinout", "workspace.specifications-pinout", [
            WORKSPACE_CONDITION.specificationsPinout,
          ]),
        ),
      ],
    }),
  ],
};

/**
 * The Sourcing and Resources column: distributor ladders first, then returned supply facts and
 * supporting resources. The redundant aggregate-pricing piece remains available to Design Studio
 * but is not part of the shipped reading order.
 */
const sourcingColumn: LayoutRegion = {
  kind: "region",
  id: WORKSPACE_REGION.sourcingColumn,
  mode: "column",
  devId: "component-browser.column-sourcing",
  size: columnSize("sourcing"),
  slots: [
    slot(
      "workspace.slot.sourcing-title",
      place("workspace.place.sourcing-title", "workspace.sourcing-title-strip"),
    ),
    slot("workspace.slot.sourcing-body", {
      kind: "region",
      id: WORKSPACE_REGION.sourcingBody,
      mode: "column",
      size: { grow: true },
      scroll: "vertical",
      slots: [
        slot(
          "workspace.slot.sourcing-offers",
          placeWhen(
            "workspace.place.sourcing-offers",
            "workspace.sourcing-offers",
            [sourcingFillCondition("offers"), WORKSPACE_CONDITION.sourcingShowEmpty],
          ),
        ),
        slot(
          "workspace.slot.sourcing-lifecycle",
          place("workspace.place.sourcing-lifecycle", "workspace.sourcing-lifecycle"),
        ),
        ...COLLAPSIBLE_SOURCING_SECTIONS.filter((section) => section !== "offers").map((section) =>
          slot(
            `workspace.slot.sourcing-${section}`,
            placeWhen(
              `workspace.place.sourcing-${section}`,
              SOURCING_SECTION_PIECE[section],
              [sourcingFillCondition(section), WORKSPACE_CONDITION.sourcingShowEmpty],
            ),
          ),
        ),
        slot(
          "workspace.slot.sourcing-empty-sections",
          placeWhen(
            "workspace.place.sourcing-empty-sections",
            "workspace.sourcing-empty-sections",
            [WORKSPACE_CONDITION.sourcingHasEmptySections],
          ),
        ),
      ],
    }),
  ],
};

/** The two splitters, built from `SPLITTER_NEIGHBOURS` so the pairing cannot drift. */
const columnSplitters: readonly SplitterSpec[] = (
  Object.keys(SPLITTER_NEIGHBOURS) as WorkspaceSplitterId[]
).map((id) => {
  const [left, right] = SPLITTER_NEIGHBOURS[id];
  return {
    id,
    between: [WORKSPACE_COLUMN_SLOT[left], WORKSPACE_COLUMN_SLOT[right]] as const,
    keyStep: SPLITTER_KEY_STEP,
    // The LINE is 1px; the grab area is 9px of transparent padding straddling it, which is what a
    // pointer can actually catch. Both read off `ColumnSplitter` in WorkspaceColumns.tsx.
    lineThickness: 1,
    grabWidth: 9,
    persistenceKey: WORKSPACE_COLUMNS_STORAGE_KEY,
  };
});

const columnBand: LayoutRegion = {
  kind: "region",
  id: WORKSPACE_REGION.columnBand,
  mode: "row",
  devId: "component-browser.columns",
  size: { grow: true },
  // `overflow-y-hidden overflow-x-auto`: below the three columns' combined minimum the band scrolls
  // SIDEWAYS rather than losing a column, and it never grows a vertical scrollbar.
  scroll: "horizontal",
  splitters: columnSplitters,
  slots: [
    slot(WORKSPACE_COLUMN_SLOT.cad, cadColumn),
    slot(WORKSPACE_COLUMN_SLOT.specifications, specificationsColumn),
    slot(WORKSPACE_COLUMN_SLOT.sourcing, sourcingColumn),
  ],
};

/* -------------------------------------------------------------------------- */
/*  the component's own status bar - WorkspaceStatusBar.tsx                    */
/* -------------------------------------------------------------------------- */

const statusBand: LayoutRegion = {
  kind: "region",
  id: WORKSPACE_REGION.statusBand,
  mode: "row",
  slots: [
    slot(
      "workspace.slot.status-bar",
      place("workspace.place.status-bar", "workspace.status-bar"),
    ),
  ],
};

/* -------------------------------------------------------------------------- */

/**
 * The shipped arrangement: three bands that never move, in a frame that never scrolls.
 *
 * `flex h-full min-h-0 flex-col overflow-hidden` on the workspace root is the whole contract - the
 * header and the status bar are fixed, the column band takes the rest, and nothing here may grow a
 * page scrollbar.
 */
export const DEFAULT_WORKSPACE_LAYOUT: LayoutDocument = {
  schemaVersion: LAYOUT_SCHEMA_VERSION,
  id: "workspace.component",
  root: {
    kind: "region",
    id: WORKSPACE_REGION.root,
    mode: "column",
    devId: "component-browser.root",
    slots: [
      slot("workspace.slot.header-band", headerBand),
      slot("workspace.slot.column-band", columnBand),
      slot("workspace.slot.status-band", statusBand),
    ],
  },
};

/* -------------------------------------------------------------------------- */
/*  reading the geometry back out                                              */
/* -------------------------------------------------------------------------- */

/**
 * The three fractions this document opens at, as `lib/workspaceColumns` wants them.
 *
 * The renderer hands the result straight to `resolveColumnWidths`, which is what keeps the pixel
 * maths in the one module that already owns it. A column whose region or fraction is missing from
 * the document falls back to the shipped constant rather than to zero: a layout that lost a column
 * region should render the column at its default width, not at no width at all.
 */
export function workspaceColumnFractions(
  document: LayoutDocument,
  sparseSourcing = false,
): StoredColumnFractions {
  const read = (id: WorkspaceColumnId): number => {
    const region = findRegion(document, WORKSPACE_COLUMN_REGION[id]);
    const size = region?.size;
    if (!size) return WORKSPACE_COLUMN_FRACTION[id];
    const override = sparseSourcing
      ? size.when?.[WORKSPACE_CONDITION.sparseSourcing]
      : undefined;
    return override?.fraction ?? size.fraction ?? WORKSPACE_COLUMN_FRACTION[id];
  };
  return {
    cad: read("cad"),
    specifications: read("specifications"),
    sourcing: read("sourcing"),
  };
}

/** The three floors this document declares, under the same fallback rule as the fractions. */
export function workspaceColumnMinimums(
  document: LayoutDocument,
  sparseSourcing = false,
): WorkspaceColumnWidths {
  const read = (id: WorkspaceColumnId): number => {
    const region = findRegion(document, WORKSPACE_COLUMN_REGION[id]);
    const size = region?.size;
    if (!size) return WORKSPACE_COLUMN_MIN[id];
    const override = sparseSourcing
      ? size.when?.[WORKSPACE_CONDITION.sparseSourcing]
      : undefined;
    return override?.min ?? size.min ?? WORKSPACE_COLUMN_MIN[id];
  };
  return {
    cad: read("cad"),
    specifications: read("specifications"),
    sourcing: read("sourcing"),
  };
}
