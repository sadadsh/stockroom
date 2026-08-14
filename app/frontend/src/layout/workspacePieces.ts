/**
 * EVERY PLACEABLE UNIT OF THE OPENED COMPONENT, transcribed from the arrangement that ships today.
 *
 * One manifest per piece, read off the current components rather than off an intention: the data
 * needs are the props and hooks those components actually consume, the actions are the callbacks
 * they actually invoke, and a size appears only where a source file states a number. Where the
 * current arrangement gives a piece no heading of its own there is no `nameCopyId`, because the
 * alternative would be inventing interface text in a data module.
 *
 * THE GRANULARITY RULE, applied the same way everywhere: a piece is the smallest unit somebody
 * could sensibly MOVE, HIDE OR RESTYLE ON ITS OWN, and it is never smaller than that. Four
 * consequences, each of which reads as a judgement call and each of which is the same call:
 *
 *   The identity header is FIVE pieces plus its action group, not one. Its four lines are four
 *   different claims at four different weights, three of them independently conditional in source,
 *   and each already carries its own `data-dev-id`. One header piece would make "drop the
 *   classification line" an impossible edit.
 *
 *   A section is a piece; a ROW inside it is not. The Documents section is one piece even though it
 *   renders a row per document, because a row is an instance of data and the section is the thing
 *   that has a position. The same for offers, related parts, provenance and every specification
 *   group.
 *
 *   The three CAD asset modules are ONE piece placed three times, parameterised by representation
 *   kind. They are the same component with the same needs and the same actions; three manifests
 *   would be three copies of one contract that could drift apart, and per-placement settings exist
 *   precisely so three appearances of one piece can differ.
 *
 *   A column's 24px title strip is a piece. It carries the column's name, its count and - on CAD -
 *   the column's one action, and Phase 3 has to be able to restyle or hide that band without
 *   touching what scrolls underneath it.
 *
 * WHAT IS NOT HERE: the application shell (rail, parts picker, application status bar) and every
 * surface that opens over the workspace (the modals, the datasheet viewer, the sheets). The shell
 * is plan Phase 6 and the overlay surfaces are Phase 7; modelling either here would commit to a
 * region tree nobody has transcribed yet.
 *
 * ACTION IDS ARE DECLARED NAMES. The action registry is plan 1.3, a later phase. A string here
 * asserts "this piece is the way in to that command" and nothing more; when the registry lands,
 * these are the ids it has to answer for.
 */
import { registerPieces, type PieceManifest, type PieceRegistry } from "./registry";

/** The region ids the manifests point their home hints at. Mirrored by the default document. */
export const WORKSPACE_REGION = {
  root: "workspace.root",
  headerBand: "workspace.header-band",
  headerLines: "workspace.header-lines",
  columnBand: "workspace.column-band",
  cadColumn: "workspace.column-cad",
  cadBody: "workspace.column-cad-body",
  specificationsColumn: "workspace.column-specifications",
  specificationsToolbar: "workspace.column-specifications-toolbar",
  specificationsBody: "workspace.column-specifications-body",
  sourcingColumn: "workspace.column-sourcing",
  sourcingBody: "workspace.column-sourcing-body",
  statusBand: "workspace.status-band",
} as const;

/** The sibling groups auto-placement keeps a new piece inside. */
const GROUP = {
  headerLines: "workspace.header-lines",
  headerActions: "workspace.header-actions",
  columnChrome: "workspace.column-chrome",
  cadAssets: "workspace.cad-assets",
  specificationsToolbar: "workspace.specifications-toolbar",
  specificationsSections: "workspace.specifications-sections",
  sourcingSections: "workspace.sourcing-sections",
  statusBar: "workspace.status-bar",
} as const;

const HEADER_SOURCE = "components/component-workspace/ComponentHeader.tsx";
const CAD_SOURCE = "components/component-workspace/CadAssetsColumn.tsx";
const SPEC_SOURCE = "components/component-workspace/SpecificationsPieces.tsx";
const SOURCING_SOURCE = "components/component-workspace/SourcingColumn.tsx";

/**
 * The manifests, in the order the workspace reads top to bottom and left to right.
 *
 * Order is not load-bearing for correctness - the registry is keyed by id - but it is how a person
 * reads this file against the running application, so it matches the screen.
 */
