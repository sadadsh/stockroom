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
const EXPECTED_ENTRIES = 374;

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

  it("enumerates the 17 areas in first-appearance order, and every entry is a member", () => {
    expect(DEV_ID_AREAS).toEqual([
      "rail",
      "about",
      "components",
      "projects",
      "component-browser",
      "detail",
      "search",
      "addpart",
      "ingest",
      "stm",
      "settings",
      "altiumdb",
      "complete",
      "preview",
      "diff",
      "confirm",
      "shell",
    ]);
    expect(DEV_ID_AREAS).toHaveLength(17);

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
