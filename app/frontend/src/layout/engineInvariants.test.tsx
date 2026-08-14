/**
 * THE ENGINE INVARIANTS (plan 1.6): what has to hold for ANY layout document, not just the shipped one.
 *
 * The other files in this directory bind the DEFAULT document: three columns in this order, these
 * sections, these scroll owners. Those are facts about ONE arrangement, and a committed redesign is
 * allowed to change every one of them. This file is the other half of that reframing - the properties
 * a redesign is NOT allowed to break, whatever it rearranges, because breaking one produces a surface
 * nobody can read: a page that scrolls, two scrollbars fighting over one wheel gesture, a tab order
 * that disagrees with the reading order, or a piece that cannot be drawn where it was dropped.
 *
 * SO EVERY TEST HERE RUNS AGAINST MORE THAN ONE DOCUMENT. The shipped one, a deliberately REARRANGED
 * one (a column moved, a column's sections reversed, a piece carried into another column), documents
 * built here from scratch, and - for the scroll invariants - the same document under pathological
 * content. A test that only ever saw the shipped arrangement would be a fourth default-document test
 * wearing a different name.
 *
 * HOW AN ARBITRARY DOCUMENT IS RENDERED THROUGH THE REAL BINDINGS. `workspaceBindings` deliberately
 * keeps its piece table module-private and draws `DEFAULT_WORKSPACE_LAYOUT`, so this file replaces
 * that ONE export with a mutable document and leaves everything else - the twenty-six real piece
 * components, the eleven real chrome components, the real condition derivation - untouched. The
 * alternative was a second binding table written out here, which is a copy of the shipped one that
 * could drift, and an invariant proven against a copy is not proven.
 *
 * WHAT IS DEFERRED, and to where. The plan's remaining invariant - EVERY ACTION REACHABLE OR WARNED -
 * is NOT here and is deliberately NOT stubbed. It needs the action registry, which is plan Phase 5
 * (1.3): today a manifest's `actions` are declared STRINGS, so "reachable" has nothing to resolve
 * against and a test asserting it would be asserting that a list of strings is a list of strings.
 * When Phase 5 lands the registry, that invariant belongs in this file beside the other four.
 *
 * ---------------------------------------------------------------------------------------------
 * NON-VACUITY. Each test below names the mutation that turns it red. Four were run for real and
 * reverted:
 *
 *   1. THE FRAME STOPPED CLIPPING. Removing `overflow-hidden` from `WorkspaceRootChrome`'s frame in
 *      `workspaceBindings.tsx` failed "clips the frame it draws every document inside" for both
 *      documents, and failed the pathological-content case with it - the frame is what makes every
 *      scroller below it a local one instead of the page's.
 *   2. THE RENDERER STOPPED FOLLOWING THE DOCUMENT. Reversing `region.slots` in `LayoutRegionView`
 *      (`LayoutRenderer.tsx`) failed "puts the focusable pieces in the document's own order" on the
 *      first pair it compared, and failed the band-order case with it.
 *   3. A PIECE LOST ITS BINDING. Deleting `"workspace.sourcing-pricing"` from
 *      `WORKSPACE_LAYOUT_BINDINGS` failed "draws each manifest's piece in isolation" naming exactly
 *      that piece - which is the failure a registry entry nothing can draw has to produce.
 *   4. A MANIFEST UNDER-DECLARED ITS SCROLLING. Putting `workspace.sourcing-provenance`'s `scroll`
 *      back to `{ owns: false }` failed "declares every scroll container a piece draws inside itself"
 *      with `workspace.sourcing-provenance scrolls horizontal undeclared`. That was not a hypothetical:
 *      writing this file FOUND that state - the provenance ledger's table has always been wrapped in an
 *      `overflow-x-auto` div while its manifest said it scrolled nothing - and the manifest was
 *      corrected rather than the test scoped around it.
 *
 * THE TWO KNOWN VACUOUS SHAPES, and why neither applies:
 *
 *   AN EFFECT SETTLING AFTER THE READ. `settle()` waits for the tree to stop changing, and every scan
 *   below is preceded by a FLOOR assertion - a named minimum that must be on screen before the scan
 *   means anything. A premature or empty render fails the floor rather than passing a scan that found
 *   nothing wrong. The piece-by-piece case goes further: what a piece drew is measured as the
 *   DIFFERENCE against the same document with that one placement hidden, so chrome cannot stand in
 *   for a piece that drew nothing at all.
 *
 *   A SOURCE GATE MATCHING ITS OWN COMMENT. Nothing here reads source text. The scroll invariants are
 *   measured off the rendered DOM, the order invariants off `compareDocumentPosition`, and every
 *   expectation is computed from the document that was rendered rather than written out by hand.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render } from "@testing-library/react";
import type { ReactNode } from "react";
import { ApiError, api } from "../api/client";
import { cadVariantApi } from "../api/cadVariantClient";
import type { ComponentDossier, SpecificationGroup } from "../api/dossierTypes";
import {
  FIXTURE_COMPONENT_ID,
  FIXTURE_NOW,
  populatedDossier,
  sparseDossier,
} from "../components/component-workspace/workspaceDomFixtures";
import { ThemeProvider } from "../lib/theme";
import { ToastProvider } from "../lib/toast";
import { makeDocument, makeOffer, makeSpecification } from "../test/dossierFixture";
import { workspaceRenderFixture } from "../test/workspaceRenderFixture";
import {
  findRegion,
  layoutPlacements,
  layoutRegions,
  validateLayout,
  type LayoutDocument,
  type LayoutNode,
  type LayoutRegion,
  type LayoutSlot,
  type PiecePlacement,
} from "./document";
import { WorkspaceDocumentView } from "./workspaceBindings";
import { WORKSPACE_PIECES, WORKSPACE_PIECE_REGISTRY, WORKSPACE_REGION } from "./workspacePieces";

/**
 * The document under test, as a MUTABLE object the shipped bindings draw.
 *
 * `layout.live` is the object `workspaceBindings` imports; `layout.pristine` is the untouched shipped
 * document every case here derives from. Both are filled inside the mock factory, which is the only
 * place able to read the real module.
 */
