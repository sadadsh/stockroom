/**
 * ARRANGE, ON THE REAL WORKSPACE. The surface test next door proves the mechanism against three stub
 * pieces; this proves it against the pieces that ship, the real bindings, the real dev-mode draft and
 * the real column band - which is where the claims that matter are made:
 *
 *   ARRANGE OFF IS BYTE-ZERO, with dev mode ON. That is the hard regression gate of this phase, and
 *   `ComponentWorkspace.domParity.test.tsx` holds the same claim on the whole workspace with committed
 *   digests. What is added here is the round trip - on, then off again - because a surface that
 *   cleans up after itself is a different claim from one that never ran.
 *
 *   A HANDLE MOVES A REAL SECTION. The keyboard path against the sourcing column's own placements,
 *   read back off the DOM as well as off the document, so a move that edited the draft without
 *   reaching the screen fails.
 *
 *   THE COLUMN BOUNDARY EDITS THE DOCUMENT, NOT THE MACHINE. The same handle means two different
 *   things inside and outside arrange, and getting that backwards would either make a redesign a
 *   local preference or make one monitor everybody's layout. Both directions are asserted, including
 *   what is and is not written to storage.
 *
 *   UNDO SPANS IT. Plan 1.5 says structure and style are one history. 3A put the arrangement in the
 *   same draft as the tokens; this proves the stack really carries an arrangement edit, rather than
 *   assuming it because the slice is in the same object.
 *
 * NON-VACUITY, run for real and reverted: installing the placement chrome unconditionally in
 * `workspaceBindings.tsx` (`chrome={ArrangePlacementChrome}` rather than
 * `chrome={editMode ? ArrangePlacementChrome : null}`) failed "adds nothing while off" here AND all
 * four committed digests in `ComponentWorkspace.domParity.test.tsx`. That pair is the whole
 * regression gate of this phase: the same one-word change turns both red, so neither is standing in
 * for the other.
 *
 * The floor under every case here is that the column really drew - `drawnSections` is asserted
 * non-empty before anything is concluded from it - so a render that gave up fails rather than
 * passing a scan that found nothing wrong.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { api } from "../../api/client";
import { cadVariantApi } from "../../api/cadVariantClient";
import { DevModeProvider, useDevMode } from "../../lib/devMode";
import { ThemeProvider } from "../../lib/theme";
import { ToastProvider } from "../../lib/toast";
import { WORKSPACE_COLUMNS_STORAGE_KEY } from "../../lib/workspaceColumns";
import {
  DEFAULT_WORKSPACE_LAYOUT,
  workspaceColumnFractions,
} from "../../layout/defaultWorkspaceLayout";
import { findRegion, layoutPlacements, type LayoutDocument } from "../../layout/document";
import { resolveWorkspaceLayout } from "../../layout/resolveWorkspaceLayout";
import { WORKSPACE_REGION } from "../../layout/workspacePieces";
import { WorkspaceRegionView } from "../../layout/workspaceBindings";
import { sparseDossier } from "../component-workspace/workspaceDomFixtures";
import {
  WorkspaceColumnBand,
  type BandSlotContent,
} from "../component-workspace/WorkspaceColumns";
import { workspaceRenderFixture } from "../../test/workspaceRenderFixture";
import { ArrangeSurfaceProvider } from "./ArrangeSurface";

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
      previewSvg: vi.fn(),
      modelGlb: vi.fn(),
      landPattern: vi.fn(),
      refreshSourcing: vi.fn(),
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

const mockApi = vi.mocked(api);
const mockCadVariantApi = vi.mocked(cadVariantApi);

beforeEach(() => {
  window.localStorage.clear();
  mockApi.partHistory.mockResolvedValue({ commits: [], count: 0 });
  mockCadVariantApi.inventory.mockResolvedValue({
    partId: "lm358",
    inventories: [],
    pairs: [],
    supplementary: [],
  });
});

function provide(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <ToastProvider>
          <DevModeProvider>{ui}</DevModeProvider>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

/* -------------------------------------------------------------------------- */
/*  the sourcing column, with the switches beside it                           */
/* -------------------------------------------------------------------------- */

/** The placement ids of a region of the arrangement in force, in order. */
function regionOrder(document_: LayoutDocument, regionId: string): string {
  return layoutPlacements(document_)
    .filter((visit) => visit.parentRegionId === regionId)
    .map((visit) => visit.node.id)
    .join(" ");
}

function Column() {
  const dev = useDevMode();
  const layout = resolveWorkspaceLayout(dev.layoutDraft);
  return (
    <>
      <button data-testid="dev" onClick={dev.toggle} />
      <button data-testid="arrange" onClick={dev.toggleEditMode} />
      <button data-testid="undo" disabled={!dev.canUndo} onClick={dev.undo} />
      <button data-testid="redo" disabled={!dev.canRedo} onClick={dev.redo} />
      <output data-testid="edited">{String(dev.isLayoutEdited)}</output>
      <output data-testid="body-order">
        {regionOrder(layout, WORKSPACE_REGION.sourcingBody)}
      </output>
      <WorkspaceRegionView
        regionId={WORKSPACE_REGION.sourcingColumn}
        context={workspaceRenderFixture(sparseDossier(), { componentId: "lm358" })}
      />
    </>
  );
}

