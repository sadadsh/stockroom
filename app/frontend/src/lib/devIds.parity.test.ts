/**
 * Catalogue <-> code parity guard (IDSYS-02).
 *
 * `lib/devIds.ts` is the single source of truth for the dev-mode id system, and every
 * element in the app carries a matching `data-dev-id`. This test proves the two never
 * drift: no element emits an id the catalogue does not know, no catalogue id is left
 * unused, and no id is duplicated. It is a permanent guardrail — adding a `data-dev-id`
 * without a catalogue row (or vice versa) fails CI.
 *
 * It reads component source as raw strings via Vite's `import.meta.glob(..., '?raw')`,
 * which works in the vitest/jsdom environment. It deliberately does NOT use
 * node:fs / node:path / process.cwd — those break `tsc -b` and are environment-fragile.
 *
 * Two kinds of catalogue id never appear as a literal `data-dev-id="<id>"` attribute:
 *
 *  1. KNOWN_DERIVED — computed at render time by a reusable component from a prop, so the
 *     full id string is never written in source. Each is justified by an asserted
 *     derivation source below (Rail's `rail.nav-${route}`, TabStrip's `${base}.tabs` /
 *     `${base}.tab-${id}`).
 *  2. KNOWN_PROP_PASSED — passed into a child as a plain string prop (e.g.
 *     WorkspaceRegion's `devId="component-browser.key-specs"`) which the
 *     child then renders as `data-dev-id={devId}`. The id string DOES exist in source,
 *     just not on a `data-dev-id="..."` attribute. Each is verified present as a quoted
 *     literal below, so this list is checked, not rubber-stamped.
 *
 * Everything else must be a literal `data-dev-id="<id>"`. An unused catalogue id — one
 * that is neither a literal, nor derived, nor prop-passed — fails the completeness check.
 */
import { describe, it, expect } from "vitest";
import { DEV_IDS, DEV_ID_BY_ID } from "./devIds";

// --- App source, loaded as raw strings at test time (no filesystem access) -------------
// Keys are absolute-from-root paths ("/src/components/Rail.tsx"); values are file text.
const RAW = import.meta.glob("/src/**/*.{ts,tsx}", {
  query: "?raw",
  eager: true,
  import: "default",
}) as Record<string, string>;

// Scan only app-authored source: exclude test/spec files and the id source of truth
// itself (devIds.ts lists all 198 ids as `id: "..."`, which is not an emission).
const SOURCE: ReadonlyArray<readonly [string, string]> = Object.entries(RAW).filter(
  ([path]) => !/\.(test|spec)\.[jt]sx?$/.test(path) && !path.endsWith("/lib/devIds.ts"),
);

// Matches static literal attributes like data-dev-id="detail.spec-group". The [a-z] start
// deliberately ignores template usages (`data-dev-id={`...`}`, `data-dev-id="${id}"`) and
// the `data-dev-id="..."` doc example in element.overrides.ts.
//
// `data-dev-role` counts as an emission of the same catalogue id. It is the SHARED half of the id
// contract: an element that carries a per-instance `data-dev-id` declares the class it belongs to
// here, and that class is a catalogue row like any other (see lib/componentDevIds.ts).
const DEV_ID_ATTR = /data-dev-(?:id|role)="([a-z][a-z0-9]*(?:[.-][a-z0-9]+)*)"/g;

function scanEmittedLiteralIds(): Set<string> {
  const ids = new Set<string>();
  for (const [, text] of SOURCE) {
    for (const m of text.matchAll(DEV_ID_ATTR)) ids.add(m[1]);
  }
  return ids;
}

/** True if the exact quoted string "<id>" appears anywhere in scanned source. */
function quotedLiteralPresent(id: string): boolean {
  const needle = `"${id}"`;
  return SOURCE.some(([, text]) => text.includes(needle));
}

/** True if any scanned file's text contains `needle`. */
function sourceContains(needle: string): boolean {
  return SOURCE.some(([, text]) => text.includes(needle));
}

// -- Catalogue ids that are NOT emitted as a literal data-dev-id="<id>" -----------------

