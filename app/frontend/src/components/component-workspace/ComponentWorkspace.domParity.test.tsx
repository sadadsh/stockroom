/**
 * CURRENT SHIPPED-DOM LOCK: the opened component's approved DOM, byte for byte.
 *
 * WHY THIS FILE EXISTS. The component workspace is composed through a layout document, and a broad
 * tree snapshot catches accidental movement, removal, identity loss and control duplication much
 * more cheaply than a screenshot. A matching tree is a strong paint precondition; native screenshots
 * remain the authority for colour, spacing and WebView behavior.
 *
 * PROVENANCE. These fixtures began as the verified pre-renderer Phase 0 trees: the old and new
 * renderers produced identical bytes. They were deliberately rebaselined after later owner-approved
 * product changes, most recently for the compact sourcing disclosures and the laptop Design Studio
 * promotion (semantic icons, missing-CAD presentation, and conditional empty source row). They now
 * lock the current shipped arrangement rather than claim historical Phase 0 identity.
 *
 * WHY EACH TREE IS ALSO CHECKED AGAINST A DIGEST WRITTEN OUT IN THIS FILE. A file snapshot alone is
 * rewritten by `vitest -u`, which is exactly the move this gate has to survive: an accidental change
 * must not disappear under a flag. The digests below are source, not snapshot, so re-capturing a tree
 * is a two-part edit that shows up in review.
 *
 * TO RE-CAPTURE DELIBERATELY after an approved product change: run only this file with `-u`, inspect
 * all four fixture diffs, then paste the digests printed by the preceding non-update run.
 *
 * PROVEN NON-VACUOUS BY MUTATION, and the mutation reverted: changing the column title strip's
 * height class from `h-[24px]` to `h-[25px]` - one character, in one shared primitive - turned four
 * of the seven trees red on the digest before the snapshot was consulted. A gate that could not see
 * that could not see anything.
 *
 * WHAT IS NORMALISED BEFORE COMPARING, and why it is not a hole in the gate:
 *
 *   `blob:mock/<n>`  the jsdom object-URL stub in `test/setup.ts` counts UP for the whole file, so
 *                    the second render of a run gets different URLs than the first for reasons that
 *                    have nothing to do with the arrangement. The COUNT and POSITION of every
 *                    object URL still has to match; only the serial number is masked.
 *
 * Nothing else is masked. Column widths are real numbers (jsdom never measures the band, so the
 * assumed 1366px total is deterministic), the clock is frozen, and the fixtures carry fixed
 * timestamps, so every other byte is compared exactly.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import type { ReactNode } from "react";
import { ApiError, api } from "../../api/client";
import { cadVariantApi } from "../../api/cadVariantClient";
import type { ComponentDossier } from "../../api/dossierTypes";
import { ThemeProvider } from "../../lib/theme";
import { ToastProvider } from "../../lib/toast";
import {
  defaultUiSession,
  openComponentInSession,
  resetUiSessionForTests,
} from "../../lib/uiSession";
import { ComponentWorkspace, ComponentWorkspaceEmpty } from "./ComponentWorkspace";
import {
  FIXTURE_COMPONENT_ID,
  FIXTURE_NOW,
  populatedDossier,
  sparseDossier,
} from "./workspaceDomFixtures";

vi.mock("../../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../../api/client")>();
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

vi.mock("../../api/cadVariantClient", async (importActual) => {
  const actual = await importActual<typeof import("../../api/cadVariantClient")>();
  return {
    ...actual,
    cadVariantApi: { inventory: vi.fn(), activatePair: vi.fn() },
  };
});

// three.js is verified in the Windows pixel gate; the DOM the module contributes is the canvas
// host and its control strip, which is what this gate is about.
vi.mock("../../lib/threeScene", () => ({
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

// Developer mode changes the DOM twice over - it fills the provenance section, which un-sparses the
// sourcing column and therefore moves all three column widths - so it is a fixture axis rather than
// a footnote. The real provider reads keyboard state and storage; a flag this file owns is what
// makes "the same component, developer mode on" a repeatable render.
let developerMode = false;

vi.mock("../../lib/devMode", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/devMode")>();
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

/**
 * Render, then wait until the tree stops moving.
 *
 * Not `waitFor(one element)`: this gate compares the WHOLE tree, so a render that has drawn the
 * header but not yet resolved a preview would be captured half-finished and the expectation would
 * encode a race. Three consecutive identical reads is the settle condition - two is not enough,
 * because a query that resolves on the turn between two reads produces one accidental repeat.
 */
