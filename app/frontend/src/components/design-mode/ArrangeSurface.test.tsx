/**
 * THE EDITING SURFACE, against a document small enough to state in this file.
 *
 * The workspace integration lives next door in `ArrangeWorkspace.test.tsx`; this is the surface
 * itself - the wrapper, the handle, the drag, the keyboard path and the piece menu - rendered
 * through the REAL renderer, the REAL provider and the REAL chrome over three stub pieces. A tiny
 * document is the point rather than a shortcut: an arrangement claim asserted against the shipped
 * workspace is entangled with twenty-six components and four conditional sections, and the claim
 * being made here is about the surface.
 *
 * --- HOW A POINTER IS SIMULATED, and what that does and does not prove ---------------------------
 *
 * jsdom has no `PointerEvent`, so `fireEvent.pointerDown` constructs a bare `Event` and every
 * property a pointer handler reads - `button`, `clientX` - arrives `undefined`. A test written that
 * way would prove that a handler with no guards ran. So the events below are real `MouseEvent`s
 * dispatched under the pointer type names, which is what a browser delivers for a mouse: they carry
 * a real `button` and real coordinates, they bubble, and React's portal listener on `document.body`
 * receives them exactly as it would in the application.
 *
 * WHAT THAT STILL DOES NOT PROVE, stated plainly: no pixel is laid out in jsdom, so every rect is
 * zero and the drop position a real pointer would be OVER is not something this environment can
 * decide. What is proven is the whole of the rest - that pressing a handle opens the drop
 * positions, that releasing on one performs the move it advertises, and that the move performed is
 * the one `arrangeMoves` computes, whose ANSWERS are asserted in `arrangeMoves.test.ts` against
 * whole slot orders. The hit-testing between those two halves is the browser's.
 *
 * --- NON-VACUITY --------------------------------------------------------------------------------
 *
 * Each case names its killing mutation. Three were run against this file for real and reverted:
 *
 *   1. THE RENDERER STOPPED READING `collapsed`. Dropping `|| placement.collapsed` from
 *      `placementDraws` in `LayoutRenderer.tsx` failed two cases here - "collapses and hides one
 *      placement" and "draws neither a collapsed nor a hidden placement" - with the collapsed
 *      section still on the screen.
 *   2. THE DROP IGNORED WHICH SIDE IT LANDED ON. Making `DropPosition` pass a hard-coded `"before"`
 *      failed "performs that move on release", which lands the piece one slot above where it was
 *      released.
 *   3. THE STEP WENT NOWHERE. Handing `movePlacement` `seat.index` instead of `seat.index +
 *      direction` in `stepPlacement` failed "steps the placement one position" and "steps and
 *      re-homes a placement from the menu alone" - and the same mutation failed
 *      `arrangeMoves.test.ts` next door, which is the point of the two files sharing one module.
 *
 * The fourth mutation - installing the placement chrome regardless of the switch - belongs to
 * `ArrangeWorkspace.test.tsx`, where it also turns four committed DOM-parity digests red.
 */
import { describe, it, expect } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import type {
  LayoutDocument,
  LayoutRegion,
  LayoutSlot,
  PiecePlacement,
} from "../../layout/document";
import { layoutPlacements } from "../../layout/document";
import {
  LayoutDocumentView,
  LayoutPlacementChromeProvider,
  type LayoutBindings,
  type PiecePartProps,
} from "../../layout/LayoutRenderer";
import { ArrangePlacementChrome, ArrangePreferencesProvider, ArrangeSurfaceProvider } from "./ArrangeSurface";
import { RESPONSIVE_VIEWPORT_PRESETS } from "../../design-studio/responsiveViewports";

/* -------------------------------------------------------------------------- */
/*  a document, and three pieces to put in it                                  */
/* -------------------------------------------------------------------------- */

function place(id: string, piece: string, over: Partial<PiecePlacement> = {}): PiecePlacement {
  return { kind: "placement", id, piece, ...over };
}

function slot(id: string, content: LayoutRegion | PiecePlacement): LayoutSlot {
  return { kind: "slot", id, content };
}