// (1) Computed by a reusable component from a prop; the full string is never in source.
const KNOWN_DERIVED: readonly string[] = [
  // Rail.tsx: <RailItem data-dev-id={`rail.nav-${item.route}`}> over lib/nav.ts routes,
  // which are exactly components, STM Viewer, and settings.
  "rail.nav-components",
  "rail.nav-projects",
  "rail.nav-stm",
  "rail.nav-settings",
  // primitives.tsx TabStrip: data-dev-id={`${devIdBase}.tabs`} + `${devIdBase}.tab-${t.id}`.
  // ProjectsPage passes the same TabStrip primitive its shared tool ids.
  "projects.tabs",
  "projects.tab-overview",
  "projects.tab-bom",
  "projects.tab-build",
  "projects.tab-activity",
  // primitives.tsx SegmentedControl derives one id per option. The STM target
  // definition uses fixed lens and inspector registries at the two call sites.
  "stm.lens.compatibility",
  "stm.lens.foundation",
  "stm.lens.electrical",
  "stm.lens.access",
  "stm.lens.board",
  "stm.inspector.decision",
  "stm.inspector.targets",
  "stm.inspector.evidence",
  // ComponentsPage passes the same TabStrip primitive the open-component strip. Only the TABLIST
  // id is static: each tab is one OPEN COMPONENT, so its id is built by lib/componentDevIds.ts and
  // is not catalogued at all.
  "component-browser.tabs",
  // InfoTabsShell: the four information tabs, whose ids ARE fixed.
  "component-browser.info.tabs",
  "component-browser.info.tab-overview",
  "component-browser.info.tab-specifications",
  "component-browser.info.tab-sourcing",
  "component-browser.info.tab-sources",
  // RepresentationDock's SegmentedControl derives one id per layout option.
  "component-browser.layout.all",
  "component-browser.layout.symbol",
  "component-browser.layout.footprint",
  "component-browser.layout.model",
  // SourcesSheet passes the same TabStrip primitive the four questions the source ledger answers.
  "component-browser.sources.tabs",
  "component-browser.sources.tab-fields",
  "component-browser.sources.tab-records",
  "component-browser.sources.tab-changes",
  "component-browser.sources.tab-diagnostics",
  // DiffModal's kind switcher is the same TabStrip primitive now, rather than a fourth
  // hand-rolled row of pills that had no roving tabindex and no arrow keys.
  "diff.tabs",
  "diff.tab-symbol",
  "diff.tab-footprint",
]; // 35

