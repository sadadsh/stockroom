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
 *     WorkbenchPanel's `devId="detail.enrich"`) which the
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
const DEV_ID_ATTR = /data-dev-id="([a-z][a-z0-9]*(?:[.-][a-z0-9]+)*)"/g;

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
  // primitives.tsx TabStrip: data-dev-id={`${devIdBase}.tabs`} + `${devIdBase}.tab-${t.id}`,
  // with DetailPanel passing devIdBase="detail" over its workbench tab ids.
  "detail.tabs",
  "detail.tab-specs",
  "detail.tab-sourcing",
  "detail.tab-enrich",
  "detail.tab-history",
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
]; // 22

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
  // DetailPanel.tsx WorkbenchPanel: devId= string prop for the conditional workbench tabs.
  "detail.enrich",
  "detail.history",
  "detail.handoff-tab",
  // Glb3DView.tsx LayerToggle: devId= string prop on the idle-spin chip.
  "detail.model-spin",
  // ProductPhoto.tsx PhotoTrigger: devId= string prop on the click-to-view photo chips.
  "detail.photo",
  "ingest.pulled-photo",
  "ingest.candidate-photo",
  // DetailPanel.tsx CollapsePaneButton / CollapsedPaneRail: devId= string prop on the controls that
  // close and reopen the Specifications and Sourcing panes. Each id is spelled out in full at its
  // call site, so it stays greppable even though the attribute itself is an expression.
  "detail.specs-collapse",
  "detail.specs-expand",
  "detail.sourcing-collapse",
  "detail.sourcing-expand",
]; // 16

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
    // TabStrip's generic derivation drives the detail.* tab ids.
    expect(sourceContains("${devIdBase}.tabs")).toBe(true);
    expect(sourceContains("${devIdBase}.tab-${t.id}")).toBe(true);
    // The detail and Projects call sites produce their workbench tab ids.
    expect(sourceContains('devIdBase="detail"')).toBe(true);
    expect(sourceContains('devIdBase="projects"')).toBe(true);
    // SegmentedControl produces the fixed STM lens and inspector option ids.
    expect(sourceContains("${devIdBase}.${opt.id}")).toBe(true);
    expect(sourceContains('devIdBase="stm.lens"')).toBe(true);
    expect(sourceContains('devIdBase="stm.inspector"')).toBe(true);
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

// --- Every docked panel header shares ONE band height. ------------------------------------------
// Owner, 2026-07-26: "the component title bar is MISALIGNED with the library Components line and
// the nav line". Measured on their real Windows window: the detail strip was h-[38px] while the
// other three headers were h-[34px], putting its ink centre 1.6px low on a band the three share.
// A source-level gate, because this cannot be a shared constant: a Tailwind arbitrary value built
// from a template literal produces a class with no CSS behind it, which would delete the height.

// The docked panel headers for the rail, list, and detail sheet. These three
// sit on ONE horizontal band across the window, so a difference between them reads as a
// mis-registration rather than as variety. Modal headers are a SEPARATE family (consistently 38px)
// and status bars a third (24px); scoping matters, because the first draft of this gate convicted
// all of them and would have "fixed" a consistency that was never broken.
const DOCKED_PANEL_HEADERS = [
  "/src/components/primitives.tsx",
  "/src/components/Rail.tsx",
  "/src/components/DetailPanel.tsx",
  "/src/pages/ProjectsPage.tsx",
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