const layout = vi.hoisted(() => ({
  live: {
    schemaVersion: 1,
    id: "workspace.component",
    root: { kind: "region", id: "workspace.root", mode: "column", slots: [] },
  } as unknown as LayoutDocument,
  pristine: null as LayoutDocument | null,
}));

vi.mock("./defaultWorkspaceLayout", async (importActual) => {
  const actual = await importActual<typeof import("./defaultWorkspaceLayout")>();
  // A JSON round trip, which this document is guaranteed to survive (`defaultWorkspaceLayout.test.ts`
  // asserts exactly that), so nothing here can reach the shipped document by reference.
  const clone = () => JSON.parse(JSON.stringify(actual.DEFAULT_WORKSPACE_LAYOUT)) as LayoutDocument;
  layout.pristine = clone();
  Object.assign(layout.live, clone());
  return { ...actual, DEFAULT_WORKSPACE_LAYOUT: layout.live };
});

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

const mockApi = vi.mocked(api);
const mockCadVariantApi = vi.mocked(cadVariantApi);

beforeEach(() => {
  window.localStorage.clear();
  vi.useFakeTimers({ shouldAdvanceTime: true, now: FIXTURE_NOW });
  mockApi.previewSvg.mockResolvedValue(new Blob(["<svg/>"], { type: "image/svg+xml" }));
  mockApi.modelGlb.mockResolvedValue(new Uint8Array([0x67, 0x6c, 0x54, 0x46]).buffer);
  mockApi.landPattern.mockRejectedValue(new ApiError(404, "no footprint"));
  mockApi.partHistory.mockResolvedValue({ commits: [], count: 0 });
  mockCadVariantApi.inventory.mockResolvedValue({
    partId: FIXTURE_COMPONENT_ID,
    inventories: [],
    pairs: [],
    supplementary: [],
  });
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

/* -------------------------------------------------------------------------- */
/*  documents: the shipped one, a rearranged one, and ones built here          */
/* -------------------------------------------------------------------------- */

function clonePristine(): LayoutDocument {
  return JSON.parse(JSON.stringify(layout.pristine)) as LayoutDocument;
}

/** Point the shipped bindings at this document. */
function useDocument(document_: LayoutDocument): void {
  Object.assign(layout.live, JSON.parse(JSON.stringify(document_)) as LayoutDocument);
}

function slot(id: string, content: LayoutNode): LayoutSlot {
  return { kind: "slot", id, content };
}

function place(id: string, piece: string): PiecePlacement {
  return { kind: "placement", id, piece };
}

function regionOf(document_: LayoutDocument, id: string): LayoutRegion {
  const region = findRegion(document_, id);
  if (!region) throw new Error(`the document has no region ${id}`);
  return region;
}

/**
 * A region of a CLONED document, as something this file can rewrite in place.
 *
 * Every collection on `LayoutRegion` is `readonly`, which is right: a document is data, and code that
 * mutated one somebody else was holding would be the bug that type stops. The rearrangements below are
 * the exception the type cannot express - they edit a clone of the shipped document, exactly as the
 * Phase 3 editor will - so the cast is here, once, with the reason attached, rather than at each edit.
 */
function editable(region: LayoutRegion): {
  slots: LayoutSlot[];
  splitters?: LayoutRegion["splitters"];
} {
  return region as unknown as { slots: LayoutSlot[]; splitters?: LayoutRegion["splitters"] };
}

/**
 * A DELIBERATE REDESIGN of the shipped arrangement: the point of this whole file.
 *
 * Three independent edits, each of a kind Phase 3 will produce with a drag:
 *
 *   A COLUMN MOVED. The band's first and last slots are swapped, so Sourcing opens on the left and
 *   CAD Assets on the right, and the two splitters are re-paired onto the neighbours they now sit
 *   between - which is what a commit has to do, since a handle between two slots that are no longer
 *   adjacent is a handle nobody can predict.
 *   A COLUMN'S SECTIONS REVERSED. The sourcing body reads bottom-to-top: the reveal control first,
 *   provenance above the offers it explains, lifecycle last.
 *   A PIECE CARRIED ACROSS COLUMNS. The pinout section leaves the specifications body and lands in
 *   the sourcing body, which is the edit that proves a piece is not owned by the column it ships in.
 */
function rearrangedDocument(): LayoutDocument {
  const document_ = clonePristine();
  const band = editable(regionOf(document_, WORKSPACE_REGION.columnBand));
  const sourcingBody = editable(regionOf(document_, WORKSPACE_REGION.sourcingBody));
  const specificationsBody = editable(regionOf(document_, WORKSPACE_REGION.specificationsBody));

  const columns = [...band.slots];
  [columns[0], columns[columns.length - 1]] = [columns[columns.length - 1], columns[0]];
  band.slots = columns;
  band.splitters = (band.splitters ?? []).map((splitter, index) => ({
    ...splitter,
    between: [columns[index].id, columns[index + 1].id] as [string, string],
  }));

  const pinout = specificationsBody.slots.find(
    (entry) => entry.content?.kind === "placement" && entry.content.piece.endsWith("-pinout"),
  );
  specificationsBody.slots = specificationsBody.slots.filter((entry) => entry !== pinout);
  sourcingBody.slots = [...(pinout ? [pinout] : []), ...sourcingBody.slots].reverse();

  return { ...document_, id: "workspace.component.rearranged" };
}

/**
 * One piece, in its own home, with nothing beside it.
 *
 * The spine is the chain of regions the SHIPPED document already puts the piece inside, each reduced
 * to the single slot that leads to it - so the piece gets the chrome it depends on (a column frame, a
 * body scroller, the context a column derives once) and no sibling. Splitters go with the siblings
 * they pointed at, because a handle naming a slot that is gone is exactly the `splitter-unknown-slot`
 * a validator would report, and these documents are asserted to validate clean.
 */
function isolatedRegion(region: LayoutRegion, piece: string): LayoutRegion | null {
  const frame: LayoutRegion = { ...region, slots: [] };
  delete (frame as { splitters?: unknown }).splitters;
  for (const entry of region.slots) {
    const content = entry.content;
    if (!content) continue;
    if (content.kind === "placement") {
      if (content.piece === piece) return { ...frame, slots: [{ ...entry, content }] };
      continue;
    }
    const inner = isolatedRegion(content, piece);
    if (inner) return { ...frame, slots: [{ ...entry, content: inner }] };
  }
  return null;
}

function isolatedDocument(piece: string): LayoutDocument {
  const document_ = clonePristine();
  const root = isolatedRegion(document_.root, piece);
  if (!root) throw new Error(`the shipped document places no ${piece}`);
  return { schemaVersion: document_.schemaVersion, id: `${document_.id}.only.${piece}`, root };
}

/** The same isolated document with its one placement hidden: the chrome, and nothing in it. */
function withPlacementHidden(document_: LayoutDocument): LayoutDocument {
  const copy = JSON.parse(JSON.stringify(document_)) as LayoutDocument;
  let node: LayoutNode | null = copy.root;
  while (node && node.kind === "region") {
    const next: LayoutNode | null = node.slots[0]?.content ?? null;
    if (next && next.kind === "placement") next.hidden = true;
    node = next;
  }
  return copy;
}

/** The chain of region ids a spine nests, which is what decides the chrome it draws. */
function regionChain(document_: LayoutDocument): string[] {
  const ids: string[] = [];
  let node: LayoutNode | null = document_.root;
  while (node && node.kind === "region") {
    ids.push(node.id);
    node = node.slots[0]?.content ?? null;
  }
  return ids;
}

/* -------------------------------------------------------------------------- */
/*  rendering                                                                  */
/* -------------------------------------------------------------------------- */

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

/** Wait until the tree stops changing, so a scan reads a finished surface. */
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
  throw new Error("the document never stopped re-rendering");
}

/**
 * Draw one document, with the previous one unmounted first.
 *
 * `cleanup()` matters: several cases here render more than once, and the page-scroll scan reads the
 * whole of `document.body`, so a left-over tree from the previous render would be counted as a
 * scroller outside the current frame.
 */
async function renderDocument(
  document_: LayoutDocument,
  dossier: ComponentDossier,
): Promise<HTMLElement> {
  cleanup();
  useDocument(document_);
  const view = provide(
    <WorkspaceDocumentView
      context={workspaceRenderFixture(dossier, { componentId: FIXTURE_COMPONENT_ID })}
    />,
  );
  await settle(view.container);
  return view.container;
}

/* -------------------------------------------------------------------------- */
/*  reading the mechanism off the DOM                                          */
/* -------------------------------------------------------------------------- */

type Axis = "vertical" | "horizontal";

const SCROLLS = /^(auto|scroll)$/;
const CLIPS = /^(hidden|clip)$/;

/**
 * Which axes this ELEMENT can scroll, read off the mechanism rather than off a known class name.
 *
 * Any overflow utility that resolves to `auto` or `scroll` counts, on whichever axis it names, and so
 * does an inline style - so a scroller introduced by `overflow-auto` instead of `overflow-y-auto`, by
 * a `scroll` variant, or by a style object is caught exactly like the ones that ship today. jsdom
 * applies no stylesheet, so a `getComputedStyle` read would answer `visible` for every element in the
 * tree and every scroll assertion in this file would pass by measuring nothing; the DECLARATION is
 * what a browser turns into a scroll container, and the declaration is what is checked.
 */
function scrollAxes(element: HTMLElement): Set<Axis> {
  const axes = new Set<Axis>();
  for (const name of element.classList) {
    const match = /^overflow(?:-([xy]))?-(auto|scroll)$/.exec(name);
    if (!match) continue;
    if (match[1] === "x") axes.add("horizontal");
    else if (match[1] === "y") axes.add("vertical");
    else {
      axes.add("horizontal");
      axes.add("vertical");
    }
  }
  const { overflow, overflowX, overflowY } = element.style;
  if (SCROLLS.test(overflow)) {
    axes.add("horizontal");
    axes.add("vertical");
  }
  if (SCROLLS.test(overflowX)) axes.add("horizontal");
  if (SCROLLS.test(overflowY)) axes.add("vertical");
  return axes;
}

/** Does this element clip BOTH axes, by whichever utility or style says so. */
function clipsBothAxes(element: HTMLElement): boolean {
  const clipped = new Set<Axis>();
  for (const name of element.classList) {
    const match = /^overflow(?:-([xy]))?-(hidden|clip)$/.exec(name);
    if (!match) continue;
    if (match[1] === "x") clipped.add("horizontal");
    else if (match[1] === "y") clipped.add("vertical");
    else {
      clipped.add("horizontal");
      clipped.add("vertical");
    }
  }
  const { overflow, overflowX, overflowY } = element.style;
  if (CLIPS.test(overflow)) {
    clipped.add("horizontal");
    clipped.add("vertical");
  }
  if (CLIPS.test(overflowX)) clipped.add("horizontal");
  if (CLIPS.test(overflowY)) clipped.add("vertical");
  return clipped.has("horizontal") && clipped.has("vertical");
}

function elementsIn(root: ParentNode): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>("*")];
}