// (2) Passed as a plain string prop and rendered by a child as data-dev-id={devId}. The
// id string is present in source (verified below), just not on a data-dev-id attribute.
const KNOWN_PROP_PASSED: readonly string[] = [
  // ProductPhoto.tsx CarouselArrow: the pager buttons take devId as a prop. Spelled out in full
  // at the call site, never built as `preview.photo-${side}` - an interpolated id is invisible to
  // this gate and to grep.
  "preview.photo-prev",
  "preview.photo-next",
  // Glb3DView.tsx LayerToggle: the layer + shading buttons take devId as a prop and render
  // data-dev-id={devId}; each id is spelled out in full at the call site or in the SHADING table.
  "detail.model-board",
  "detail.model-show-model",
  "detail.model-show-board",
  "detail.model-shade-realistic",
  "detail.model-shade-studio",
  "detail.model-shade-xray",
  // Glb3DView.tsx ViewControls: the canonical-view buttons render data-dev-id={v.devId} from a
  // VIEWS table that spells each id out in full, so the string is greppable even though the
  // attribute is an expression.
  "detail.model-view-iso",
  "detail.model-view-top",
  "detail.model-view-front",
  // PreviewModal maps a typed tab table to data-dev-id={t.devId}; the exact strings
  // remain at the table declaration so the addressable inspection modes cannot drift.
  // three-viewport-gizmo creates its own DOM node, so threeScene attaches this id after
  // construction with setAttribute instead of emitting it through JSX.
  "detail.model-gizmo",
  // Glb3DView.tsx LayerToggle: devId= string prop on the idle-spin chip.
  "detail.model-spin",
  // ProductPhoto.tsx PhotoTrigger: devId= string prop on the click-to-view photo chips.
  "ingest.pulled-photo",
  "ingest.candidate-photo",
  // HandoffBand.tsx: the filing control arrives as an AdaptiveChoice devId prop.
  "detail.category-control",
  // AdaptiveChoice renders these source-spelled ids through its devId prop. The semantic
  // value/options contract stays in the caller while the primitive swaps presentation presets.
  "ingest.footprint-control",
  "ingest.kind-control",
  "ingest.package-control",
  "projects.board-control",
  "projects.bom-filter-control",
  "projects.bom-line-control",
  "projects.build-placement-control",
  "projects.document-control",
  "stm.target-set-control",
  // component-workspace/WorkspaceRegion.tsx: every bounded information region is the same shell,
  // so each region's id (and its View All control's id) arrives as a `devId` / `viewAllDevId`
  // string prop. Spelled out in full at each call site, never interpolated.
  "component-browser.key-specs",
  "component-browser.attention",
  "component-browser.sourcing-snapshot",
  "component-browser.sourcing-snapshot-all",
  "component-browser.view-all",
  "component-browser.specifications",
  "component-browser.specifications-all",
  "component-browser.pinout",
  "component-browser.spec-conflicts",
  "component-browser.sourcing",
  "component-browser.sourcing-all",
  "component-browser.relationships",
  "component-browser.resources",
  "component-browser.sources",
  "component-browser.sources-all",
  "component-browser.field-sources",
  "component-browser.diagnostics",
  // component-workspace/SheetParts.tsx: the exhaustive sheets share one section and one table
  // shell, so a section's or a table's id arrives as a `devId` string prop. Spelled out in full at
  // each call site for the same reason as the regions above.
  "component-browser.spec-group",
  "component-browser.pinout-table",
  "component-browser.offer-ladder",
  // component-workspace/CompleteComponentSheet.tsx: the four bands of the provider trip share one
  // band shell, so each band's id arrives as a `devId` string prop. Spelled out in full at each
  // call site, never interpolated. The Providers band deliberately passes NONE: its addressable
  // element is the matrix inside it, which emits `component-browser.provider-matrix` itself.
  "component-browser.provider-browser",
  "component-browser.provider-progress",
  "component-browser.provider-report",
  "component-browser.provider-sets",
  // components/modalParts.tsx ModalShell: the scrim, the 38px header and the close control are ONE
  // frame now, so each window names its own parts through `devId` / `headerDevId` / `closeDevId`
  // string props. Spelled out in full at each call site. Four windows had hand-written the same
  // frame four slightly different ways, which is also how two of them ended up sharing a z-index.
  "component-browser.modal",
  "component-browser.modal-close",
  "diff.root",
  "diff.header",
  "preview.root",
  "preview.header",
  "preview.close",
  // components/modalParts.tsx ModalActions: the confirm dialog's action row is the shared bar.
  "confirm.actions",
  // components/productState.tsx AttentionItem: one attention row is one object, so the row's id and
  // its action's id arrive as `devId` / `actionDevId` string props.
  "component-browser.attention-item",
  "component-browser.attention-action",
  // The stage windows' body IS the stage, so the body takes the window's stage id rather than a
  // second absolutely-positioned div inside it.
  "preview.stage",
  "diff.stage",
  // lib/componentDevIds.ts CANDIDATE_ROLE: the staged candidate card carries a per-candidate
  // `data-dev-id` and declares this as its SHARED role. The role name is a named export rather than
  // a literal at the call site because `candidateDevId()` builds the instance id from the same
  // constant - two spellings of one id is exactly how the two halves would drift apart.
  "ingest.candidate",
]; // 62