/**
 * A section shaped like the real ones: a bordered block carrying `last:border-b-0`, which is the one
 * utility the `display: contents` wrapper displaces and which the arrange stylesheet restores.
 */
function stubPart(name: string) {
  return function StubPart({ placement }: PiecePartProps) {
    return (
      <section
        data-testid={`part-${name}`}
        data-placement={placement.id}
        className="border-b border-line last:border-b-0"
      >
        {name}
      </section>
    );
  };
}

const BINDINGS: LayoutBindings = {
  pieces: {
    "piece.alpha": stubPart("alpha"),
    "piece.beta": stubPart("beta"),
    "piece.gamma": stubPart("gamma"),
  },
  chrome: {},
};

function baseDocument(over: Partial<Record<"alpha" | "beta" | "gamma", Partial<PiecePlacement>>> = {}): LayoutDocument {
  return {
    schemaVersion: 1,
    id: "test.arrange",
    root: {
      kind: "region",
      id: "root",
      mode: "row",
      slots: [
        slot("slot.left", {
          kind: "region",
          id: "left",
          mode: "column",
          slots: [
            slot("slot.alpha", place("alpha", "piece.alpha", over.alpha)),
            slot("slot.beta", place("beta", "piece.beta", over.beta)),
          ],
        }),
        slot("slot.right", {
          kind: "region",
          id: "right",
          mode: "column",
          slots: [slot("slot.gamma", place("gamma", "piece.gamma", over.gamma))],
        }),
      ],
    },
  };
}

/** The placement ids of a region, in order - the whole of what a move is judged on. */
function order(document_: LayoutDocument, regionId: string): string[] {
  return layoutPlacements(document_)
    .filter((visit) => visit.parentRegionId === regionId)
    .map((visit) => visit.node.id);
}

/* -------------------------------------------------------------------------- */
/*  the harness                                                                */
/* -------------------------------------------------------------------------- */

/**
 * The surface, holding the document the way the application does: one value in, one whole document
 * out. The current order is printed into the tree so a case reads the ARRANGEMENT back rather than
 * inferring it from what happens to be on screen.
 */
function Surface({
  active,
  start = baseDocument(),
  snap = true,
  gridSize = 8,
}: {
  active: boolean;
  start?: LayoutDocument;
  snap?: boolean;
  gridSize?: number;
}) {
  const [document_, setDocument] = useState(start);
  return (
    <ArrangePreferencesProvider snap={snap} gridSize={gridSize}>
    <ArrangeSurfaceProvider active={active} layout={document_} onLayout={setDocument}>
      <LayoutPlacementChromeProvider chrome={active ? ArrangePlacementChrome : null}>
        <LayoutDocumentView document={document_} bindings={BINDINGS} />
      </LayoutPlacementChromeProvider>
      <output data-testid="left-order">{order(document_, "left").join(" ")}</output>
      <output data-testid="right-order">{order(document_, "right").join(" ")}</output>
      <output data-testid="settings">
        {layoutPlacements(document_)
          .map(
            (visit) =>
              `${visit.node.id}:${visit.node.collapsed === true ? "c" : "-"}${
                visit.node.hidden === true ? "h" : "-"
              }`,
          )
          .join(" ")}
      </output>
      <output data-testid="roles">
        {layoutPlacements(document_)
          .filter((visit) => visit.node.styleRoles !== undefined)
          .map((visit) => `${visit.node.id}:${JSON.stringify(visit.node.styleRoles)}`)
          .join(" ")}
      </output>
      <output data-testid="sizes">
        {layoutPlacements(document_)
          .map((visit) => `${visit.node.id}:${visit.node.size?.width ?? "-"}`)
          .join(" ")}
      </output>
      <output data-testid="positions">
        {layoutPlacements(document_)
          .map((visit) => `${visit.node.id}:${visit.node.position?.x ?? "-"},${visit.node.position?.y ?? "-"}`)
          .join(" ")}
      </output>
    </ArrangeSurfaceProvider>
    </ArrangePreferencesProvider>
  );
}