interface Scroller {
  element: HTMLElement;
  axes: Set<Axis>;
}

function scrollersIn(root: ParentNode): Scroller[] {
  return elementsIn(root)
    .map((element) => ({ element, axes: scrollAxes(element) }))
    .filter((entry) => entry.axes.size > 0);
}

/** The one element the whole document is drawn inside. */
function frameOf(container: HTMLElement): HTMLElement {
  const frame = container.firstElementChild as HTMLElement | null;
  if (!frame) throw new Error("the document rendered nothing at all");
  return frame;
}

const FOCUSABLE =
  "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), " +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function focusablesIn(root: ParentNode): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)];
}

function devIdElement(container: ParentNode, id: string): HTMLElement {
  const element = container.querySelector<HTMLElement>(`[data-dev-id="${id}"]`);
  if (!element) throw new Error(`nothing rendered ${id}`);
  return element;
}

/** A precedes B in the rendered tree. */
function precedes(first: HTMLElement, second: HTMLElement): boolean {
  return Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);
}

/**
 * The floor every full-document scan stands on.
 *
 * A scan for "nothing wrong" passes trivially on an empty tree, so each case asserts first that the
 * surface it is about to scan was really drawn.
 */
function expectWorkspaceDrawn(container: HTMLElement): void {
  expect(elementsIn(container).length).toBeGreaterThan(100);
  expect(container.querySelectorAll("[data-workspace-column]")).toHaveLength(3);
  expect(container.querySelectorAll("[data-workspace-scroll]").length).toBeGreaterThan(0);
}

