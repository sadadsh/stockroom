import { describe, expect, it } from "vitest";
import { DEV_IDS, DEV_ID_AREAS, DEV_ID_BY_ID } from "./devIds";

// The catalogue is the single source of truth for the dev-mode ID system, so these
// tests guard it against accidental drops, duplicate ids, area drift, and a stale
// by-id map — the four ways the hand-authored list could silently rot.
// Bump this when a dev id is deliberately added or removed. It is a drift alarm, not a target: a
// change here should always accompany a real catalogue change in the same commit.
// 237 as of Batch 4d (+rail.collapse, +shell.profile-switch, +shell.profile-menu).
// 241 as of Batch 5 (+detail.model-views and the three canonical-view buttons: iso/top/front).
// 242 with +detail.model-board, the Footprint toggle that puts the land pattern under the body.
// 249 with the layer + shading bar: model/PCB toggles and the realistic/studio/x-ray modes.
// Deliberate re-baseline, which is what this gate exists for.
// 234 as of Batch 3: +detail.spec-family (repeated spec keys collapsed into one row),
// +detail.alternates (the other sources for a value), +detail.trade (the procurement facts that
// used to be discarded). All three are new controls in this commit.
// 253 as of 2026-07-25: `detail.spec-group-toggle`, the spec sheet's disclosure header. Bumping
// this is what the gate is FOR - a deliberate re-baseline, never a silent drift.
// 264 as of 2026-07-26: the four pane collapse/expand controls (`detail.specs-collapse` /
// `-expand`, `detail.sourcing-collapse` / `-expand`) for the owner's closable Specifications and
// Sourcing panes. A deliberate re-baseline, which is what this gate is for.
// 263 as of 2026-07-26: -detail.sourcing-qty, the amount-needed input the owner removed ("the need
// box in the library should be removed"). The quantity-AWARE pricing it fed is untouched.
// 238 after the Projects surface and its 41 project-only ids were removed. The
// STM Viewer rail id replaces the former Projects rail id one-for-one.
// 245 with the compact 3D settings/popover, interactive view cube, the cross-EDA
// representation matrix, and the three
// explicitly addressable Symbol / Footprint / 3D inspection tabs.
// 245 after the standalone Pinout tab moved into the persistent specimen/CAD rail and its
// bounded pin-list scroller became directly inspectable.
// 262 with the STM Viewer workbench, compiled target map, legend, and inspector controls.
// 264 with both Add to Components paths addressable under the same dev-mode contract.
// 262 after the owner removed the KiCad-only Projects surface and automatic convergence
// removed the obsolete Install And Restart control.
// 258 after network-only ingest removed ZIP browsing, inspect progress, and the global
// file-drop overlay; none of those retired local-file controls remains addressable.
// 259 with the source-collection outcome ledger exposed to the dev-mode inspector.
// 256 after the unified inspection instrument replaced eight legacy asset-card ids with four
// direct instrument/stage/expand/status ids.
// 273 after restoring the shared Projects rail, shell, picker, workbenches, and native PCB stage.
// 275 with the About window's stale-frontend note, which appears only when the running bundle and
// the backend disagree about the installed revision.
// 279 with the completion worklist: the block itself, one row per provider route a run could not
// finish alone, and the control that opens that provider on that exact component.
// 280 with `settings.completion-worklist-start`, the row's new PRIMARY control. It starts the real
// person-driven capture for that component and provider, so what the person downloads is actually
// imported; the pre-existing `-open` id stays as the secondary "just look" link.
// 281 with `settings.completion-worklist-run`, the one control that works the whole worklist: it
// starts the first row and starts the next one each time a capture reaches a terminal state, and
// the same control stops the pass.
// 280 after the obsolete profile switch/menu pair became one noninteractive active-library label.
// 278 after the one Get Files workflow removed the provider picker and separate open-provider link.
// 280 with the active Settings content scroller and STM32CubeMX source disclosure directly
// addressable for first-run and scroll-position acceptance.
// 279 after the single-slot capture contract removed the obsolete superseded-capture notice.
// 273 after each asset opens only its own viewer and the four combined-preview tab controls were
// removed.
// 283 with the ten source-backed AdaptiveChoice controls spanning Category, intake, Projects, and STM.
// 338 with the opened-component workspace: the tab band, the persistent identity header, the
// three-module representation dock and its layout switcher, the four information tabs, the Overview
// regions, and the one workspace modal. A new `component-browser` area, because these elements
// belong to the OPENED component rather than to the picker that lists them. Per-component elements
// (`component-browser.component[<id>]` and friends) are DYNAMIC and deliberately have no rows here.
// 374 with the three exhaustive sheets the compact tabs hand off to (the full specification sheet
// with its search / sort / pin controls and the complete pinout table, the full sourcing sheet with
// per-source outcomes, price ladders and distributor-suggested relationships, and the four-tab
// sources ledger), plus the capabilities Slice 2 had left unreachable: Edit Identity, the category
// move, Apply Pinout, and the sourcing refresh. A deliberate re-baseline, which is what this
// gate is for.
// 373 after the provider-website sign-in panels were removed: Stockroom no longer signs in to a
// provider site, so `settings.vendor-logins` (the "Provider Sessions And Optional Sign-Ins"
// section) has nothing left to configure. The DigiKey catalogue API creds moved into
// `settings.distributor`, which keeps `settings.vendor-login-row` emitted.
// 385 with Complete Component: the header action that opens it, the sheet itself, the provider
// coverage matrix and its per-row Open Provider and per-artifact answer controls, the provider trip
// controls (show the page, return to Stockroom, import downloaded files), the download progress,
// the run report, and the retained verified sets. Per-PROVIDER rows are dynamic
// (`component-browser.component[<id>].provider[<provider id>]`) and carry no rows here, for the
// same reason the per-component ids do not. A deliberate re-baseline, which is what this gate is for.
// 345 after the superseded detail panel was deleted: the component workspace had already taken over
// every capability it carried, so its 40 ids stopped rendering (27 literals, 8 prop-passed, and the
// 5 workbench tab ids TabStrip derived from its `devIdBase="detail"`). The `detail` area SURVIVES
// with 21 rows whose emitters are live components: HandoffBand's EDA handoff block and category
// selector, Glb3DView + threeScene's 3D model instrument, and PinoutViewer's pin list.
// 346 after Slice 7's polish half. Removed: `detail.pinout` / `detail.pinout-list` with
// components/PinoutViewer.tsx (orphaned when DetailPanel was deleted; the workspace's PinoutTable
// already rendered strictly more of the same data), and `component-browser.identity-category`
// (the identity sheet's hand-written category select was a second editor for a field the generated
// EDA registry owns, so the sheet renders HandoffBand and the band's `detail.category-control` is
// the one control). Added: `component-browser.pinout-filter` (the one capability worth keeping
// from the deleted viewer), `component-browser.change-diff` (the visual diff, finally openable now
// that modals stack), and `diff.tab-symbol` / `diff.tab-footprint` (the diff's kind switcher is
// the shared TabStrip, which derives an id per tab). A deliberate re-baseline, which is what this
// gate is for.
// 347 with `component-browser.provider-row`: the SHARED role every provider coverage row declares.
// Each row already carried a per-provider instance id, which is what makes one row editable on its
// own; this row is what an edit meant for EVERY provider row is keyed on. Adding it is what keeps
// the instance / shared distinction addressable from both ends rather than only from the narrow one.
// 351 with the four SHARED roles the last interpolated ids became: detail.handoff-field,
// detail.handoff-open, stm.package and stm.family. Those elements had been building an id by
// interpolating a registry field key or a package name straight into the attribute, which no
// catalogue row covered and no selector could be safely derived from. Each is an instance id now
// (stm.package[LQFP100]), built through the same escape every other dynamic id uses, and the role
// it declares is the catalogue row here. A deliberate re-baseline, which is what this gate is for.
// 343 as of the component dossier overhaul: the opened component became three columns with a
// compact identity header, so the four information tabs, the representation dock, the
// per-component tab strip and the header's four competing buttons went (50 ids), and the columns,
// their regions, the splitters, the Manage menu, Copy MPN and the quality summary arrived (42).
// A deliberate re-baseline, which is what this gate is for.
// 387 as of wiring the dossier through: the specification row grew its inline provenance and the
// four write controls behind it (16 ids), the datasheet became a split button with a real viewer
// carrying page, zoom, rotation, outline and an in-place failure (26 ids), and the sourcing column
// gained the total-stock cell, the per-source failure notice, the preferred-datasheet reason and
// the related-part row with its evidence (8 ids). Three went: `related-group` and
// `relationship-group` grouped related parts by the catalogue key they arrived under, and a
// related part now states its own reason, so the ROW is the unit; `sourcing-shared` held the trade
// and compliance facts, which are canonical specifications with a category-assigned group like any
// other. Another deliberate re-baseline.
// 389 as of closing the projection contract: a reviewed decision now travels on the specification
// itself rather than being read back out of the value it produced, so the row states what an
// override REPLACED and whether a pinned source is actually in force (2 ids). Both are states the
// row could not previously show, and a pin that is silently ignored is worse than no pin.
// 399 as of finishing the Specifications column. The sticky anchor strip and its per-section
// jump (2), and the attached editor with the six controls a reviewed decision actually needs -
// unit, value type, source, verification status, reason, and whether the value outranks the
// sources - plus the refusal that says which category rule the entry broke (8). The editor was
// previously one unlabelled value box, so none of these were addressable. A deliberate
// re-baseline, which is what this gate is for.
// 401 with the Manage menu's shell bridge: one export format action and one installed EDA
// application (2). Both are per-row controls in the two dialogs behind Export Component... and
// Open In..., and both are addressable because the SET they belong to is decided by the machine -
// which formats this component has files for, and which applications are really installed - so a
// dev-mode inspection has to be able to name the row it is looking at.
// 416 with the Sourcing and Resources column in its six fixed sections. The lifecycle band gained
// the manufacturer's own status beside the library's lifecycle (1), the offers became a dense
// table with its own scroller (1), pricing and lead time became a section rather than three rows
// borrowed from lifecycle (1), and provenance stopped being one flat source list: Data Sources,
// Field Conflicts, Manual Overrides, Import and Enrichment History, Revision History and
// Technical Diagnostics are six addressable regions with a row id each (9), plus the translated
// compatibility warning and the control that names the fields it is about (3). Every one of them
// is a region a dev-mode inspection has to be able to point at, and the flat list had exactly two.
// 418 with the picker's corrected search band: the parametric search became its own control
// beside the now-real inline input (1), and the active filters say in words what they are hiding
// (1). Both were previously unaddressable because neither existed - the search box WAS the
// parametric trigger, and the filter state was a bare count badge.
// 439 with the CAD Assets column's real previews and its one column-level decision. The symbol
// and land pattern are now DRAWN from geometry rather than shown as pictures, so every layer a
// person can switch on is an addressable control: pin names, pin numbers and electrical type on
// the symbol (3), and copper, mask, paste, silkscreen, fabrication, courtyard, pad numbers,
// origin, dimensions and the ruler on the land pattern (10). Each is a real layer of the file,
// and one shared "layers" id would make ten different switches the same element to an override.
// The rest are states and controls that did not exist: the two drawing canvases (2), the asset
// issue line held apart from its evidence line (1), the maximize glyph that replaced a text
// button (1), the way back to all three modules (1), the confirmation that says what changing
// the preferred source replaces (1), and the two ways to choose a source in the comparison -
// the whole set and one asset (2). A deliberate re-baseline.
// 441 with the picker row's identifier and its package label (2). The row's MPN had been sharing
// line one with a `flex-none` package while a fixed-width attention block held 112px beside them
// both, so at a 290px picker the identifier rendered as one letter and an ellipsis. Neither box
// was addressable, which is why the measurement that would have caught it could not be taken.
// 447 as of collapsing the CAD column's visibility controls and the sourcing column's empty
// sections. The left column carried its layer switches as always-visible outlined pills - three
// under the symbol, ten under the land pattern - which measured fourteen bordered controls across
// six toolbar rows in a ~300px column. They are now rows in a panel behind ONE icon per preview, so
// the shell that opens it (2, one per preview), the panel itself (1) and the strip they sit on (1)
// are new addressable elements; the twelve switch ids are unchanged and still one per switch.
// The right column stopped rendering a full sentence per empty section, so the control that reveals
// them (1) and the one line that names the silent provenance questions (1) are new. Nothing was
// removed: `asset-measure` and `asset-maximize` moved file but kept their ids.
// A deliberate re-baseline, which is what this gate is for.
// 448 with `component-browser.spec-conflict-marker`. A specification row stopped printing three
// pieces of metadata around every value - a source tier, a state word and the word `Evidence` - and
// a conflict became a quiet marker instead of a sentence. The marker is a new addressable element;
// the word it replaced was not one.
// 466 with the eighteen `design` rows of Design Mode's arrange surface (plan 1.5, Phase 3B). Nine
// are the CANVAS - the per-placement drag handle, its two drop positions, and the piece settings
// menu with its name block, its collapse / hide pair, its two step controls and its region picker -
// drawn in a portal over the running application while arrange is on. Nine are the panel's Arrange
// section: the switch, the section, its edited/unedited state, the revert, the control that puts an
// off-screen piece back, and the four the named local drafts need. The `design` AREA is new, and it
// is an area rather than rows under `shell` because these belong to the editor OF the application
// rather than to a surface in it. A deliberate re-baseline, which is what this gate is for.
// 472 with the six `design` rows of Phase 3C. Two are the narrow style scope on the piece menu (the
// role being overridden, and what it becomes for that one placement); three are the Issues section
// in the panel - the section, its warning/note count, and the shared row - which is where a
// committed layout's known cost is read (plan 1.4); one is the live letter-rule warning on the copy
// editor (plan 1.5). The WIDE style scope earns no row: editing a role everywhere it appears is the
// Tokens rows and the Box tab, which stay outside the id system with the panel's other chrome.
// 474 with the onboarding and toast targets used by Design Studio's real-component scenarios.
// 482 with the Components list's loading, failed, and filtered-empty states exposed to the same
// stable target contract as the rest of the production picker.
// 495 with the Projects scenario states that distinguish loading, failures, native/runtime
// blockers, repository collaboration, shared review, and build completion in the real workbenches.
// 496 with the STM target-definition rules surface used by the real Bench scenario.
// 497 with the background guided-capture status exposed to global scenario coverage.
// 500 after Design Studio simplification removed four obsolete drawer/compare targets while
// keeping the component-scoped Manage Models tab, EDA selection, modal browser, navigation,
// and status. 501 exposes each opened component's inline offer price ladder for direct editing.
// Missing CAD art/status and the authored datasheet page cluster replace generated identities.
const EXPECTED_ENTRIES = 504;