export const WORKSPACE_PIECES: readonly PieceManifest[] = [
  /* ---------------------------------------------------------------- header */

  // ComponentHeader.tsx, line 1. The MPN and the lifecycle state share one baseline row and are
  // one piece: the state is aligned in its own slot BESIDE the part number and moving one without
  // the other would produce the "SN74LVC1G08DBVR Active" reading the header exists to prevent.
  {
    id: "workspace.header-identity",
    devIds: ["component-browser.header-mpn", "component-browser.header-lifecycle"],
    dataNeeds: [
      "dossier.identity.mpn",
      "dossier.identity.displayName",
      "dossier.identity.lifecycle",
    ],
    actions: [],
    scroll: { owns: false },
    home: { regionId: WORKSPACE_REGION.headerLines, siblingGroup: GROUP.headerLines },
    source: HEADER_SOURCE,
  },
  // ComponentHeader.tsx, line 2. Rendered only when there is a manufacturer or a description.
  {
    id: "workspace.header-description",
    devIds: ["component-browser.header-description"],
    dataNeeds: ["dossier.identity.manufacturer", "dossier.qualitySummary.description"],
    actions: [],
    scroll: { owns: false },
    home: { regionId: WORKSPACE_REGION.headerLines, siblingGroup: GROUP.headerLines },
    source: HEADER_SOURCE,
  },
  // ComponentHeader.tsx, line 3, via componentIdentity.classificationLine: category, package and
  // pin count, each dropped when line 2 already said it.
  {
    id: "workspace.header-classification",
    devIds: ["component-browser.header-classification"],
    dataNeeds: [
      "dossier.identity.category",
      "dossier.identity.package",
      "dossier.identity.pinCount",
    ],
    actions: [],
    scroll: { owns: false },
    home: { regionId: WORKSPACE_REGION.headerLines, siblingGroup: GROUP.headerLines },
    source: HEADER_SOURCE,
  },
  // ComponentHeader.tsx, line 4, via componentIdentity.keyFacts: the category schema's own key set,
  // never re-scanned from the groups.
  {
    id: "workspace.header-key-facts",
    devIds: ["component-browser.header-key-facts"],
    dataNeeds: ["dossier.keySpecifications"],
    actions: [],
    scroll: { owns: false },
    home: { regionId: WORKSPACE_REGION.headerLines, siblingGroup: GROUP.headerLines },
    source: HEADER_SOURCE,
  },
  // ComponentHeader.tsx `QualitySummary`. One piece, not one per segment: the segments are derived
  // from the dossier as a set and the separators between them are the piece's own.
  {
    id: "workspace.header-quality-summary",
    devIds: ["component-browser.quality-summary", "component-browser.quality-segment"],
    dataNeeds: [
      "dossier.qualitySummary.stateCounts.missing",
      "dossier.qualitySummary.stateCounts.conflicting",
      "dossier.cadAssets.kinds",
    ],
    actions: [
      "component-browser.filter-missing-specifications",
      "component-browser.filter-conflicting-specifications",
      "component-browser.focus-cad-asset",
    ],
    scroll: { owns: false },
    home: { regionId: WORKSPACE_REGION.headerLines, siblingGroup: GROUP.headerLines },
    source: HEADER_SOURCE,
  },
  // ComponentHeader.tsx, the right-hand action group: Datasheet (with its menu), Manufacturer Page
  // when the projection verified the host, Copy MPN, and the Manage menu. ONE piece, because the
  // group is a single right-aligned cluster whose entries appear and disappear with what the
  // machine and the component can do - the Manage inventory is `manageActions.tsx`.
  {
    id: "workspace.header-actions",
    devIds: [
      "component-browser.header-actions",
      "component-browser.header-datasheet",
      "component-browser.header-manufacturer-page",
      "component-browser.copy-mpn",
      "component-browser.manage",
    ],
    dataNeeds: [
      "dossier.documents",
      "dossier.identity.mpn",
      "dossier.identity.manufacturerPage",
      "query.part-shell",
    ],
    actions: [
      "component-browser.open-datasheet",
      "component-browser.find-datasheet",
      "component-browser.open-manufacturer-page",
      "component-browser.copy-mpn",
      "component-browser.edit-identity",
      "component-browser.edit-classification",
      "component-browser.review-missing",
      "component-browser.refresh",
      "component-browser.manage-models",
      "component-browser.view-provenance",
      "component-browser.export",
      "component-browser.open-in",
      "component-browser.reveal",
      "component-browser.delete",
    ],
    scroll: { owns: false },
    home: { regionId: WORKSPACE_REGION.headerBand, siblingGroup: GROUP.headerActions },
    source: HEADER_SOURCE,
  },

  /* ------------------------------------------------------------- cad column */

  // WorkspaceColumns.tsx `WorkspaceColumn` header: name, view tabs, and attached count.
  {
    id: "workspace.cad-title-strip",
    nameCopyId: "component-browser.column-cad",
    devIds: [
      "component-browser.column-cad",
      "component-browser.cad-tab-models",
      "component-browser.cad-tab-manage-models",
    ],
    dataNeeds: ["dossier.cadAssets.kinds"],
    actions: ["component-browser.manage-models"],
    preferredHeight: 24,
    scroll: { owns: false },
    home: { regionId: WORKSPACE_REGION.cadColumn, siblingGroup: GROUP.columnChrome },
    source: "components/component-workspace/WorkspaceColumns.tsx",
  },
  // CadAssetsColumn.tsx `toolbar`: the preferred-source control, plus Show All Three while one
  // module is focused. One piece - it is one control row, and the second control exists only to
  // undo the state the first row is in.
  {
    id: "workspace.cad-preferred-source",
    devIds: ["component-browser.preferred-source", "component-browser.show-all-assets"],
    dataNeeds: ["dossier.cadAssets.preference"],
    actions: [
      "component-browser.set-cad-set-source",
      "component-browser.clear-cad-set-source",
      "component-browser.show-all-cad-assets",
    ],
    scroll: { owns: false },
    home: { regionId: WORKSPACE_REGION.cadColumn, siblingGroup: GROUP.columnChrome },
    source: CAD_SOURCE,
  },
  // CadAssetModule.tsx. ONE manifest, placed once per `cadAssetSet.REPRESENTATION_KINDS` entry with
  // the kind as a placement parameter. Every module has the same needs and the same actions; what
  // differs is which representation it draws, which is exactly what a per-placement parameter is.
  {
    id: "workspace.cad-asset-module",
    devIds: [
      "component-browser.cad-asset",
      "component-browser.asset-header",
      "component-browser.asset-preview",
      "component-browser.asset-control-strip",
      "component-browser.asset-issue",
      "component-browser.asset-evidence",
    ],
    dataNeeds: [
      "dossier.cadAssets.kinds",
      "dossier.cadAssets.preference",
      "dossier.keySpecifications",
      "dossier.specificationGroups",
      "query.symbol-geometry",
      "query.land-pattern",
      "query.preview-glb",
      "session.representation_layout",
    ],
    actions: [
      "component-browser.focus-cad-asset",
      "component-browser.open-full-preview",
      "component-browser.toggle-asset-layer",
      "component-browser.measure-footprint",
    ],
    scroll: { owns: false },
    home: { regionId: WORKSPACE_REGION.cadBody, siblingGroup: GROUP.cadAssets },
    source: "components/component-workspace/CadAssetModule.tsx",
  },

  /* --------------------------------------------------- specifications column */

  {
    id: "workspace.specifications-title-strip",
    nameCopyId: "component-browser.column-specifications",
    devIds: ["component-browser.column-specifications"],
    dataNeeds: ["dossier.specificationGroups", "dossier.keySpecifications"],
    actions: [],
    preferredHeight: 24,
    scroll: { owns: false },
    home: {
      regionId: WORKSPACE_REGION.specificationsColumn,
      siblingGroup: GROUP.columnChrome,
    },
    source: "components/component-workspace/WorkspaceColumns.tsx",
  },
  // SpecificationsColumn.tsx toolbar, first row. Its own piece rather than part of a single
  // toolbar piece: search and the filters narrow the same list by different rules and each already
  // carries its own dev id, so hiding one has to be possible without hiding the other.
  {
    id: "workspace.specifications-search",
    devIds: ["component-browser.spec-search"],
    dataNeeds: [],
    actions: ["component-browser.search-specifications"],
    scroll: { owns: false },
    home: {
      regionId: WORKSPACE_REGION.specificationsToolbar,
      siblingGroup: GROUP.specificationsToolbar,
    },
    source: SPEC_SOURCE,
  },
  // SpecificationsColumn.tsx toolbar, second row: the four filters from `specificationRows`, each
  // with its own count.
  {
    id: "workspace.specifications-filters",
    devIds: ["component-browser.spec-filter"],
    dataNeeds: ["dossier.specificationGroups", "dossier.keySpecifications"],
    actions: ["component-browser.filter-specifications"],
    scroll: { owns: false },
    home: {
      regionId: WORKSPACE_REGION.specificationsToolbar,
      siblingGroup: GROUP.specificationsToolbar,
    },
    source: SPEC_SOURCE,
  },
  // SpecificationsColumn.tsx `SectionAnchorStrip`. Separately placeable because it is separately
  // conditional: it renders only where the current filter leaves at least two headings on screen.
  {
    id: "workspace.specifications-anchors",
    devIds: ["component-browser.spec-anchors", "component-browser.spec-anchor"],
    dataNeeds: ["dossier.specificationGroups", "dossier.keySpecifications"],
    actions: ["component-browser.jump-to-specification-section"],
    scroll: { owns: false },
    home: {
      regionId: WORKSPACE_REGION.specificationsToolbar,
      siblingGroup: GROUP.specificationsToolbar,
    },
    source: SPEC_SOURCE,
  },
  // SpecificationsColumn.tsx, the key block. A distinct piece from a specification group: it is
  // promoted out of the groups by the category schema, it is emphasised, and it anchors under its
  // own `KEY_SECTION_ID` rather than under a group id the dossier sent.
  {
    id: "workspace.specifications-key-block",
    nameCopyId: "component-browser.key-specs-title",
    devIds: ["component-browser.key-specs"],
    dataNeeds: ["dossier.keySpecifications"],
    actions: [
      "component-browser.write-specification",
      "component-browser.use-alternate-value",
      "component-browser.add-override",
      "component-browser.clear-override",
      "component-browser.clear-preferred-source",
      "component-browser.view-specification-source",
    ],
    scroll: { owns: false },
    home: {
      regionId: WORKSPACE_REGION.specificationsBody,
      siblingGroup: GROUP.specificationsSections,
    },
    source: SPEC_SOURCE,
  },
  // SpecificationsColumn.tsx, one specification group. ONE piece placed once and repeated per group
  // at render: which groups exist is the category schema's answer for THIS component, so a document
  // that named them would be a document per category - which plan decision 2 explicitly rules out.
  {
    id: "workspace.specifications-group",
    devIds: [
      "component-browser.spec-group",
      "component-browser.spec-group-toggle",
      "component-browser.spec-row",
    ],
    dataNeeds: ["dossier.specificationGroups"],
    actions: [
      "component-browser.toggle-specification-group",
      "component-browser.write-specification",
      "component-browser.use-alternate-value",
      "component-browser.add-override",
      "component-browser.clear-override",
      "component-browser.clear-preferred-source",
      "component-browser.view-specification-source",
    ],
    scroll: { owns: false },
    home: {
      regionId: WORKSPACE_REGION.specificationsBody,
      siblingGroup: GROUP.specificationsSections,
    },
    source: SPEC_SOURCE,
  },
  // SpecificationsColumn.tsx, the message the column draws when the filter left nothing at all.
  // A piece rather than chrome, because it has a POSITION - between the groups and the pinout - and
  // Phase 3 has to be able to move or restyle it. It carries no dev id and no name: the two
  // sentences it can say are `EmptyState`s addressed by copy id, and `EmptyState` only emits a
  // `data-dev-id` when a caller passes one, which this call site never has.
  {
    id: "workspace.specifications-empty",
    devIds: [],
    dataNeeds: ["dossier.specificationGroups", "dossier.keySpecifications"],
    actions: [],
    scroll: { owns: false },
    home: {
      regionId: WORKSPACE_REGION.specificationsBody,
      siblingGroup: GROUP.specificationsSections,
    },
    source: SPEC_SOURCE,
  },
  // SpecificationsColumn.tsx, the pinout section: a heading, a count, and the one control that
  // opens the genuinely tabular surface.
  {
    id: "workspace.specifications-pinout",
    nameCopyId: "component-browser.pinout-section",
    devIds: ["component-browser.pinout", "component-browser.pinout-open"],
    dataNeeds: ["dossier.diagnostics.pinCount"],
    actions: ["component-browser.view-pinout"],
    scroll: { owns: false },
    home: {
      regionId: WORKSPACE_REGION.specificationsBody,
      siblingGroup: GROUP.specificationsSections,
    },
    source: SPEC_SOURCE,
  },

  /* --------------------------------------------------------- sourcing column */

  {
    id: "workspace.sourcing-title-strip",
    nameCopyId: "component-browser.column-sourcing",
    devIds: ["component-browser.column-sourcing"],
    dataNeeds: ["dossier.supplySummary.offerCount"],
    actions: [],
    preferredHeight: 24,
    scroll: { owns: false },
    home: { regionId: WORKSPACE_REGION.sourcingColumn, siblingGroup: GROUP.columnChrome },
    source: "components/component-workspace/WorkspaceColumns.tsx",
  },
  // SourcingColumn.tsx `LifecycleSection`. The one section in this column that never collapses -
  // see sourcingSections.ts: `Last Checked: Unknown` is the fact that explains the empty rest.
  {
    id: "workspace.sourcing-lifecycle",
    nameCopyId: "component-browser.lifecycle-title",
    devIds: [
      "component-browser.lifecycle",
      "component-browser.lifecycle-details",
      "component-browser.manufacturer-status",
      "component-browser.total-stock",
    ],
    dataNeeds: [
      "dossier.supplySummary.lifecycle",
      "dossier.supplySummary.manufacturerStatus",
      "dossier.supplySummary.totalStock",
      "dossier.supplySummary.leadTime",
      "dossier.supplySummary.staleness",
      "dossier.identity.lifecycle",
      "dossier.distributorOffers",
    ],
    actions: [],
    scroll: { owns: false },
    home: { regionId: WORKSPACE_REGION.sourcingBody, siblingGroup: GROUP.sourcingSections },
    source: SOURCING_SOURCE,
  },
  // OffersSection.tsx. Each provider is a wrapping fact ledger with its complete price ladder.
  // The Sourcing column owns vertical movement; this piece must never introduce a second,
  // horizontal reading axis.
  {
    id: "workspace.sourcing-offers",
    nameCopyId: "component-browser.offers-title",
    devIds: [
      "component-browser.offers",
      "component-browser.offers-table",
      "component-browser.offer-row",
      "component-browser.offer-price-ladder",
      "component-browser.offer-details",
      "component-browser.offer-failures",
      "component-browser.offer-listing",
      "component-browser.refresh-offers",
    ],
    dataNeeds: ["dossier.distributorOffers", "dossier.supplySummary.failures"],
    actions: [
      "component-browser.refresh",
      "component-browser.open-offer-listing",
    ],
    scroll: { owns: false },
    home: { regionId: WORKSPACE_REGION.sourcingBody, siblingGroup: GROUP.sourcingSections },
    source: "components/component-workspace/OffersSection.tsx",
  },
  {
    id: "workspace.sourcing-official-api",
    nameCopyId: "component-browser.official-api-data-title",
    devIds: [
      "component-browser.official-api-data",
      "component-browser.official-api-search",
      "component-browser.official-api-provider",
      "component-browser.official-api-endpoint",
      "component-browser.official-api-row",
    ],
    dataNeeds: ["dossier.officialApiData"],
    actions: [],
    scroll: { owns: false },
    home: { regionId: WORKSPACE_REGION.sourcingBody, siblingGroup: GROUP.sourcingSections },
    source: "components/component-workspace/OfficialApiDataSection.tsx",
  },
  {
    id: "workspace.sourcing-documents",
    nameCopyId: "component-browser.documents-title",
    devIds: [
      "component-browser.documents",
      "component-browser.preferred-datasheet-reason",
      "component-browser.document-row",
      "component-browser.document-details",
      "component-browser.document-open",
    ],
    dataNeeds: ["dossier.documents.items", "dossier.documents.preferredDatasheetReason"],
    actions: ["component-browser.open-document"],
    scroll: { owns: false },
    home: { regionId: WORKSPACE_REGION.sourcingBody, siblingGroup: GROUP.sourcingSections },
    source: "components/component-workspace/ResourcesSection.tsx",
  },
  {
    id: "workspace.sourcing-related",
    nameCopyId: "component-browser.related-title",
    devIds: [
      "component-browser.related",
      "component-browser.related-row",
      "component-browser.related-evidence",
      "component-browser.related-not-validated",
    ],
    dataNeeds: ["dossier.relatedParts"],
    actions: ["component-browser.open-related-part"],
    scroll: { owns: false },
    home: { regionId: WORKSPACE_REGION.sourcingBody, siblingGroup: GROUP.sourcingSections },
    source: "components/component-workspace/ResourcesSection.tsx",
  },
  // ProvenanceHistory.tsx. ONE piece for six sub-questions: they are sub-headings at property-label
  // weight inside one section, and promoting any of them to a piece would put Manual Overrides at
  // the same weight as Distributor Offers, which is the arrangement this column was rebuilt out of.
  {
    id: "workspace.sourcing-provenance",
    nameCopyId: "component-browser.provenance-title",
    devIds: [
      "component-browser.provenance",
      "component-browser.compatibility-notice",
      "component-browser.provenance-sources",
      "component-browser.provenance-conflicts",
      "component-browser.provenance-overrides",
      "component-browser.provenance-intake",
      "component-browser.provenance-revisions",
      "component-browser.provenance-diagnostics",
      "component-browser.provenance-nothing",
      "component-browser.provenance-all",
    ],
    dataNeeds: [
      "dossier.provenance",
      "dossier.revisions",
      "dossier.diagnostics",
      "devMode.enabled",
    ],
    actions: ["component-browser.view-provenance"],
    // The `Source | Fields Used | Retrieved | State` table inside
    // `component-browser.provenance-sources` is wrapped in an `overflow-x-auto` div, exactly as the
    // offers table is: four columns of named facts do not fit a ~300px column, and scrolling the
    // table SIDEWAYS is what keeps the section's own width off the column's.
    scroll: { owns: true, axis: "horizontal" },
    home: { regionId: WORKSPACE_REGION.sourcingBody, siblingGroup: GROUP.sourcingSections },
    source: "components/component-workspace/ProvenanceHistory.tsx",
  },
  // SourcingColumn.tsx `EmptySectionsToggle`. Last, under everything it accounts for, and its own
  // piece: it is a control over the five conditional sections rather than a part of any of them.
  {
    id: "workspace.sourcing-empty-sections",
    devIds: ["component-browser.empty-sections"],
    dataNeeds: [
      "dossier.distributorOffers",
      "dossier.supplySummary",
      "dossier.documents.items",
      "dossier.relatedParts",
      "dossier.provenance",
      "dossier.revisions",
      "devMode.enabled",
      "preference.stockroom.component-workspace.sourcing-empty.v1",
    ],
    actions: ["component-browser.toggle-empty-sourcing-sections"],
    scroll: { owns: false },
    home: { regionId: WORKSPACE_REGION.sourcingBody, siblingGroup: GROUP.sourcingSections },
    source: SOURCING_SOURCE,
  },

  /* --------------------------------------------------------------- status bar */

  // WorkspaceStatusBar.tsx: what is happening to THIS component right now. Deliberately not the
  // application status bar at the bottom of the window, which is shell and is Phase 6.
  {
    id: "workspace.status-bar",
    devIds: ["component-browser.status-bar"],
    dataNeeds: [
      "dossier.specificationGroups",
      "dossier.keySpecifications",
      "dossier.qualitySummary.stateCounts.missing",
      "dossier.qualitySummary.stateCounts.conflicting",
      "dossier.distributorOffers",
      "runtime.workspace-activity",
    ],
    actions: [],
    preferredHeight: 22,
    scroll: { owns: false },
    home: { regionId: WORKSPACE_REGION.statusBand, siblingGroup: GROUP.statusBar },
    source: "components/component-workspace/WorkspaceStatusBar.tsx",
  },
];

const registered = registerPieces(WORKSPACE_PIECES);

/**
 * The workspace registry, built once from the manifests above.
 *
 * `duplicateIssues` is exported rather than thrown for the same reason validation reports rather
 * than refuses: a duplicate is a defect in this file, the coverage test names it, and a build that
 * exploded on import would take the whole application down over a layout catalogue entry.
 */
export const WORKSPACE_PIECE_REGISTRY: PieceRegistry = registered.registry;
export const WORKSPACE_PIECE_DUPLICATES = registered.issues;