/* -------------------------------------------------------------------------- */
/*  the pathological component                                                 */
/* -------------------------------------------------------------------------- */

/**
 * A component whose content cannot fit in any window: forty specification groups, thirty offers,
 * twenty documents, and labels nobody would wrap.
 *
 * Built ON TOP of the populated fixture rather than beside it, so every conditional section that
 * draws for the populated component draws here too and the two renders place the same pieces. The
 * only difference is how much is in them, which is the whole question: content decides how much
 * SCROLLS and it must never decide WHAT scrolls.
 */
function pathologicalDossier(): ComponentDossier {
  const base = populatedDossier();
  const groups: SpecificationGroup[] = Array.from({ length: 40 }, (_, group) => ({
    id: `group_${group}`,
    label: `Group ${group} ${"very long heading ".repeat(4)}`,
    count: 10,
    specifications: Array.from({ length: 10 }, (_, row) =>
      makeSpecification({
        key: `spec_${group}_${row}`,
        label: `Specification ${group}.${row} ${"long label ".repeat(6)}`,
        group: `group_${group}`,
        groupLabel: `Group ${group}`,
        displayValue: "1".repeat(40),
        unit: "V",
      }),
    ),
  }));
  return {
    ...base,
    specificationGroups: [...base.specificationGroups, ...groups],
    distributorOffers: Array.from({ length: 30 }, (_, index) =>
      makeOffer({
        provider: `provider_${index}`,
        providerLabel: `Provider ${index} ${"long name ".repeat(4)}`,
        sku: `SKU-${index}-${"0".repeat(30)}`,
        stock: 1000 + index,
      }),
    ),
    documents: {
      ...base.documents,
      items: Array.from({ length: 20 }, (_, index) =>
        makeDocument({
          id: `document_${index}`,
          title: `Document ${index} ${"long title ".repeat(8)}`,
        }),
      ),
      count: 20,
    },
  };
}

/* -------------------------------------------------------------------------- */
/*  1. no document grows a page scrollbar                                      */
/* -------------------------------------------------------------------------- */