/** A real mouse event under a pointer type name - see the file header for why not `fireEvent.pointerDown`. */
function pointer(node: Node | Window, type: string, init: MouseEventInit = {}): void {
  fireEvent(
    node,
    new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, ...init }),
  );
}

function handleFor(placementId: string): HTMLElement {
  const node = document.querySelector<HTMLElement>(`[data-arrange-handle="${placementId}"]`);
  if (!node) throw new Error(`no arrange handle for ${placementId}`);
  return node;
}

function handles(): string[] {
  return [...document.querySelectorAll<HTMLElement>("[data-arrange-handle]")].map(
    (node) => node.dataset.arrangeHandle ?? "",
  );
}

/* -------------------------------------------------------------------------- */
/*  1. arrange off                                                             */
/* -------------------------------------------------------------------------- */

describe("arrange off", () => {
  /**
   * THE REGRESSION GATE OF THIS PHASE, in miniature. The workspace's own digests
   * (`ComponentWorkspace.domParity.test.tsx`) hold the same claim against the real arrangement; this
   * holds it against the mechanism, which is where it can be read.
   *
   * FAILS IF: the placement chrome is installed regardless of the switch, the surface renders
   * anything into the page while inactive, or the provider leaves a listener or a stylesheet behind
   * (the stylesheet names `data-arrange-placement`, so it is caught by the same scan).
   */
  it("leaves the DOM exactly as it found it", () => {
    const off = render(<Surface active={false} />);
    const before = off.container.innerHTML;
    expect(document.querySelectorAll("[data-arrange-placement]")).toHaveLength(0);
    expect(document.querySelectorAll("[data-arrange-handle]")).toHaveLength(0);
    expect(document.body.innerHTML).not.toContain("data-arrange-placement");
    off.unmount();

    // The same tree with the switch on, and then off again: the pieces' own markup is untouched
    // throughout, and the wrapper is gone the moment it is not needed.
    const on = render(<Surface active />);
    expect(document.querySelectorAll("[data-arrange-placement]").length).toBeGreaterThan(0);
    expect(within(on.container).getByTestId("part-alpha").className).toBe(
      "border-b border-line last:border-b-0",
    );
    on.unmount();

    const again = render(<Surface active={false} />);
    expect(again.container.innerHTML).toBe(before);
  });
});

/* -------------------------------------------------------------------------- */
/*  2. a handle per placement                                                  */
/* -------------------------------------------------------------------------- */

describe("arrange on", () => {
  it("defines the exact responsive desktop presets and a custom width", () => {
    expect(RESPONSIVE_VIEWPORT_PRESETS).toEqual([
      { id: "desktop-1366", label: "1366 px", width: 1366 },
      { id: "desktop-1600", label: "1600 px", width: 1600 },
      { id: "desktop-1920", label: "1920 px", width: 1920 },
      { id: "custom", label: "Custom", width: null },
    ]);
  });

  /**
   * FAILS IF: the wrapper stops being `display: contents` (which would give the piece a box of its
   * own and change every flex layout it sits in), the handle is drawn inside the piece's subtree
   * rather than in a portal, or a placement loses its handle.
   */
  it("names every drawn placement without touching its subtree", () => {
    const view = render(<Surface active />);
    expect(handles().sort()).toEqual(["alpha", "beta", "gamma"]);

    for (const name of ["alpha", "beta", "gamma"]) {
      const part = screen.getByTestId(`part-${name}`);
      const wrapper = part.parentElement;
      expect(wrapper?.getAttribute("data-arrange-placement")).toBe(name);
      expect(wrapper?.style.display).toBe("contents");
      // The affordance is a portal at the body, so nothing was added inside the piece.
      expect(part.querySelectorAll("[data-dev-id]")).toHaveLength(0);
      expect(view.container.contains(handleFor(name))).toBe(false);
    }
    // The one declaration the wrapper displaces is put back by the surface's own stylesheet.
    expect(document.body.textContent).toContain("border-bottom-width:1px");
  });

  /**
   * A hidden or collapsed placement draws nothing, so there is nothing for a handle to sit on and
   * none is offered - which is exactly why the panel carries the list that puts one back.
   *
   * FAILS IF: the chrome is applied before the draw decision, which would hang a handle over a
   * placement with no pixels anywhere on the page.
   */
  it("offers no handle for a placement that is not drawn", () => {
    render(<Surface active start={baseDocument({ beta: { hidden: true } })} />);
    expect(handles().sort()).toEqual(["alpha", "gamma"]);
    expect(screen.queryByTestId("part-beta")).toBeNull();
  });
});