describe("devIds catalogue", () => {
  // The count is asserted from a single constant so bumping it is one edit, and so the test NAME can
  // never drift out of step with the number it checks (it used to say 199 while asserting 219).
  it(`has exactly ${EXPECTED_ENTRIES} entries carrying only id/label/area`, () => {
    expect(DEV_IDS).toHaveLength(EXPECTED_ENTRIES);
    for (const entry of DEV_IDS) {
      expect(Object.keys(entry).sort()).toEqual(["area", "id", "label"]);
      expect(typeof entry.id).toBe("string");
      expect(typeof entry.label).toBe("string");
      expect(typeof entry.area).toBe("string");
      expect(entry.id.length).toBeGreaterThan(0);
      expect(entry.label.length).toBeGreaterThan(0);
    }
  });

  it("has unique ids whose first dot-segment equals the area", () => {
    const seen = new Set<string>();
    for (const entry of DEV_IDS) {
      expect(seen.has(entry.id)).toBe(false);
      seen.add(entry.id);
      expect(entry.id.split(".")[0]).toBe(entry.area);
    }
    expect(seen.size).toBe(EXPECTED_ENTRIES);
  });

  it("enumerates the 21 areas in first-appearance order, and every entry is a member", () => {
    expect(DEV_ID_AREAS).toEqual([
      "rail",
      "about",
      "onboarding",
      "toast",
      "capture",
      "components",
      "stm",
      "projects",
      "component-browser",
      "detail",
      "search",
      "addpart",
      "ingest",
      "settings",
      "altiumdb",
      "complete",
      "preview",
      "diff",
      "confirm",
      "shell",
      // Design Mode's arrange surface. Last, because it arrived last and this list is
      // first-appearance order rather than a taxonomy.
      "design",
    ]);
    expect(DEV_ID_AREAS).toHaveLength(21);

    // Every catalogued area is declared in DEV_ID_AREAS...
    const declared = new Set(DEV_ID_AREAS);
    for (const entry of DEV_IDS) {
      expect(declared.has(entry.area)).toBe(true);
    }
    // ...and DEV_ID_AREAS is exactly the areas in first-appearance order (no extras).
    const firstSeen: string[] = [];
    for (const entry of DEV_IDS) {
      if (!firstSeen.includes(entry.area)) firstSeen.push(entry.area);
    }
    expect(DEV_ID_AREAS).toEqual(firstSeen);
  });

  it("DEV_ID_BY_ID round-trips every entry", () => {
    expect(DEV_ID_BY_ID.size).toBe(EXPECTED_ENTRIES);
    for (const entry of DEV_IDS) {
      expect(DEV_ID_BY_ID.get(entry.id)).toBe(entry);
    }
  });
});
