/**
 * THE COVERAGE GATE (plan 1.2): a section that is on the screen is a section somebody can place.
 *
 * The registry is only worth having if it is COMPLETE. A new section shipped without a manifest
 * would render perfectly, look finished, and be invisible to the builder - the owner would drag
 * everything around it and never be able to move it, with nothing anywhere saying why. So this walks
 * the workspace as it actually renders and fails if any section on screen is not accounted for by
 * the layout system, and it walks the other way too: every manifest has to be something that
 * actually appears.
 *
 * WHAT COUNTS AS A SECTION, defined structurally rather than by asking the renderer. A sectioning
 * or landmark element - `section`, `header`, `footer`, `nav`, `aside`, `article` - that carries a
 * dev identity. That definition is deliberately independent of the layout system: it is read off the
 * HTML, so a rogue section added by a component that knows nothing about pieces is caught, which a
 * definition like "everything the renderer placed" would not be. Its identity is its `data-dev-role`
 * where it has one and its `data-dev-id` otherwise, which is the same instance-versus-class rule
 * `lib/componentDevIds.ts` states: the three CAD modules carry a per-component instance id and
 * declare `component-browser.cad-asset` as the class they belong to, and the class is what a
 * manifest can name.
 *
 * WHAT ACCOUNTS FOR ONE. Either a registered piece claims that dev id in its manifest, or the layout
 * document declares it as a REGION's dev id. Both are layout-system entities; anything else is a
 * section nobody can place.
 *
 * ---------------------------------------------------------------------------------------------
 * NON-VACUITY, PROVEN BY MUTATION rather than asserted.
 *
 * Two mutations were run against this file and each one turned it red; both were reverted.
 *
 *   1. REGISTRATION REMOVED. Deleting the `workspace.sourcing-documents` manifest from
 *      `WORKSPACE_PIECES` fails "every section on screen is placeable" with
 *      `component-browser.documents` unaccounted for, and fails "every registered piece appears"
 *      is unaffected - which is the right pair of outcomes and is why both directions are here.
 *   2. ROGUE SECTION RENDERED. Adding `<section data-dev-id="component-browser.message" />` inside
 *      `SourcingBodyChrome` - a real catalogue id, so the dev-id gates stay green - fails the same
 *      assertion. This is the case the gate exists for: a section that is legitimate everywhere
 *      else in the codebase and unplaceable here.
 *
 * THE TWO KNOWN VACUOUS SHAPES, and why neither applies:
 *
 *   AN EFFECT SETTLING AFTER THE READ. A gate that scanned an empty DOM would pass by finding
 *   nothing wrong. `settle()` waits for the tree to stop changing, and then the floor assertions
 *   below require a named minimum to be present - the three columns, the status bar, a specification
 *   group and a CAD module. A premature read fails those rather than passing the scan.
 *
 *   A SOURCE GATE MATCHING ITS OWN COMMENT. Nothing here reads source text. Both directions are
 *   measured against a rendered DOM, and the expected sets are computed from the registry and the
 *   document rather than written out by hand.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import type { ReactNode } from "react";
import { ApiError, api } from "../api/client";
import { cadVariantApi } from "../api/cadVariantClient";
import type { ComponentDossier } from "../api/dossierTypes";
import { ComponentWorkspace } from "../components/component-workspace/ComponentWorkspace";
import {
  FIXTURE_COMPONENT_ID,
  FIXTURE_NOW,
  populatedDossier,
  sparseDossier,
} from "../components/component-workspace/workspaceDomFixtures";
import { ThemeProvider } from "../lib/theme";
import { ToastProvider } from "../lib/toast";
import {
  defaultUiSession,
  openComponentInSession,
  resetUiSessionForTests,
} from "../lib/uiSession";
import { DEFAULT_WORKSPACE_LAYOUT } from "./defaultWorkspaceLayout";
import { layoutRegions } from "./document";
import { WORKSPACE_PIECES } from "./workspacePieces";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      partDossier: vi.fn(),
      partHistory: vi.fn(),
      partDiff: vi.fn(),
      partDetail: vi.fn(),
      facets: vi.fn(),
      editField: vi.fn(),
      moveCategory: vi.fn(),
      setSpecs: vi.fn(),
      previewSvg: vi.fn(),
      modelGlb: vi.fn(),
      landPattern: vi.fn(),
      deletePart: vi.fn(),
      refreshSourcing: vi.fn(),
      setSpecificationOverride: vi.fn(),
      clearSpecificationOverride: vi.fn(),
      setSpecificationPreferredSource: vi.fn(),
      clearSpecificationPreferredSource: vi.fn(),
      documentFile: vi.fn(),
    },
  };
});

vi.mock("../api/cadVariantClient", async (importActual) => {
  const actual = await importActual<typeof import("../api/cadVariantClient")>();
  return {
    ...actual,
    cadVariantApi: { inventory: vi.fn(), activatePair: vi.fn() },
  };
});

vi.mock("../lib/threeScene", () => ({
  mountModelScene: vi.fn(() => ({
    dispose: vi.fn(),
    fit: vi.fn(),
    setView: vi.fn(),
    setSpin: vi.fn((wanted: boolean) => wanted),
    setLandPattern: vi.fn(),
    setRenderMode: vi.fn(),
    setLayers: vi.fn(),
    setPlacementMode: vi.fn(),
    modelInfo: vi.fn(() => null),
  })),
}));

// Developer mode is on for the populated render because it draws the MOST: Technical Diagnostics
// only exists there, and a coverage gate should walk the fullest workspace the app can produce.
let developerMode = false;

vi.mock("../lib/devMode", async (importActual) => {
  const actual = await importActual<typeof import("../lib/devMode")>();
  return {
    ...actual,
    useDevMode: () => ({ ...actual.useDevMode(), enabled: developerMode }),
  };
});

const mockApi = vi.mocked(api);
const mockCadVariantApi = vi.mocked(cadVariantApi);

beforeEach(() => {
  developerMode = false;
  window.localStorage.clear();
  vi.useFakeTimers({ shouldAdvanceTime: true, now: FIXTURE_NOW });
  mockApi.previewSvg.mockResolvedValue(new Blob(["<svg/>"], { type: "image/svg+xml" }));
  mockApi.modelGlb.mockResolvedValue(new Uint8Array([0x67, 0x6c, 0x54, 0x46]).buffer);
  mockApi.landPattern.mockRejectedValue(new ApiError(404, "no footprint"));
  mockCadVariantApi.inventory.mockResolvedValue({
    partId: FIXTURE_COMPONENT_ID,
    inventories: [],
    pairs: [],
    supplementary: [],
  });
  mockApi.partHistory.mockResolvedValue({ commits: [], count: 0 });
  mockApi.facets.mockResolvedValue({
    by_category: { ICs: 1 },
    by_manufacturer: {},
    complete: 1,
    incomplete: 0,
    category_catalog: ["ICs", "Passives"],
  });
});

afterEach(() => {
  vi.useRealTimers();
});

const SECTION_TAGS = "section, header, footer, nav, aside, article";

/** Every dev id a registered manifest claims. */
const REGISTERED_DEV_IDS = new Set(WORKSPACE_PIECES.flatMap((manifest) => manifest.devIds));