describe("direct resize parity", () => {
  it("snaps the same placement resize from keyboard and pointer without rebinding it", () => {
    render(<Surface active start={baseDocument({ alpha: { size: { width: 480 } } })} />);
    const resize = document.querySelector<HTMLElement>('[data-arrange-resize="alpha"]')!;

    fireEvent.keyDown(resize, { key: "ArrowRight" });
    expect(screen.getByTestId("sizes")).toHaveTextContent("alpha:488");

    pointer(resize, "pointerdown", { clientX: 488 });
    pointer(window, "pointerup", { clientX: 503 });
    expect(screen.getByTestId("sizes")).toHaveTextContent("alpha:504");
    expect(screen.getByTestId("part-alpha")).toHaveAttribute("data-placement", "alpha");
  });

  it("uses single-pixel movement when shell snap is off", () => {
    render(<Surface active snap={false} start={baseDocument({ alpha: { size: { width: 480 } } })} />);
    fireEvent.keyDown(document.querySelector('[data-arrange-resize="alpha"]')!, { key: "ArrowRight" });
    expect(screen.getByTestId("sizes")).toHaveTextContent("alpha:481");
  });

  it("uses the selected shell grid size when snap is on", () => {
    render(<Surface active gridSize={12} start={baseDocument({ alpha: { size: { width: 480 } } })} />);
    fireEvent.keyDown(document.querySelector('[data-arrange-resize="alpha"]')!, { key: "ArrowRight" });
    expect(screen.getByTestId("sizes")).toHaveTextContent("alpha:492");
  });
});

/* -------------------------------------------------------------------------- */
/*  3. the keyboard path                                                       */
/* -------------------------------------------------------------------------- */

describe("a handle answers the arrow keys", () => {
  /**
   * A POINTER-ONLY EDITOR FAILS THIS REPOSITORY'S STANDARD, so the step is a real key press on a
   * real focusable control, not a call to the function behind it.
   *
   * FAILS IF: the handle stops being a focusable control, the arrow keys stop being bound, or the
   * step is computed in the wrong direction.
   */
  it("steps the placement one position, and stops at the ends", () => {
    render(<Surface active />);
    const handle = handleFor("alpha");
    handle.focus();
    expect(document.activeElement).toBe(handle);

    expect(screen.getByTestId("left-order").textContent).toBe("alpha beta");
    fireEvent.keyDown(handleFor("alpha"), { key: "ArrowDown" });
    expect(screen.getByTestId("left-order").textContent).toBe("beta alpha");
    fireEvent.keyDown(handleFor("alpha"), { key: "ArrowDown" });
    // Already last: nothing moves, and nothing throws.
    expect(screen.getByTestId("left-order").textContent).toBe("beta alpha");
    fireEvent.keyDown(handleFor("alpha"), { key: "ArrowUp" });
    expect(screen.getByTestId("left-order").textContent).toBe("alpha beta");
    // A key the surface does not claim is left to the page.
    fireEvent.keyDown(handleFor("alpha"), { key: "ArrowRight" });
    expect(screen.getByTestId("left-order").textContent).toBe("alpha beta");
  });

  it("opens the piece menu on Enter, so the cross-region move needs no pointer", () => {
    render(<Surface active />);
    fireEvent.keyDown(handleFor("alpha"), { key: "Enter" });
    const menu = document.querySelector<HTMLElement>('[data-dev-id="design.piece-menu"]');
    expect(menu).not.toBeNull();
    expect(menu?.textContent).toContain("alpha");
    expect(menu?.textContent).toContain("piece.alpha");
    // Every region of the document is offered, including the two the placement is not in. Scoped to
    // the region picker rather than to the whole menu, because the menu also carries the two text
    // role pickers and their options are a different vocabulary entirely.
    const picker = menu?.querySelector('[data-dev-id="design.piece-move-into"]');
    const options = [...(picker?.querySelectorAll("option") ?? [])].map((node) => node.value);
    expect(options).toEqual(["root", "left", "right"]);
  });
});