describe("no layout document grows a page scrollbar", () => {
  /**
   * FAILS IF: the frame stops clipping (remove `overflow-hidden` from `WorkspaceRootChrome`), the
   * frame itself becomes a scroller, or a scroller is drawn outside it (portal a scrolling element
   * straight into `document.body`). PROVEN by removing the frame's `overflow-hidden`; reverted.
   */
  it("clips the frame it draws every document inside, and keeps every scroller under it", async () => {
    for (const document_ of [clonePristine(), rearrangedDocument()]) {
      const container = await renderDocument(document_, populatedDossier());
      expectWorkspaceDrawn(container);

      const frame = frameOf(container);
      // The frame IS the mechanism: it clips both axes and scrolls neither, so every scroller below
      // it is a local one and the page itself has nothing left to scroll.
      expect(clipsBothAxes(frame), `${document_.id}: the frame clips both axes`).toBe(true);
      expect([...scrollAxes(frame)], `${document_.id}: the frame scrolls nothing`).toEqual([]);

      const outside = scrollersIn(document.body)
        .filter((entry) => !frame.contains(entry.element))
        .map((entry) => entry.element.className);
      expect(outside, `${document_.id}: scrollers outside the frame`).toEqual([]);
    }
  }, 60_000);

  /**
   * FAILS IF: a piece grows a scroll container of its own when its content grows - a virtualised list
   * with its own viewport, a table wrapper added above some row count, a `max-h-*` with
   * `overflow-y-auto` on a section. The SET of scrollers is the assertion: content may change how much
   * scrolls, never what.
   */
  it("adds no scroll container when the content is pathological", async () => {
    const document_ = rearrangedDocument();
    const ordinary = await renderDocument(document_, populatedDossier());
    expectWorkspaceDrawn(ordinary);
    const before = scrollersIn(ordinary).map((entry) => [...entry.axes].sort().join("+"));

    const pathological = await renderDocument(document_, pathologicalDossier());
    expectWorkspaceDrawn(pathological);
    // The floor for THIS case: the enormous component really drew its rows, so the comparison is
    // between two full renders rather than between one full render and one that gave up.
    expect(
      pathological.querySelectorAll('[data-dev-id="component-browser.spec-row"]').length,
    ).toBeGreaterThan(100);

    expect(scrollersIn(pathological).map((entry) => [...entry.axes].sort().join("+"))).toEqual(
      before,
    );
    expect(clipsBothAxes(frameOf(pathological))).toBe(true);
  }, 60_000);
});

/* -------------------------------------------------------------------------- */
/*  2. every region owns at most one scroll axis                               */
/* -------------------------------------------------------------------------- */

/**
 * The scrollers a REGION owns, as opposed to the ones a piece draws inside itself.
 *
 * A region that declares `scroll` renders one of two elements in this arrangement: the column
 * scroller primitive, which marks itself `data-workspace-scroll`, or a band that carries the
 * region's own `devId`. Both are read here from the DOCUMENT rather than from a list of class names,
 * so a rearranged document's region scrollers are found the same way the shipped one's are.
 *
 * The distinction matters because the two kinds answer different questions. A REGION's scroll is the
 * arrangement's - the plan's invariant, "each region owns at most one scroll axis", is about these.
 * A PIECE's internal scroll is the piece's own business (the provenance ledger declares one in its
 * manifest and scrolls sideways inside its section); what the
 * invariant has to say about those is that they are CONTAINED and DECLARED, never that they do not
 * exist.
 */
function regionScrollerDevIds(document_: LayoutDocument): Set<string> {
  const ids = new Set<string>();
  for (const visit of layoutRegions(document_)) {
    if (visit.node.scroll && visit.node.devId) ids.add(visit.node.devId);
  }
  return ids;
}

function isRegionScroller(element: HTMLElement, regionDevIds: ReadonlySet<string>): boolean {
  const devId = element.dataset.devId;
  return element.hasAttribute("data-workspace-scroll") || Boolean(devId && regionDevIds.has(devId));
}

/**
 * Which manifest claims each dev identity, so a rendered element can be traced to its piece.
 *
 * `data-dev-role` is consulted before `data-dev-id` for the same reason the coverage gate does it:
 * the three CAD modules carry a per-component INSTANCE id and declare the CLASS they belong to as
 * their role, and the class is what a manifest can name.
 */
const PIECE_BY_DEV_ID = new Map(
  WORKSPACE_PIECES.flatMap((manifest) => manifest.devIds.map((id) => [id, manifest] as const)),
);

/** The piece that drew this element: the nearest ancestor-or-self a manifest claims. */
function owningPiece(element: HTMLElement, container: HTMLElement) {
  let node: HTMLElement | null = element;
  while (node && node !== container) {
    const role = node.getAttribute("data-dev-role");
    const id = node.getAttribute("data-dev-id");
    const claimed = (role ? PIECE_BY_DEV_ID.get(role) : undefined) ??
      (id ? PIECE_BY_DEV_ID.get(id) : undefined);
    if (claimed) return claimed;
    node = node.parentElement;
  }
  return null;
}