/** Every dev id the document says a region renders. */
const REGION_DEV_IDS = new Set(
  layoutRegions(DEFAULT_WORKSPACE_LAYOUT)
    .map((visit) => visit.node.devId)
    .filter((id): id is string => typeof id === "string"),
);

function provide(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>{ui}</ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

/** Wait until the tree stops changing, so the scan reads a finished workspace. */
async function settle(container: HTMLElement): Promise<void> {
  let previous = "";
  let stable = 0;
  for (let pass = 0; pass < 80; pass += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    const current = container.innerHTML;
    stable = current === previous ? stable + 1 : 0;
    previous = current;
    if (stable >= 2) return;
  }
  throw new Error("the workspace never stopped re-rendering");
}

async function openWorkspace(dossier: ComponentDossier): Promise<HTMLElement> {
  resetUiSessionForTests(openComponentInSession(defaultUiSession(), FIXTURE_COMPONENT_ID));
  mockApi.partDossier.mockResolvedValue(dossier);
  const view = provide(<ComponentWorkspace componentId={FIXTURE_COMPONENT_ID} />);
  await settle(view.container);
  return view.container;
}

/** The identity of every section on screen: the class it belongs to, or the id it carries. */
function sectionIdentities(container: HTMLElement): string[] {
  const ids = new Set<string>();
  for (const element of container.querySelectorAll<HTMLElement>(SECTION_TAGS)) {
    const identity =
      element.getAttribute("data-dev-role") ?? element.getAttribute("data-dev-id");
    if (identity) ids.add(identity);
  }
  return [...ids].sort();
}

function unaccountedFor(identities: readonly string[]): string[] {
  return identities.filter((id) => !REGISTERED_DEV_IDS.has(id) && !REGION_DEV_IDS.has(id));
}

describe("every section the workspace renders is placeable", () => {
  it("accounts for every section of a fully populated component in developer mode", async () => {
    developerMode = true;
    const container = await openWorkspace(populatedDossier());
    const identities = sectionIdentities(container);

    // THE FLOOR, so an unsettled or empty render cannot pass by finding nothing wrong. These are
    // the sections the fullest workspace must have drawn before the scan below means anything.
    expect(identities).toEqual(
      expect.arrayContaining([
        "component-browser.header",
        "component-browser.column-cad",
        "component-browser.column-specifications",
        "component-browser.column-sourcing",
        "component-browser.cad-asset",
        "component-browser.key-specs",
        "component-browser.spec-group",
        "component-browser.lifecycle",
        "component-browser.offers",
        "component-browser.provenance",
        "component-browser.status-bar",
      ]),
    );
    expect(identities.length).toBeGreaterThanOrEqual(20);

    expect(unaccountedFor(identities)).toEqual([]);
  });

  it("accounts for every section of a component nobody has sourced", async () => {
    const container = await openWorkspace(sparseDossier());
    const identities = sectionIdentities(container);
    // The sparse workspace draws FEWER sections, not different ones - the floor is the three
    // columns and the bar, and the five collapsible sourcing sections are absent by design.
    expect(identities).toEqual(
      expect.arrayContaining([
        "component-browser.header",
        "component-browser.column-cad",
        "component-browser.column-specifications",
        "component-browser.column-sourcing",
        "component-browser.lifecycle",
        "component-browser.status-bar",
      ]),
    );
    expect(unaccountedFor(identities)).toEqual([]);
  });
});

describe("every registered piece and region is something that appears", () => {
  it("renders at least one dev id of every manifest that names one", async () => {
    // The other direction, and the reason two renders are needed: the five collapsible sourcing
    // sections only exist on a component that HAS sourcing, and the reveal control only exists on
    // one that does not. Neither workspace alone can show every piece; between them they must.
    developerMode = true;
    const populated = sectionIdentitiesAndEverything(await openWorkspace(populatedDossier()));
    // Blank-section recovery is intentionally developer-only; keep that mode for the sparse pass.
    const sparse = sectionIdentitiesAndEverything(await openWorkspace(sparseDossier()));
    const seen = new Set([...populated, ...sparse]);

    const missing = WORKSPACE_PIECES.filter(
      (manifest) => manifest.devIds.length > 0 && !manifest.devIds.some((id) => seen.has(id)),
    ).map((manifest) => manifest.id);
    expect(missing).toEqual([]);
  });

  it("renders every region dev id the document declares", async () => {
    developerMode = true;
    const seen = sectionIdentitiesAndEverything(await openWorkspace(populatedDossier()));
    const missing = [...REGION_DEV_IDS].filter((id) => !seen.has(id));
    expect(missing).toEqual([]);
  });
});

/**
 * Every dev identity anywhere in the tree, not just the sectioning elements.
 *
 * The two directions ask different questions, so they scan different things. "Is this section
 * placeable" is about sections, because a `<span>` with a dev id is a detail inside a piece rather
 * than something anyone would move. "Does this piece appear" is about the whole tree, because a
 * manifest legitimately names the ids of controls INSIDE its section - `component-browser
 * .compare-sources` is a button, not a section.
 */
function sectionIdentitiesAndEverything(container: HTMLElement): Set<string> {
  const ids = new Set<string>();
  for (const element of container.querySelectorAll<HTMLElement>("[data-dev-id], [data-dev-role]")) {
    const role = element.getAttribute("data-dev-role");
    const id = element.getAttribute("data-dev-id");
    if (role) ids.add(role);
    if (id) ids.add(id);
  }
  return ids;
}