/* -------------------------------------------------------------------------- */
/*  4. the pointer path                                                        */
/* -------------------------------------------------------------------------- */

describe("dragging a handle", () => {
  /**
   * FAILS IF: pressing a handle does not start a drag, the drop positions are drawn when nothing is
   * being dragged (they cover the application when they are), or the dragged placement offers a
   * position to drop itself on.
   */
  it("opens a drop position above and below every other placement, and only then", () => {
    render(<Surface active />);
    expect(document.querySelectorAll('[data-dev-id="design.drop-target"]')).toHaveLength(0);

    pointer(handleFor("alpha"), "pointerdown");
    const targets = [...document.querySelectorAll<HTMLElement>('[data-dev-id="design.drop-target"]')];
    expect(
      targets.map((node) => `${node.dataset.arrangeAnchor}:${node.dataset.arrangeDrop}`).sort(),
    ).toEqual(["beta:after", "beta:before", "gamma:after", "gamma:before"]);
  });

  /**
   * FAILS IF: the drop reads the wrong side, drops onto the wrong region, or the release does not
   * end the drag. PROVEN by hard-coding `"before"` in `DropPosition`; reverted.
   */
  it("performs that move on release, and ends the drag", () => {
    render(<Surface active />);
    pointer(handleFor("alpha"), "pointerdown");
    const target = document.querySelector<HTMLElement>(
      '[data-arrange-anchor="gamma"][data-arrange-drop="after"]',
    );
    expect(target).not.toBeNull();
    pointer(target!, "pointerup");

    expect(screen.getByTestId("left-order").textContent).toBe("beta");
    expect(screen.getByTestId("right-order").textContent).toBe("gamma alpha");
    expect(document.querySelectorAll('[data-dev-id="design.drop-target"]')).toHaveLength(0);
  });

  it("releasing on nothing leaves the arrangement alone", () => {
    render(<Surface active />);
    pointer(handleFor("alpha"), "pointerdown");
    pointer(document.body, "pointerup");
    expect(document.querySelectorAll('[data-dev-id="design.drop-target"]')).toHaveLength(0);
    expect(screen.getByTestId("left-order").textContent).toBe("alpha beta");
  });
});

/* -------------------------------------------------------------------------- */
/*  5. the piece menu                                                          */
/* -------------------------------------------------------------------------- */