/**
 * Which sections the column really drew, top to bottom, by the dev id each one carries.
 *
 * Reads the scroller's direct child AND that child's own children, because in arrange mode the
 * direct child is the `display: contents` wrapper and the section is inside it. That the two cases
 * produce the same LIST is the point: the wrapper generates no box, so the reading order the browser
 * lays out is unchanged - all it does is add a name to the tree.
 */
function drawnSections(container: HTMLElement): string[] {
  return [...container.querySelectorAll<HTMLElement>("[data-workspace-scroll] > *")].flatMap(
    (node) => {
      const own = node.getAttribute("data-dev-id");
      if (own) return [own];
      return [...node.children].flatMap((child) => {
        const id = child.getAttribute("data-dev-id");
        return id ? [id] : [];
      });
    },
  );
}

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("arrange over the real sourcing column", () => {
  /**
   * FAILS IF: the chrome is installed while arrange is off, the provider leaves its stylesheet or a
   * listener behind after the switch goes off, or the wrapper changes the column's markup.
   *
   * Dev mode is ON throughout, which is the state the digests in
   * `ComponentWorkspace.domParity.test.tsx` are captured under - so this is the same claim, made
   * about the round trip rather than about one render.
   */
  it("adds nothing while off, and takes back everything it added", async () => {
    const view = provide(<Column />);
    await settle();
    fireEvent.click(screen.getByTestId("dev"));
    await settle();

    const before = view.container.innerHTML;
    expect(document.querySelectorAll("[data-arrange-placement]")).toHaveLength(0);
    expect(document.body.innerHTML).not.toContain("data-arrange-placement");
    // The floor: the column really drew, so "nothing was added" is about a real surface.
    expect(drawnSections(view.container).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByTestId("arrange"));
    await settle();
    expect(document.querySelectorAll("[data-arrange-handle]").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByTestId("arrange"));
    await settle();
    expect(view.container.innerHTML).toBe(before);
    expect(document.querySelectorAll("[data-arrange-placement]")).toHaveLength(0);
    expect(document.body.innerHTML).not.toContain("data-arrange-placement");
  }, 30_000);

  /**
   * FAILS IF: the handle's key press edits nothing, edits something the workspace does not draw
   * from, or the workspace keeps drawing the committed order after the draft changed.
   *
   * Both halves are asserted: the DOCUMENT order and the DRAWN order. A move that edited the draft
   * without reaching the screen is the failure this phase's whole resolution order exists to prevent.
   */
  it("moves a real section with the arrow keys, in the document and on the screen", async () => {
    const view = provide(<Column />);
    await settle();
    fireEvent.click(screen.getByTestId("dev"));
    fireEvent.click(screen.getByTestId("arrange"));
    await settle();

    const shipped = regionOrder(DEFAULT_WORKSPACE_LAYOUT, WORKSPACE_REGION.sourcingBody);
    expect(screen.getByTestId("body-order").textContent).toBe(shipped);
    expect(screen.getByTestId("edited").textContent).toBe("false");
    const drawnBefore = drawnSections(view.container);
    expect(drawnBefore[0]).toBe("component-browser.lifecycle");

    const handle = document.querySelector<HTMLElement>(
      '[data-arrange-handle="workspace.place.sourcing-lifecycle"]',
    );
    expect(handle).not.toBeNull();
    fireEvent.keyDown(handle!, { key: "ArrowDown" });
    await settle();

    expect(screen.getByTestId("edited").textContent).toBe("true");
    const moved = screen.getByTestId("body-order").textContent ?? "";
    expect(moved).not.toBe(shipped);
    expect(moved.split(" ")[1]).toBe("workspace.place.sourcing-lifecycle");

    // ONE step is a document change that this component nobody has sourced cannot SHOW, because the
    // sibling it swapped with is one of the five conditional sections and draws nothing here. So the
    // screen half of the claim is made by stepping it past every sibling: the section that opens the
    // column has to end up under the control that reveals the blank ones.
    for (let press = 1; press < shipped.split(" ").length; press += 1) {
      fireEvent.keyDown(
        document.querySelector('[data-arrange-handle="workspace.place.sourcing-lifecycle"]')!,
        { key: "ArrowDown" },
      );
    }
    await settle();
    const drawnAfter = drawnSections(view.container);
    expect(drawnAfter).not.toEqual(drawnBefore);
    expect(drawnAfter[drawnAfter.length - 1]).toBe("component-browser.lifecycle");
  }, 30_000);

  /**
   * PLAN 1.5: "undo/redo spans structure and style as one history". 3A put the arrangement into the
   * same draft the tokens live in; this is the proof that the stack really carries one, taken through
   * the same control the panel offers rather than by calling the reducer.
   *
   * FAILS IF: the layout slice stops being part of the history snapshot, or `resetLayoutDraft` and
   * undo disagree about what "no edit" is.
   */
  it("undoes and redoes an arrangement edit through the one shared history", async () => {
    provide(<Column />);
    await settle();
    fireEvent.click(screen.getByTestId("dev"));
    fireEvent.click(screen.getByTestId("arrange"));
    await settle();

    const shipped = screen.getByTestId("body-order").textContent;
    fireEvent.keyDown(
      document.querySelector('[data-arrange-handle="workspace.place.sourcing-lifecycle"]')!,
      { key: "ArrowDown" },
    );
    await settle();
    const edited = screen.getByTestId("body-order").textContent;
    expect(edited).not.toBe(shipped);

    fireEvent.click(screen.getByTestId("undo"));
    await settle();
    expect(screen.getByTestId("body-order").textContent).toBe(shipped);
    expect(screen.getByTestId("edited").textContent).toBe("false");

    fireEvent.click(screen.getByTestId("redo"));
    await settle();
    expect(screen.getByTestId("body-order").textContent).toBe(edited);
    expect(screen.getByTestId("edited").textContent).toBe("true");
  }, 30_000);
});

