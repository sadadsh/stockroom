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
 *  2. KNOWN_PROP_PASSED — passed into a child as a plain string prop (e.g. AssetTile's
 *     `devId="detail.asset-hero"`, WorkbenchPanel's `devId="detail.pinout"`) which the
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
  // which are exactly components, projects, settings.
  "rail.nav-components",
  "rail.nav-projects",
  "rail.nav-settings",
  // primitives.tsx TabStrip: data-dev-id={`${devIdBase}.tabs`} + `${devIdBase}.tab-${t.id}`,
  // with DetailPanel passing devIdBase="detail" over tab ids specs/sourcing/pinout/enrich/history.
  "detail.tabs",
  "detail.tab-specs",
  "detail.tab-sourcing",
  "detail.tab-pinout",
  "detail.tab-enrich",
  "detail.tab-history",
  // ...and ProjectsPage passing devIdBase="projects" over overview/health/bom/setup/netclasses.
  "projects.tabs",
  "projects.tab-overview",
  "projects.tab-health",
  "projects.tab-bom",
  "projects.tab-setup",
  "projects.tab-netclasses",
]; // 15

// (2) Passed as a plain string prop and rendered by a child as data-dev-id={devId}. The
// id string is present in source (verified below), just not on a data-dev-id attribute.
const KNOWN_PROP_PASSED: readonly string[] = [
  // DetailPanel.tsx AssetTile: devId=/stageDevId= string props.
  "detail.asset-hero",
  "detail.asset-symbol",
  "detail.asset-footprint",
  "detail.asset-stage",
  // DetailPanel.tsx WorkbenchPanel: devId= string prop for the conditional workbench tabs.
  "detail.pinout",
  "detail.enrich",
  "detail.history",
]; // 7

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
    // TabStrip's generic derivation (drives both detail.* and projects.* tab ids).
    expect(sourceContains("${devIdBase}.tabs")).toBe(true);
    expect(sourceContains("${devIdBase}.tab-${t.id}")).toBe(true);
    // The two devIdBase call sites that produce the detail.* and projects.* tab ids.
    expect(sourceContains('devIdBase="detail"')).toBe(true);
    expect(sourceContains('devIdBase="projects"')).toBe(true);
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