describe("every region the renderer draws owns at most one scroll axis", () => {
  /**
   * THREE PARTS, and the third is why the second is about region scrollers only.
   *
   *   ONE AXIS EACH. No element in the tree scrolls both axes, whoever drew it.
   *   NO REGION SCROLLER INSIDE A REGION SCROLLER THAT SHARES ITS AXIS. Two vertical scrollers one
   *   inside the other is the state where nobody can say which one a wheel gesture moves.
   *   EVERY PIECE-INTERNAL SCROLLER IS CONTAINED by a region scroller, so it can never be the thing
   *   the page scrolls. That it is also DECLARED by its piece's manifest is the next test.
   *
   * The nesting rule is deliberately NOT extended to piece-internal scrollers, because the shipped
   * arrangement may nest a piece-owned horizontal axis inside the column band's emergency horizontal
   * overflow. The provenance ledger owns that contained axis; the offers ledger no longer does.
   *
   * FAILS IF: a scroller claims both axes (change `overflow-y-auto overflow-x-hidden` in
   * `WorkspaceColumnScroller` to `overflow-auto`), a region scroller ends up inside another on the
   * same axis, or a piece draws a scroller outside every region scroller.
   */
  it("gives each scroller one axis, and never nests two region scrollers that share one", async () => {
    for (const document_ of [clonePristine(), rearrangedDocument()]) {
      // This case is about the documents the validator reports NOTHING about; a document it warns
      // over is the next case.
      expect(
        validateLayout(document_, WORKSPACE_PIECE_REGISTRY).filter(
          (issue) => issue.code === "scroll-owner-conflict",
        ),
      ).toEqual([]);

      const container = await renderDocument(document_, pathologicalDossier());
      expectWorkspaceDrawn(container);
      const regionDevIds = regionScrollerDevIds(document_);
      const scrollers = scrollersIn(container);
      const regionScrollers = scrollers.filter((entry) =>
        isRegionScroller(entry.element, regionDevIds),
      );
      // The floor: the columns' own scrollers and the band's sideways overflow are all present, so
      // the assertions below are made against a real set rather than an empty one.
      expect(scrollers.length, `${document_.id}: scrollers found`).toBeGreaterThanOrEqual(4);
      expect(
        regionScrollers.length,
        `${document_.id}: region scrollers found`,
      ).toBeGreaterThanOrEqual(4);

      for (const { element, axes } of scrollers) {
        expect([...axes], `${document_.id}: ${element.className}`).toHaveLength(1);
      }
      for (const outer of regionScrollers) {
        for (const inner of regionScrollers) {
          if (outer.element === inner.element || !outer.element.contains(inner.element)) continue;
          expect(
            [...inner.axes].filter((axis) => outer.axes.has(axis)),
            `${document_.id}: nested region scrollers share an axis`,
          ).toEqual([]);
        }
      }
      for (const entry of scrollers) {
        if (isRegionScroller(entry.element, regionDevIds)) continue;
        expect(
          regionScrollers.some((region) => region.element.contains(entry.element)),
          `${document_.id}: ${entry.element.className} scrolls outside every region scroller`,
        ).toBe(true);
      }
    }
  }, 60_000);

  /**
   * THE STRONG FORM: a scroll container a piece draws inside itself must be DECLARED by that piece's
   * manifest, on the axis it actually scrolls.
   *
   * This is what makes the registry answerable about scrolling rather than merely descriptive. The
   * builder reads `scroll` to decide what may be placed where - a piece that scrolls an axis cannot be
   * dropped into a region that already owns it - so an undeclared scroller is a piece the builder will
   * place into exactly the conflict the validator exists to report, with nothing anywhere saying why.
   * Every scroller is traced to its piece through the manifests' own dev ids, so a piece is measured
   * against its own declaration rather than against a list kept here.
   *
   * FAILS IF: a piece renders a scroll container its manifest does not declare (revert
   * `workspace.sourcing-provenance`'s `scroll` to `{ owns: false }`, which is the state this file
   * found and the manifest was corrected from), declares the wrong axis, or draws a scroller no
   * manifest owns at all. PROVEN by that revert; re-applied.
   */
  it("declares every scroll container a piece draws inside itself", async () => {
    for (const document_ of [clonePristine(), rearrangedDocument()]) {
      const container = await renderDocument(document_, pathologicalDossier());
      expectWorkspaceDrawn(container);
      const regionDevIds = regionScrollerDevIds(document_);
      const pieceScrollers = scrollersIn(container).filter(
        (entry) => !isRegionScroller(entry.element, regionDevIds),
      );
      // The floor: the provenance ledger's declared horizontal scroller is on screen, so the scan
      // below has something real to be right about.
      expect(
        pieceScrollers.length,
        `${document_.id}: piece-internal scrollers found`,
      ).toBeGreaterThanOrEqual(1);

      const undeclared: string[] = [];
      for (const { element, axes } of pieceScrollers) {
        const owner = owningPiece(element, container);
        if (!owner) {
          undeclared.push(`no manifest owns ${element.className}`);
          continue;
        }
        for (const axis of axes) {
          if (owner.scroll.owns && owner.scroll.axis === axis) continue;
          undeclared.push(`${owner.id} scrolls ${axis} undeclared`);
        }
      }
      expect(undeclared, document_.id).toEqual([]);

      // And the other direction: a piece that DECLARES a scroll axis and draws none would make the
      // declaration a fiction the builder would still honour. Checked for the pieces on screen.
      const scrolled = new Set(
        pieceScrollers.map((entry) => owningPiece(entry.element, container)?.id),
      );
      const onScreen = WORKSPACE_PIECES.filter(
        (manifest) =>
          manifest.scroll.owns &&
          manifest.devIds.some((id) => container.querySelector(`[data-dev-id="${id}"]`)),
      );
      expect(onScreen.length, `${document_.id}: declared scrollers on screen`).toBeGreaterThan(0);
      expect(
        onScreen.filter((manifest) => !scrolled.has(manifest.id)).map((manifest) => manifest.id),
        `${document_.id}: declared a scroll axis and drew none`,
      ).toEqual([]);
    }
  }, 60_000);

  /**
   * The other half of the invariant, and the half the RENDERER owns: a document that DOES stack two
   * scroll owners on one axis is reported and still drawn. Warn, never block (plan decision 3) - a
   * renderer that refused would take the surface down over an arrangement somebody is halfway through
   * editing, and a validator that stayed quiet would let it ship.
   *
   * FAILS IF: `validateLayout` stops reporting `scroll-owner-conflict`, or the renderer throws or
   * blanks the surface on a document carrying one.
   */
  it("reports a stacked pair of scroll owners and still draws the surface", async () => {
    const document_ = clonePristine();
    const column = editable(regionOf(document_, WORKSPACE_REGION.sourcingColumn));
    // A SECOND vertical scroll owner directly under the first, in the same column - the shape one
    // drag could produce. It carries the same region id, because the id is what resolves the chrome
    // and a copy under a new name would silently render no scroller at all and prove nothing.
    const second: LayoutRegion = {
      kind: "region",
      id: WORKSPACE_REGION.sourcingBody,
      mode: "column",
      size: { grow: true },
      scroll: "vertical",
      slots: [
        slot(
          "workspace.slot.sourcing-lifecycle-again",
          place("workspace.place.sourcing-lifecycle-again", "workspace.sourcing-lifecycle"),
        ),
      ],
    };
    column.slots = [...column.slots, slot("workspace.slot.sourcing-body-again", second)];

    const conflicts = validateLayout(document_, WORKSPACE_PIECE_REGISTRY).filter(
      (issue) => issue.code === "scroll-owner-conflict",
    );
    expect(conflicts.map((issue) => issue.nodeId)).toEqual([WORKSPACE_REGION.sourcingColumn]);
    expect(conflicts[0].severity).toBe("warning");
    expect(conflicts[0].detail?.axis).toBe("vertical");

    const container = await renderDocument(document_, populatedDossier());
    // Drawn anyway, and drawn WHOLE: the reported document is still the surface somebody is looking
    // at, and every scroller in it still owns exactly one axis.
    expectWorkspaceDrawn(container);
    expect(container.querySelectorAll('[data-workspace-scroll="sourcing"]')).toHaveLength(2);
    for (const { axes } of scrollersIn(container)) expect([...axes]).toHaveLength(1);
  }, 60_000);
});