/* -------------------------------------------------------------------------- */
/*  the column boundary                                                        */
/* -------------------------------------------------------------------------- */

/** The band of the shipped document, with inert content in each column slot. */
function bandSlots(): BandSlotContent[] {
  const band = findRegion(DEFAULT_WORKSPACE_LAYOUT, WORKSPACE_REGION.columnBand);
  if (!band) throw new Error("the shipped document has no column band");
  return band.slots.map((slot) => ({ slot, content: null }));
}

function Band({ active }: { active: boolean }) {
  const [layout, setLayout] = useState<LayoutDocument>(DEFAULT_WORKSPACE_LAYOUT);
  const band = findRegion(layout, WORKSPACE_REGION.columnBand)!;
  const fractions = workspaceColumnFractions(layout);
  return (
    <ArrangeSurfaceProvider active={active} layout={layout} onLayout={setLayout}>
      <WorkspaceColumnBand region={band} slots={bandSlots()} />
      <output data-testid="fractions">
        {`${fractions.cad.toFixed(4)} ${fractions.specifications.toFixed(4)}`}
      </output>
    </ArrangeSurfaceProvider>
  );
}

function firstSplitter(): HTMLElement {
  const node = document.querySelector<HTMLElement>(
    '[data-dev-id="component-browser.column-splitter"]',
  );
  if (!node) throw new Error("the band drew no splitter");
  return node;
}

describe("a column boundary means two different things", () => {
  /**
   * OUTSIDE ARRANGE the boundary is a WORKSTATION preference, which is what it has always been.
   *
   * FAILS IF: the arrange path leaks into the ordinary one - the document is edited by a drag nobody
   * made in edit mode, or the stored preference stops being written.
   */
  it("outside arrange, remembers the position for this machine and leaves the document alone", () => {
    render(<Band active={false} />);
    const shipped = screen.getByTestId("fractions").textContent;
    fireEvent.keyDown(firstSplitter(), { key: "ArrowLeft" });
    expect(window.localStorage.getItem(WORKSPACE_COLUMNS_STORAGE_KEY)).not.toBeNull();
    expect(screen.getByTestId("fractions").textContent).toBe(shipped);
  });

  /**
   * INSIDE ARRANGE the same handle edits the DOCUMENT's fractions, which is what a committed
   * redesign ships to every machine.
   *
   * FAILS IF: the drag writes storage instead (a redesign that never leaves the monitor it was made
   * on), writes the document AND storage (one person's window silently becoming the design), or
   * writes the wrong pair of regions - a splitter is a zero-sum contract between exactly two
   * neighbours and the third column must not move.
   */
  it("inside arrange, edits the arrangement and writes nothing to this machine", () => {
    render(<Band active />);
    const shipped = workspaceColumnFractions(DEFAULT_WORKSPACE_LAYOUT);
    expect(screen.getByTestId("fractions").textContent).toBe(
      `${shipped.cad.toFixed(4)} ${shipped.specifications.toFixed(4)}`,
    );

    fireEvent.keyDown(firstSplitter(), { key: "ArrowLeft" });

    const [cad, specifications] = (screen.getByTestId("fractions").textContent ?? "")
      .split(" ")
      .map(Number);
    expect(cad).toBeLessThan(shipped.cad);
    expect(specifications).toBeGreaterThan(shipped.specifications);
    // Zero-sum: what one neighbour lost the other gained, to within the rounding of a pixel width.
    expect(cad + specifications).toBeCloseTo(shipped.cad + shipped.specifications, 3);
    expect(window.localStorage.getItem(WORKSPACE_COLUMNS_STORAGE_KEY)).toBeNull();
  });

  /**
   * FAILS IF: the shipped document is edited in place rather than a new one produced - which would
   * make one test's drag change the arrangement every later test starts from.
   */
  it("never edits the shipped document itself", () => {
    const before = workspaceColumnFractions(DEFAULT_WORKSPACE_LAYOUT);
    render(<Band active />);
    fireEvent.keyDown(firstSplitter(), { key: "ArrowLeft" });
    expect(workspaceColumnFractions(DEFAULT_WORKSPACE_LAYOUT)).toEqual(before);
  });
});