async function settle(container: HTMLElement): Promise<string> {
  let previous = "";
  let stable = 0;
  for (let pass = 0; pass < 80; pass += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    const current = container.innerHTML;
    stable = current === previous ? stable + 1 : 0;
    previous = current;
    if (stable >= 2) return current;
  }
  throw new Error("the workspace never stopped re-rendering");
}

async function renderWorkspace(dossier: ComponentDossier): Promise<string> {
  resetUiSessionForTests(openComponentInSession(defaultUiSession(), FIXTURE_COMPONENT_ID));
  mockApi.partDossier.mockResolvedValue(dossier);
  const view = provide(<ComponentWorkspace componentId={FIXTURE_COMPONENT_ID} />);
  return settle(view.container);
}

/** The one volatile token, masked. See the file header for why this is not a hole. */
function normalise(html: string): string {
  return html.replace(/blob:mock\/\d+/g, "blob:mock/x");
}

/** A newline between adjacent tags, so the committed tree is a diff a person can read. */
function readable(html: string): string {
  return `${html.replace(/></g, ">\n<")}\n`;
}

/**
 * A digest of the tree, computed in plain arithmetic.
 *
 * Not a cryptographic hash and it does not need to be: its whole job is to be a value that lives in
 * THIS FILE rather than in the snapshot, so that rewriting the snapshot is not sufficient to make a
 * changed tree pass. Length plus two independent 32-bit mixes over every character.
 */
function digest(text: string): string {
  let a = 0x811c9dc5;
  let b = 0x9e3779b9;
  for (let index = 0; index < text.length; index += 1) {
    const code = text.charCodeAt(index);
    a = Math.imul(a ^ code, 0x01000193) >>> 0;
    b = Math.imul(b + code + index, 0x85ebca6b) >>> 0;
    b = (b ^ (b >>> 13)) >>> 0;
  }
  const hex = (value: number) => value.toString(16).padStart(8, "0");
  return `${text.length}-${hex(a)}-${hex(b)}`;
}

async function expectTree(name: string, html: string, expected: string): Promise<void> {
  const tree = readable(normalise(html));
  // The digest first: it is the assertion `-u` cannot satisfy, and reading its failure message is
  // how a deliberate re-capture gets the new value.
  expect(digest(tree), `dom-parity digest for ${name}`).toBe(expected);
  await expect(tree).toMatchFileSnapshot(`./__dom-parity__/${name}.html`);
}

describe("the opened component renders the same DOM it shipped with", () => {
  it("draws a fully populated component identically", async () => {
    await expectTree(
      "populated",
      await renderWorkspace(populatedDossier()),
      "84043-df5f618c-ce8eda5a",
    );
  });

  it("draws a fully populated component identically in developer mode", async () => {
    developerMode = true;
    await expectTree(
      "populated-developer",
      await renderWorkspace(populatedDossier()),
      "99257-1f1a12c7-d5713046",
    );
  });

  it("draws a component nobody has sourced identically", async () => {
    await expectTree("sparse", await renderWorkspace(sparseDossier()), "26964-1a81344e-621a9052");
  });

  it("draws a component nobody has sourced identically in developer mode", async () => {
    // Developer mode fills the provenance section, so this component is NOT sparse here and the
    // three columns take their resting widths. That difference is the point of the fixture.
    developerMode = true;
    await expectTree(
      "sparse-developer",
      await renderWorkspace(sparseDossier()),
      "37347-dd9ef614-8984d67c",
    );
  });

  it("draws the loading state identically", async () => {
    resetUiSessionForTests(openComponentInSession(defaultUiSession(), FIXTURE_COMPONENT_ID));
    mockApi.partDossier.mockReturnValue(new Promise(() => {}));
    const view = provide(<ComponentWorkspace componentId={FIXTURE_COMPONENT_ID} />);
    await expectTree("loading", await settle(view.container), "869-b566eb0e-cf139882");
  });

  it("draws the failed state identically", async () => {
    resetUiSessionForTests(openComponentInSession(defaultUiSession(), FIXTURE_COMPONENT_ID));
    mockApi.partDossier.mockRejectedValue(new ApiError(500, "no"));
    const view = provide(<ComponentWorkspace componentId={FIXTURE_COMPONENT_ID} />);
    await expectTree("failed", await settle(view.container), "1298-68231b61-e8555ba3");
  });

  it("draws the empty workspace identically", async () => {
    const view = provide(<ComponentWorkspaceEmpty />);
    await expectTree("empty", await settle(view.container), "395-4cbf6f7b-e01211fd");
  });
});