describe("right-clicking a placement", () => {
  /**
   * The delegation is what makes this work on the piece ITSELF rather than only on its handle, which
   * is what plan 1.5 asks for.
   *
   * FAILS IF: the capture listener is not installed, is bound to the handle rather than to the
   * document, or does not swallow the browser's own menu.
   */
  it("opens the piece menu over the piece, and names what it is about", () => {
    render(<Surface active />);
    const opened = fireEvent.contextMenu(screen.getByTestId("part-beta"), {
      clientX: 40,
      clientY: 90,
    });
    // `fireEvent` returns false when the handler called `preventDefault`, which is how the native
    // menu is kept from covering this one.
    expect(opened).toBe(false);
    const menu = document.querySelector<HTMLElement>('[data-dev-id="design.piece-menu"]');
    expect(menu?.style.left).toBe("40px");
    expect(menu?.style.top).toBe("90px");
    expect(
      menu?.querySelector('[data-dev-id="design.piece-name"]')?.textContent,
    ).toContain("beta");
  });

  /**
   * FAILS IF: either setting is written to the wrong key, or the renderer draws a piece the document
   * says is off. PROVEN by dropping `|| placement.collapsed` from `placementDraws`; reverted.
   *
   * The two settings are asserted SEPARATELY even though both currently draw nothing, because they
   * are different facts about the document and only one of them is meant to grow a header the day a
   * piece declares separable chrome.
   */
  it("collapses and hides one placement, each recorded on its own key", () => {
    render(<Surface active />);
    fireEvent.contextMenu(screen.getByTestId("part-beta"));
    fireEvent.click(document.querySelector('[data-dev-id="design.piece-collapse"]')!);
    expect(screen.getByTestId("settings").textContent).toBe("alpha:-- beta:c- gamma:--");
    expect(screen.queryByTestId("part-beta")).toBeNull();
    expect(screen.getByTestId("part-alpha")).toBeTruthy();

    // The same control expands it again, from the panel's point of view as much as the menu's.
    fireEvent.contextMenu(screen.getByTestId("part-alpha"));
    fireEvent.click(document.querySelector('[data-dev-id="design.piece-hide"]')!);
    expect(screen.getByTestId("settings").textContent).toBe("alpha:-h beta:c- gamma:--");
    expect(screen.queryByTestId("part-alpha")).toBeNull();
  });

  /**
   * FAILS IF: the menu's step controls disagree with the keyboard path, or are offered where the
   * step is not available - a control that does nothing is worse than one that is not there.
   */
  it("steps and re-homes a placement from the menu alone", () => {
    render(<Surface active />);
    fireEvent.contextMenu(screen.getByTestId("part-alpha"));
    expect(
      document.querySelector<HTMLButtonElement>('[data-dev-id="design.piece-move-up"]')?.disabled,
    ).toBe(true);
    fireEvent.click(document.querySelector('[data-dev-id="design.piece-move-down"]')!);
    expect(screen.getByTestId("left-order").textContent).toBe("beta alpha");

    fireEvent.change(document.querySelector('[data-dev-id="design.piece-move-into"]')!, {
      target: { value: "right" },
    });
    expect(screen.getByTestId("left-order").textContent).toBe("beta");
    expect(screen.getByTestId("right-order").textContent).toBe("gamma alpha");
  });

  /**
   * THE NARROW STYLE SCOPE (plan 1.5): "only here", written on the placement the menu was opened on
   * and on no other. The wide scope is the Tokens rows and the Box tab and is not touched here.
   *
   * FAILS IF: the control writes the role on the wrong placement (the exception would reach a
   * sibling, which is the one thing "only here" promises it does not), writes the pair the wrong way
   * round, or leaves the entry behind when the owner picks the shipped role back. The last of those
   * is what makes the exception UNTRACKABLE rather than merely stale: `validateDocument` derives its
   * `style-role-exception` row from the document, so an entry that will not go is a note that will
   * not go either.
   */
  it("scopes a text role to the placement the menu was opened on, and drops it again", () => {
    render(<Surface active />);
    fireEvent.contextMenu(screen.getByTestId("part-beta"));

    // Which role is being overridden, then what it becomes here.
    fireEvent.change(document.querySelector('[data-dev-id="design.piece-text-role"]')!, {
      target: { value: "sectionTitle" },
    });
    fireEvent.change(document.querySelector('[data-dev-id="design.piece-text-role-here"]')!, {
      target: { value: "sourceText" },
    });
    expect(screen.getByTestId("roles").textContent).toBe('beta:{"sectionTitle":"sourceText"}');

    // A second role on the same placement joins the first rather than replacing it.
    fireEvent.change(document.querySelector('[data-dev-id="design.piece-text-role"]')!, {
      target: { value: "rowMetadata" },
    });
    // The second control shows the ABSENCE of an exception for the newly-picked role, which is what
    // makes it readable as "what does this placement do with that role" rather than as a last edit.
    expect(
      document.querySelector<HTMLSelectElement>('[data-dev-id="design.piece-text-role-here"]')?.value,
    ).toBe("");
    fireEvent.change(document.querySelector('[data-dev-id="design.piece-text-role-here"]')!, {
      target: { value: "machineText" },
    });
    expect(screen.getByTestId("roles").textContent).toBe(
      'beta:{"sectionTitle":"sourceText","rowMetadata":"machineText"}',
    );

    // Back to what the piece ships with: the entry goes, and when the last one goes the key goes.
    fireEvent.change(document.querySelector('[data-dev-id="design.piece-text-role-here"]')!, {
      target: { value: "" },
    });
    fireEvent.change(document.querySelector('[data-dev-id="design.piece-text-role"]')!, {
      target: { value: "sectionTitle" },
    });
    fireEvent.change(document.querySelector('[data-dev-id="design.piece-text-role-here"]')!, {
      target: { value: "" },
    });
    expect(screen.getByTestId("roles").textContent).toBe("");
  });

  it("closes on Escape without changing anything", () => {
    render(<Surface active />);
    fireEvent.contextMenu(screen.getByTestId("part-beta"));
    expect(document.querySelector('[data-dev-id="design.piece-menu"]')).not.toBeNull();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(document.querySelector('[data-dev-id="design.piece-menu"]')).toBeNull();
    expect(screen.getByTestId("left-order").textContent).toBe("alpha beta");
  });

  it("restores direct arrangement overrides from the keyboard-reachable piece menu", () => {
    render(<Surface active start={baseDocument({ alpha: { size: { width: 480 } } })} />);
    fireEvent.contextMenu(screen.getByTestId("part-alpha"), { clientX: 10, clientY: 12 });
    const restore = document.querySelector<HTMLButtonElement>('[data-dev-id="design.piece-restore"]');
    expect(restore).not.toBeNull();
    restore?.focus();
    expect(restore).toHaveFocus();
    fireEvent.click(restore!);
    expect(screen.getByTestId("sizes")).toHaveTextContent("alpha:-");
  });

  it("uses a visual slider for free positioning", () => {
    const start = baseDocument({ alpha: { position: { x: 16, y: 24 } } });
    const left = start.root.slots[0]?.content as LayoutRegion;
    left.positioning = "free";
    render(<Surface active start={start} />);
    fireEvent.contextMenu(screen.getByTestId("part-alpha"));
    const position = screen.getByLabelText("Position X");
    expect(position).toHaveAttribute("type", "range");
    fireEvent.change(position, { target: { value: "32" } });
    expect(screen.getByTestId("positions")).toHaveTextContent("alpha:32,24");
  });
});