/* -------------------------------------------------------------------------- */
/*  3. focus order follows document order                                      */
/* -------------------------------------------------------------------------- */

/**
 * Three pieces that each draw a focusable control carrying a dev id nothing else claims, so a rendered
 * element can be attributed to the placement that produced it.
 *
 * They come from three different columns of the shipped arrangement on purpose: the document decides
 * where a piece goes, and a focus-order case that only reordered siblings inside one column would not
 * have shown that.
 */
const FOCUS_MARKERS: readonly { piece: string; marker: string }[] = [
  { piece: "workspace.specifications-pinout", marker: "component-browser.pinout-open" },
  { piece: "workspace.sourcing-offers", marker: "component-browser.refresh-offers" },
  { piece: "workspace.header-actions", marker: "component-browser.copy-mpn" },
];

/** A one-column document holding exactly these pieces, in exactly this order. */
function focusDocument(pieces: readonly string[]): LayoutDocument {
  const body: LayoutRegion = {
    kind: "region",
    id: WORKSPACE_REGION.sourcingBody,
    mode: "column",
    size: { grow: true },
    scroll: "vertical",
    slots: pieces.map((piece, index) =>
      slot(`workspace.slot.focus-${index}`, place(`workspace.place.focus-${index}`, piece)),
    ),
  };
  return {
    schemaVersion: 1,
    id: "workspace.component.focus-order",
    root: {
      kind: "region",
      id: WORKSPACE_REGION.root,
      mode: "column",
      slots: [
        slot("workspace.slot.focus-column", {
          kind: "region",
          id: WORKSPACE_REGION.sourcingColumn,
          mode: "column",
          slots: [slot("workspace.slot.focus-body", body)],
        }),
      ],
    },
  };
}