describe("devIds catalogue <-> code parity (IDSYS-02)", () => {
  const catalogueIds = new Set(DEV_IDS.map((e) => e.id));
  const emitted = scanEmittedLiteralIds();

  it("scans a non-trivial amount of source (glob is wired)", () => {
    // Guard against a silently-empty glob turning every assertion into a false pass.
    expect(SOURCE.length).toBeGreaterThan(10);
    expect(emitted.size).toBeGreaterThan(100);
  });

  it("has no duplicate ids in DEV_IDS", () => {
    const seen = new Set<string>();
    const dupes: string[] = [];
    for (const e of DEV_IDS) {
      if (seen.has(e.id)) dupes.push(e.id);
      seen.add(e.id);
    }
    expect(dupes).toEqual([]);
    // DEV_ID_BY_ID must round-trip 1:1 with DEV_IDS (a dropped/duplicate id would diverge).
    expect(DEV_ID_BY_ID.size).toBe(DEV_IDS.length);
  });

  it("every emitted data-dev-id literal resolves to a catalogue entry (no unknown id)", () => {
    const unknown = [...emitted].filter((id) => !DEV_ID_BY_ID.has(id)).sort();
    expect(unknown).toEqual([]);
  });

  it("the derivation sources for KNOWN_DERIVED ids are present", () => {
    // Rail's per-route nav id derivation.
    expect(sourceContains("data-dev-id={`rail.nav-${item.route}`}")).toBe(true);
    // TabStrip's generic derivation drives every catalogued tab id.
    expect(sourceContains("${devIdBase}.tabs")).toBe(true);
    expect(sourceContains("${devIdBase}.tab-${t.id}")).toBe(true);
    // The Projects call site produces its workbench tab ids.
    expect(sourceContains('devIdBase="projects"')).toBe(true);
    // SegmentedControl produces the fixed STM lens and inspector option ids.
    expect(sourceContains("${devIdBase}.${opt.id}")).toBe(true);
    expect(sourceContains('devIdBase="stm.lens"')).toBe(true);
    expect(sourceContains('devIdBase="stm.inspector"')).toBe(true);
    // The opened component: the open-component tablist, the four information tabs, and the
    // representation layout switcher.
    expect(sourceContains('devIdBase="component-browser"')).toBe(true);
    expect(sourceContains('devIdBase="component-browser.info"')).toBe(true);
    expect(sourceContains('devIdBase="component-browser.layout"')).toBe(true);
    // The source ledger's own four tabs, inside the workspace modal.
    expect(sourceContains('devIdBase="component-browser.sources"')).toBe(true);
    // The visual diff's symbol/footprint switcher.
    expect(sourceContains('devIdBase="diff"')).toBe(true);
  });

  it("per-component tab ids are built by the dynamic helper, never spelled into the strip", () => {
    // The open-component strip overrides only the PER-TAB id; the tablist keeps the derived one.
    // If this override were dropped, the ids would silently revert to `component-browser.tab-<raw
    // component id>` - an uncatalogued, unescaped id interpolated straight from a record field.
    expect(sourceContains("devIdForTab={componentTabDevId}")).toBe(true);
    expect(sourceContains("${devIdBase}.tab-${t.id}")).toBe(true);
  });

  it("every KNOWN_DERIVED id is a catalogue id and is genuinely derived (never a literal)", () => {
    const notInCatalogue = KNOWN_DERIVED.filter((id) => !catalogueIds.has(id)).sort();
    expect(notInCatalogue).toEqual([]);
    // A derived id must NOT also be emitted as a literal — otherwise the allowlist is
    // masking a real placement (or is redundant). Keeps the allowlist honest.
    const alsoLiteral = KNOWN_DERIVED.filter((id) => emitted.has(id)).sort();
    expect(alsoLiteral).toEqual([]);
  });

  it("every KNOWN_PROP_PASSED id is a catalogue id and present as a quoted string in source", () => {
    const notInCatalogue = KNOWN_PROP_PASSED.filter((id) => !catalogueIds.has(id)).sort();
    expect(notInCatalogue).toEqual([]);
    // Verify (don't rubber-stamp): the id string must actually appear in source, and not
    // as a data-dev-id literal (those would be covered by the emitted scan instead).
    const missingFromSource = KNOWN_PROP_PASSED.filter((id) => !quotedLiteralPresent(id)).sort();
    expect(missingFromSource).toEqual([]);
    const alsoLiteral = KNOWN_PROP_PASSED.filter((id) => emitted.has(id)).sort();
    expect(alsoLiteral).toEqual([]);
  });

  it("every catalogue id is accounted for: literal ∪ derived ∪ prop-passed == catalogue (no unused id)", () => {
    const accounted = new Set<string>([...emitted, ...KNOWN_DERIVED, ...KNOWN_PROP_PASSED]);

    // No catalogue id is orphaned (present in catalogue but neither placed nor derived).
    const unused = [...catalogueIds].filter((id) => !accounted.has(id)).sort();
    expect(unused).toEqual([]);

    // No accounted id falls outside the catalogue (stale allowlist entry or stray literal).
    const extra = [...accounted].filter((id) => !catalogueIds.has(id)).sort();
    expect(extra).toEqual([]);

    // Exact partition sanity: the three disjoint buckets cover the whole catalogue.
    expect(accounted.size).toBe(catalogueIds.size);
    expect(emitted.size + KNOWN_DERIVED.length + KNOWN_PROP_PASSED.length).toBe(catalogueIds.size);
  });
});