/* -------------------------------------------------------------------------- */
/*  6. the settings the renderer reads, with no editor involved                */
/* -------------------------------------------------------------------------- */

describe("the renderer's own reading of the per-placement settings", () => {
  /**
   * THE PARITY HALF of the collapse work: a document that sets NEITHER setting must render exactly
   * what it rendered before the renderer learned to read them. Asserted as bytes, because that is
   * the claim - the shipped document sets neither, so this is the code path the application takes.
   *
   * FAILS IF: `placementDraws` starts treating an absent setting as `false`-ish in some way that
   * changes what is drawn, or the chrome seam alters the tree when no chrome is installed.
   */
  it("draws a document with no settings exactly as it did before it could read them", () => {
    const plain = render(
      <LayoutDocumentView document={baseDocument()} bindings={BINDINGS} />,
    );
    const expected = plain.container.innerHTML;
    plain.unmount();

    // Through the chrome seam with no chrome installed: the same bytes.
    const seamed = render(
      <LayoutPlacementChromeProvider chrome={null}>
        <LayoutDocumentView document={baseDocument()} bindings={BINDINGS} />
      </LayoutPlacementChromeProvider>,
    );
    expect(seamed.container.innerHTML).toBe(expected);
    expect(expected).toContain("part-alpha");
  });

  it("draws neither a collapsed nor a hidden placement, and draws the rest", () => {
    render(
      <LayoutDocumentView
        document={baseDocument({ alpha: { collapsed: true }, gamma: { hidden: true } })}
        bindings={BINDINGS}
      />,
    );
    expect(screen.queryByTestId("part-alpha")).toBeNull();
    expect(screen.queryByTestId("part-gamma")).toBeNull();
    expect(screen.getByTestId("part-beta")).toBeTruthy();
  });
});