describe("focus order follows document order", () => {
  /**
   * WHY DOM ORDER IS THE ASSERTION. Sequential focus navigation belongs to the browser, not to jsdom:
   * pressing Tab in jsdom moves nothing, and `userEvent`'s Tab walks its own list of focusable
   * elements in DOM order - so asserting through it would be asserting the test library. In a real
   * browser the sequential focus order of elements carrying no positive `tabindex` IS tree order, so
   * DOM order is the honest proxy and `compareDocumentPosition` the honest way to read it. The
   * `tabindex` half of that assumption is not assumed: a positive `tabindex` anywhere would make the
   * proxy false, so its absence is asserted below.
   *
   * FAILS IF: the renderer stops following slot order (reverse `region.slots` in `LayoutRegionView`),
   * chrome reorders what it is handed, or a piece is drawn outside the slot that placed it. PROVEN by
   * reversing `region.slots`; reverted.
   */
  it("puts the focusable pieces in the document's own order, and follows it when it changes", async () => {
    const forward = FOCUS_MARKERS.map((entry) => entry.piece);
    const orders = [forward, [...forward].reverse()];

    for (const order of orders) {
      const container = await renderDocument(focusDocument(order), populatedDossier());
      const markers = order.map((piece) => {
        const entry = FOCUS_MARKERS.find((candidate) => candidate.piece === piece)!;
        return devIdElement(container, entry.marker);
      });
      // The floor: all three pieces really drew their control, so the ordering below compares three
      // elements rather than passing over a list it never filled.
      expect(markers).toHaveLength(3);
      expect(focusablesIn(container).length).toBeGreaterThanOrEqual(3);

      for (let index = 0; index + 1 < markers.length; index += 1) {
        expect(
          precedes(markers[index], markers[index + 1]),
          `${order[index]} is drawn before ${order[index + 1]}`,
        ).toBe(true);
      }

      // Nothing claims a place of its own in the sequence, which is what makes tree order the whole
      // tab order rather than most of it.
      expect(
        focusablesIn(container).filter(
          (element) => Number(element.getAttribute("tabindex") ?? "0") > 0,
        ),
      ).toEqual([]);
    }
  }, 60_000);

  /**
   * The same claim about REGIONS rather than pieces: a band's columns come out in the order its slots
   * name, whatever that order is.
   *
   * FAILS IF: the band draws a fixed order rather than the document's - which is exactly what
   * `WorkspaceColumns.tsx` did while the three columns were three props.
   */
  it("draws the regions of a band in the band's own slot order", async () => {
    for (const document_ of [clonePristine(), rearrangedDocument()]) {
      const container = await renderDocument(document_, populatedDossier());
      const band = regionOf(document_, WORKSPACE_REGION.columnBand);
      const expected = band.slots.map((entry) =>
        entry.content?.kind === "region" ? entry.content.devId : undefined,
      );
      const drawn = [...container.querySelectorAll<HTMLElement>("[data-workspace-column]")].map(
        (element) => element.dataset.devId,
      );
      expect(drawn, document_.id).toEqual(expected);
    }
  }, 60_000);
});

/* -------------------------------------------------------------------------- */
/*  4. every registered piece is renderable on its own                         */
/* -------------------------------------------------------------------------- */

describe("every registered piece renders where the registry says it lives", () => {
  /**
   * A piece the builder offers has to be drawable ON ITS OWN, in its own home, with nothing beside it
   * - because that is the state a drag produces: one placement in a region, before anything else has
   * been dropped next to it. A piece that only draws when a sibling happens to be there is a piece the
   * owner can move into a hole.
   *
   * WHAT COUNTS AS DRAWN. The isolated document is rendered twice: once as it is, and once with the
   * one placement HIDDEN, which draws the same chrome and no piece. The piece drew something when the
   * first tree has more elements than the second. Measuring "the tree is not empty" instead would pass
   * for every piece in the registry, because a column frame and its scroller are drawn whether the
   * placement inside them produced anything or not - that is the vacuous version of this test.
   *
   * TWO DOSSIERS, and neither alone is enough: the five collapsible sourcing sections only draw for a
   * component that HAS sourcing and the reveal control only for one that does not, which is the same
   * pair of renders the coverage gate needs for the same reason.
   *
   * FAILS IF: a manifest is registered with no binding (delete an entry from
   * `WORKSPACE_LAYOUT_BINDINGS`), a piece throws when its siblings are absent, or a piece reads the
   * region around it rather than the context it is handed.
   */
  it("draws each manifest's piece in isolation, without throwing", async () => {
    // Chrome output depends on the region chain and the dossier, never on which placement sits in the
    // innermost slot, so one baseline per (chain, dossier) is enough and each is computed at most once.
    const baselines = new Map<string, number>();
    const missing: string[] = [];

    for (const manifest of WORKSPACE_PIECES) {
      const document_ = isolatedDocument(manifest.id);
      // The spine is a valid document in its own right: no orphan slot, no unknown piece, no splitter
      // pointing at a slot that left with the siblings.
      expect(validateLayout(document_, WORKSPACE_PIECE_REGISTRY), manifest.id).toEqual([]);
      expect(layoutPlacements(document_).map((visit) => visit.node.piece)).toEqual([manifest.id]);

      const chain = regionChain(document_).join(">");
      let drawn = false;
      for (const [name, dossier] of [
        ["populated", populatedDossier()],
        ["sparse", sparseDossier()],
      ] as const) {
        const withPiece = elementsIn(await renderDocument(document_, dossier)).length;
        const key = `${chain}|${name}`;
        let chromeOnly = baselines.get(key);
        if (chromeOnly === undefined) {
          chromeOnly = elementsIn(
            await renderDocument(withPlacementHidden(document_), dossier),
          ).length;
          baselines.set(key, chromeOnly);
        }
        if (withPiece > chromeOnly) {
          drawn = true;
          break;
        }
      }
      if (!drawn) missing.push(manifest.id);
    }

    expect(missing).toEqual([]);
    // The floor: the loop really ran over the whole registry rather than an empty list.
    expect(WORKSPACE_PIECES.length).toBeGreaterThanOrEqual(20);
  }, 300_000);

  /**
   * The home hint is what auto-placement (plan decision 6) uses for a piece that arrives into a layout
   * nobody has placed it in, so it has to name a region the piece can actually be drawn inside.
   *
   * FAILS IF: a manifest's `home.regionId` names a region that is not on the piece's own spine - a hint
   * that would drop a sourcing section into the CAD column, where the chrome it needs cannot reach it.
   */
  it("homes every piece in a region the shipped document really puts it inside", () => {
    const wrong = WORKSPACE_PIECES.filter(
      (manifest) => !findRegion(isolatedDocument(manifest.id), manifest.home.regionId),
    ).map((manifest) => `${manifest.id}: ${manifest.home.regionId}`);
    expect(wrong).toEqual([]);
  });
});