// --- dynamic ids are BUILT, never interpolated ---------------------------------------------------
// A `data-dev-id` assembled from a template literal at a call site is the failure this whole file
// exists to prevent, and it is the one the literal scan above cannot see: the id never appears in
// source, no catalogue row covers it, and the value it embeds arrives from a record - a package name
// with a bracket in it, a field key with a space. Every dynamic id goes through
// `lib/componentDevIds.ts`, which bounds and escapes the value first.

// A direct template on the attribute: data-dev-id={`...`}
const INTERPOLATED_ATTR = /data-dev-id=\{`([^`]*)`\}/g;

// The one exception, and why. `item.route` comes from `lib/nav.ts`, a closed union of four routes,
// and all four resulting ids ARE catalogue rows (see KNOWN_DERIVED). No record value reaches it.
const ALLOWED_INTERPOLATIONS: readonly string[] = ["rail.nav-${item.route}"];

describe("dynamic dev ids are built, not interpolated", () => {
  it("no data-dev-id is assembled from a template literal at a call site", () => {
    const offenders: string[] = [];
    for (const [path, text] of SOURCE) {
      INTERPOLATED_ATTR.lastIndex = 0;
      for (let m = INTERPOLATED_ATTR.exec(text); m; m = INTERPOLATED_ATTR.exec(text)) {
        if (ALLOWED_INTERPOLATIONS.includes(m[1])) continue;
        offenders.push(`${path}: ${m[1]}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("the instance-id builders are the only source of a bracketed id", () => {
    // Every bracketed id in source is produced by one of these, so the escape and the length bound
    // are not optional at any call site.
    expect(sourceContains("export function instanceDevId(")).toBe(true);
    expect(sourceContains("`${role}[${devIdSegment(value)}]`")).toBe(true);
    expect(sourceContains("`${COMPONENT_BROWSER_AREA}.component[${devIdSegment(id)}]`")).toBe(true);
  });
});

// --- one static id, one control -----------------------------------------------------------------
// A catalogue id names one control (or one role played by a repeated row). The way that quietly
// breaks is a copy-paste: a new component takes an existing `data-dev-id` because the markup looked
// similar, and from then on an override written for one surface silently retunes another. A shared
// id emitted from TWO DIFFERENT FILES is the shape that mistake takes, so it has to be declared.

// Ids that legitimately appear in more than one file, each with the reason it is not a collision.
const KNOWN_SHARED_ACROSS_FILES: Readonly<Record<string, string>> = {
  // Not a second emission: AddPartModal names the hero input in a querySelector to land the caret
  // in it when the window opens. The one emission is IngestPage's.
  "ingest.input": "AddPartModal selects it to focus; IngestPage emits it",
  // The same role in two presentations: one source record's outcome, rendered compactly in the
  // information panel and in full in the sourcing sheet. Retuning the row is meant to reach both.
  "component-browser.source-state": "one source-record row, compact panel and full sheet",
};

describe("no unrelated controls share one static dev id", () => {
  it("every emitted static id belongs to a single file, unless it is a declared shared role", () => {
    const files = new Map<string, Set<string>>();
    for (const [path, text] of SOURCE) {
      DEV_ID_ATTR.lastIndex = 0;
      for (const m of text.matchAll(DEV_ID_ATTR)) {
        if (!files.has(m[1])) files.set(m[1], new Set());
        files.get(m[1])!.add(path);
      }
    }
    const offenders = [...files]
      .filter(([id, paths]) => paths.size > 1 && !(id in KNOWN_SHARED_ACROSS_FILES))
      .map(([id, paths]) => `${id}: ${[...paths].sort().join(", ")}`)
      .sort();
    expect(offenders).toEqual([]);
  });

  it("every declared shared role is really emitted from more than one file", () => {
    // Keeps the allowlist honest: a stale entry (the duplication was since removed) fails here
    // rather than sitting forever as permission nobody needs.
    const stale = Object.keys(KNOWN_SHARED_ACROSS_FILES).filter((id) => {
      const paths = SOURCE.filter(([, text]) => text.includes(`"${id}"`));
      return paths.length < 2;
    });
    expect(stale).toEqual([]);
  });
});

// --- Every docked panel header shares ONE band height. ------------------------------------------
// Owner, 2026-07-26: "the component title bar is MISALIGNED with the library Components line and
// the nav line". Measured on their real Windows window: the detail strip was h-[38px] while the
// other three headers were h-[34px], putting its ink centre 1.6px low on a band the three share.
// A source-level gate, because this cannot be a shared constant: a Tailwind arbitrary value built
// from a template literal produces a class with no CSS behind it, which would delete the height.

// The docked panel headers for the rail, the list, and the opened component. These
// sit on ONE horizontal band across the window, so a difference between them reads as a
// mis-registration rather than as variety. Modal headers are a SEPARATE family (consistently 38px)
// and status bars a third (24px); scoping matters, because the first draft of this gate convicted
// all of them and would have "fixed" a consistency that was never broken.
const DOCKED_PANEL_HEADERS = [
  // The strip itself lives here now, as `RouteHeader`. `primitives.tsx` re-exports it and no
  // longer declares a `bg-band` height of its own, so this gate follows the decision rather than
  // scanning a file that can no longer offend. The 38px MODAL header family lives in
  // `modalParts.tsx`, which is deliberately NOT in this list.
  "/src/components/productState.tsx",
  "/src/components/Rail.tsx",
  "/src/pages/ProjectsPage.tsx",
  // The open-component tab band replaced the detail sheet's title strip on the Components route,
  // so it inherits the same obligation: it sits on the SAME horizontal line as the rail header and
  // the Components list header, and a 4px difference reads as a mis-registration.
  "/src/pages/ComponentsPage.tsx",
];

describe("panel header band height", () => {
  it("is h-[34px] in every docked panel header", () => {
    // Measured on the owner's real Windows window, 2026-07-26: the detail strip was h-[38px] while
    // the other three were h-[34px], putting its ink centre at 17.8 against 16.2 for "Components"
    // and the rail toggle. Uses the RAW glob this file already established, NOT node:fs - the
    // header comment says why, and my first draft ignored it and used node:fs anyway.
    const offenders: string[] = [];
    for (const [path, src] of SOURCE) {
      if (!DOCKED_PANEL_HEADERS.includes(path)) continue;
      for (const line of src.split("\n")) {
        if (line.includes("bg-band") && /h-\[\d+px\]/.test(line)) {
          const h = /h-\[(\d+)px\]/.exec(line)![1];
          if (h !== "34") offenders.push(`${path}: h-[${h}px]`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});

// --- The machine-data face matches Altium. -------------------------------------------------------
describe("monospace stack", () => {
  it("leads with Consolas, and still bundles a fallback that travels", () => {
    // Owner, 2026-07-26, superseding their own Geist Mono pick: "the monospace font does not match
    // Altium". Consolas ships with Windows, where Altium runs. A peer without it must still get a
    // real mono, offline - the host serves from an ephemeral local port, so a CDN font is not an
    // option and the bundled face has to stay in the stack.
    //
    // Read as RAW SOURCE, not imported: `tailwind.config.js` has no type declaration, and importing
    // it breaks `tsc -b` (which is exactly what my first draft did).
    const raw = import.meta.glob("/tailwind.config.js", {
      query: "?raw",
      eager: true,
      import: "default",
    }) as Record<string, string>;
    const cfg = Object.values(raw)[0];
    expect(cfg).toBeTruthy();
    const block = /mono:\s*\[([\s\S]*?)\]/.exec(cfg)![1];
    // Strip comment lines FIRST. The block carries a long rationale comment containing quoted
    // owner words, and matching quotes across it made faces[0] the sentence "the monospace font
    // does not match Altium" rather than a font name - a gate reading its own documentation.
    const mono = block
      .split("\n")
      .filter((l) => !l.trim().startsWith("//"))
      .join("\n");
    // Split on commas and strip quote characters. A quote-pair regex kept matching the SEPARATORS
    // between entries (the closing quote of one and the opening quote of the next), which is how
    // the last "face" came out as ",\n          ".
    const faces = mono
      .split(",")
      .map((s) => s.replace(/["'`]/g, "").trim())
      .filter(Boolean);
    expect(faces[0]).toBe("Consolas");
    expect(faces.some((f) => f.includes("Geist Mono"))).toBe(true);
    expect(faces[faces.length - 1]).toBe("monospace");
  });
});
