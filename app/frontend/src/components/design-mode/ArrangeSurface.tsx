/**
 * ARRANGE MODE: the running application, with handles on it.
 *
 * Plan decision 5 - "the real app is the canvas" - taken literally. There is no design canvas, no
 * preview and no second render of the workspace: this file hangs an editing affordance off the
 * pieces that are already on the screen, so what the owner drags is the actual Documents section
 * showing the actual documents of the component they actually have open.
 *
 * ------------------------------------------------------------------------------------------------
 * HOW A HANDLE FINDS A PIECE WITHOUT RESTRUCTURING IT - the central design decision.
 *
 * A handle has to be drawn over a placement, so something has to know where that placement's pixels
 * are. Three ways were available and two of them are wrong:
 *
 *   PUT THE HANDLE INSIDE THE PIECE. Rejected: it makes the piece's own DOM subtree different in
 *   edit mode from what ships, which is exactly the claim decision 5 rests on. A section with an
 *   extra child is not the section.
 *
 *   FIND THE PIECE BY ITS DEV IDS. Rejected: it very nearly works - every manifest lists the
 *   `data-dev-id`s its piece renders - and it fails on the cases that matter most. The three CAD
 *   modules are three PLACEMENTS of one piece and carry the same ids, a repeated placement draws one
 *   subtree per row, and `workspace.specifications-empty` declares no dev id at all. A handle that
 *   cannot address one of three identical modules cannot move one of them.
 *
 *   WHAT IS DONE. Each drawn placement is wrapped in a `display: contents` box carrying
 *   `data-arrange-placement`. `display: contents` GENERATES NO BOX: the piece's own elements remain
 *   direct participants in the parent's flex or block layout, at the same sizes, in the same order,
 *   with the same margins. Nothing is nested, nothing is repositioned, and the piece's subtree is
 *   byte-identical. The wrapper is a NAME, not a container - it exists to be a ref - and the handle
 *   itself is drawn in a portal to `document.body`, over the measured union of the wrapper's
 *   children, exactly as `DevInspector` draws its hover outline and its id badges.
 *
 *   THE ONE THING `display: contents` DOES CHANGE, stated rather than hidden: structural
 *   pseudo-classes. The wrapper is a real element in the tree, so a piece root that used to be its
 *   region's `:last-child` becomes the only child of its own wrapper and matches `:last-child`
 *   always. In this arrangement exactly one utility depends on that - `last:border-b-0`, which
 *   removes the hairline under the final section of a column - and it would silently remove EVERY
 *   section hairline in edit mode. `ARRANGE_STYLESHEET` below restores precisely that declaration
 *   for a wrapper that still has a drawn sibling after it, so the canvas keeps the borders the
 *   shipped app has. It is scoped by the `data-arrange-placement` attribute, which exists only while
 *   arrange is on.
 *
 * ------------------------------------------------------------------------------------------------
 * THREE WAYS TO MAKE THE SAME MOVE, because a pointer-only editor is an editor half the people who
 * need it cannot use. All three call the same pure functions in `arrangeMoves.ts`:
 *
 *   POINTER. Press a handle, and every OTHER placement on screen offers two drop positions - above
 *   it and below it. Release over one. Legal positions are highlighted, and every position is legal:
 *   the model places no restriction on which region a piece may sit in, so the validator reports
 *   what an odd arrangement costs and nothing refuses it (decision 3).
 *
 *   KEYBOARD. A focused handle answers Arrow Up and Arrow Down by stepping the placement one
 *   position inside its own region, and Enter or Space by opening the piece menu - which carries the
 *   step controls AND a list of every region in the document, so the cross-region move a drag makes
 *   is reachable without a pointer.
 *
 *   RIGHT-CLICK. A capture-phase `contextmenu` listener - the same delegation `DevInspector` uses
 *   for its inspect click, and for the same reason: 25 placements should not mean 25 React handlers
 *   bound to elements this module does not own. It opens the piece menu for whichever placement the
 *   pointer is inside.
 *
 * ARRANGE OFF IS NOTHING AT ALL. No wrapper, no listener, no portal, no stylesheet - the chrome is
 * simply not installed into the renderer, which is why the DOM-parity digests are untouched.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { useText } from "../../lib/copy";
import { DEV_ID_BY_ID } from "../../lib/devIds";
import {
  WORKSPACE_COLUMN_IDS,
  type StoredColumnFractions,
  type WorkspaceColumnWidths,
} from "../../lib/workspaceColumns";
import {
  WORKSPACE_CONDITION,
  WORKSPACE_COLUMN_REGION,
  workspaceColumnFractions,
} from "../../layout/defaultWorkspaceLayout";
import type { LayoutDocument } from "../../layout/document";
import {
  setPlacementCollapsed,
  setPlacementHidden,
  setRegionSize,
} from "../../layout/editOperations";
import type { PlacementChromeProps } from "../../layout/LayoutRenderer";
import { WORKSPACE_PIECE_REGISTRY } from "../../layout/workspacePieces";
import {
  arrangeRegionChoices,
  canStepPlacement,
  dropPlacement,
  movePlacementIntoRegion,
  placementSeat,
  stepPlacement,
  type DropSide,
  type StepDirection,
} from "./arrangeMoves";

/* -------------------------------------------------------------------------- */
/*  the surface                                                                */
/* -------------------------------------------------------------------------- */

/** The wrapper's whole style. A box that generates no box - see the file header. */
const CONTENTS: CSSProperties = { display: "contents" };

/**
 * The one declaration the wrapper displaces, put back.
 *
 * `last:border-b-0` compiles to `.last\:border-b-0:last-child { border-bottom-width: 0 }`, and a
 * wrapped piece root is always its wrapper's last child. This restores the 1px the utility removed,
 * for a piece whose wrapper is still followed by a wrapper that DREW something - which is the
 * original meaning of "not the last section". The border COLOUR is untouched: it comes from the
 * element's own `border-line` class, which the wrapper never affected.
 *
 * `:has()` rather than `:not(:last-child)` because a placement whose piece component returns nothing
 * still leaves an empty wrapper behind, and counting one of those as a following section would draw
 * a hairline under the last visible one. A browser without `:has()` loses the compensation and gets
 * a column with no section rules while arrange is on; it loses nothing outside arrange.
 */
const ARRANGE_STYLESHEET =
  '[data-arrange-placement]:has(~ [data-arrange-placement] > *) > [class~="last:border-b-0"]' +
  "{border-bottom-width:1px}";

interface ArrangeMenuState {
  placementId: string;
  /** Viewport coordinates the menu opens at: the pointer, or the handle it was opened from. */
  x: number;
  y: number;
}

interface ArrangeSurfaceValue {
  /** The arrangement in force, which is the one every gesture edits. */
  layout: LayoutDocument;
  /** Write the whole next document into the working draft. */
  edit: (next: LayoutDocument) => void;
  dragging: string | null;
  beginDrag: (placementId: string) => void;
  endDrag: () => void;
  menu: ArrangeMenuState | null;
  openMenu: (next: ArrangeMenuState | null) => void;
  /** Bumped when everything on screen has to be measured again. */
  tick: number;
}

const ArrangeSurfaceContext = createContext<ArrangeSurfaceValue | null>(null);

/** The arrange surface, or `null` when arrange is off. Everything here degrades to nothing on null. */
export function useArrangeSurface(): ArrangeSurfaceValue | null {
  return useContext(ArrangeSurfaceContext);
}

/**
 * The piece's name for a person, taken from the id catalogue rather than authored here.
 *
 * A manifest names a piece as a COPY ID (`nameCopyId`) and not every piece has one, so the reliable
 * human name is the label of the first `data-dev-id` the piece declares - which `lib/devIds.ts`
 * already holds for every one of them. That is a catalogue lookup over data, in the same class as a
 * provider label, which is why it is not authored through the copy layer at this call site. The
 * piece id is shown beside it verbatim, so the name is context and never a substitute.
 *
 * Reads the WORKSPACE registry, which is the one editable surface this phase ships (plan Phase 6 and
 * 7 bring the shell and the remaining routes, and this lookup is what they will have to generalise).
 */
function pieceDisplayName(pieceId: string): string {
  const devId = WORKSPACE_PIECE_REGISTRY.get(pieceId)?.devIds[0];
  return (devId ? DEV_ID_BY_ID.get(devId)?.label : undefined) ?? pieceId;
}

export function ArrangeSurfaceProvider({
  active,
  layout,
  onLayout,
  children,
}: {
  active: boolean;
  layout: LayoutDocument;
  onLayout: (next: LayoutDocument) => void;
  children: ReactNode;
}) {
  const [dragging, setDragging] = useState<string | null>(null);
  const [menu, setMenu] = useState<ArrangeMenuState | null>(null);
  const [tick, setTick] = useState(0);

  const beginDrag = useCallback((placementId: string) => setDragging(placementId), []);
  const endDrag = useCallback(() => setDragging(null), []);
  const openMenu = useCallback((next: ArrangeMenuState | null) => setMenu(next), []);

  const edit = useCallback(
    (next: LayoutDocument) => {
      // A gesture that could not mean anything hands back the document it was given, BY REFERENCE
      // (`arrangeMoves` and `editOperations` both promise that), so comparing here is what keeps a
      // refused move out of the undo history entirely.
      if (next !== layout) onLayout(next);
    },
    [layout, onLayout],
  );

  // Everything is measured off the live DOM, so anything that moves the page has to say so. A
  // re-render remeasures by itself (the chrome's layout effect runs every time); these are the two
  // events that move pixels WITHOUT one.
  //
  // THE CLEANUP ALSO ENDS ANY GESTURE, which is where that belongs rather than in an effect of its
  // own watching the switch: a drag or an open menu is part of the arrange SESSION, so it goes when
  // the session does - whether that is the switch going off or the surface unmounting - and it can
  // never be restored by switching arrange back on.
  useEffect(() => {
    if (!active) return;
    const bump = () => setTick((value) => value + 1);
    window.addEventListener("resize", bump);
    window.addEventListener("scroll", bump, true);
    return () => {
      window.removeEventListener("resize", bump);
      window.removeEventListener("scroll", bump, true);
      setDragging(null);
      setMenu(null);
    };
  }, [active]);

  // A drag ends wherever the pointer is released, including outside every drop position - dropping
  // on nothing has to mean "no move", not "stuck in a drag with no way out".
  useEffect(() => {
    if (!active || !dragging) return;
    const stop = () => setDragging(null);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
    return () => {
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };
  }, [active, dragging]);

  // Right-click, by capture-phase delegation. `DevInspector`'s pattern: the 25 wrappers stay pure
  // markup and one listener answers for all of them, and it is removed the moment arrange is off.
  useEffect(() => {
    if (!active) return;
    function onContextMenu(event: MouseEvent) {
      const target = event.target as Element | null;
      const host =
        target && "closest" in target ? target.closest("[data-arrange-placement]") : null;
      const placementId = host?.getAttribute("data-arrange-placement");
      if (!placementId) return;
      // Swallowed, so the browser's own menu never covers the one being opened.
      event.preventDefault();
      event.stopPropagation();
      setMenu({ placementId, x: event.clientX, y: event.clientY });
    }
    document.addEventListener("contextmenu", onContextMenu, true);
    return () => document.removeEventListener("contextmenu", onContextMenu, true);
  }, [active]);

  // The menu closes on Escape and on any press outside it, which are the two ways a person expects
  // to dismiss one. Bound only while a menu is open.
  useEffect(() => {
    if (!menu) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setMenu(null);
    }
    function onDown(event: PointerEvent) {
      const target = event.target as Element | null;
      if (target && "closest" in target && target.closest("[data-arrange-menu]")) return;
      setMenu(null);
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onDown, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onDown, true);
    };
  }, [menu]);

  const value = useMemo<ArrangeSurfaceValue | null>(
    () =>
      active
        ? { layout, edit, dragging, beginDrag, endDrag, menu, openMenu, tick }
        : null,
    [active, layout, edit, dragging, beginDrag, endDrag, menu, openMenu, tick],
  );

  return (
    <ArrangeSurfaceContext.Provider value={value}>
      {children}
      {active
        ? createPortal(
            <>
              <style>{ARRANGE_STYLESHEET}</style>
              {menu ? <PieceMenu state={menu} /> : null}
            </>,
            document.body,
          )
        : null}
    </ArrangeSurfaceContext.Provider>
  );
}

/* -------------------------------------------------------------------------- */
/*  measuring a placement that generates no box of its own                     */
/* -------------------------------------------------------------------------- */

interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * The union of the wrapper's children, which is where the placement's pixels are.
 *
 * `getBoundingClientRect` on a `display: contents` element answers with an empty rect, because the
 * element has no boxes - that is the whole point of it. So the boxes are its children's, and a
 * placement that repeats draws several of them, which is why this is a union rather than a read of
 * the first one. `null` when the wrapper has no element children at all: the piece drew nothing, so
 * there is nothing to hang a handle off.
 */
function measureContents(host: HTMLElement | null): Rect | null {
  if (!host) return null;
  const children = Array.from(host.children);
  if (children.length === 0) return null;
  let left = Number.POSITIVE_INFINITY;
  let top = Number.POSITIVE_INFINITY;
  let right = Number.NEGATIVE_INFINITY;
  let bottom = Number.NEGATIVE_INFINITY;
  for (const child of children) {
    const box = child.getBoundingClientRect();
    left = Math.min(left, box.left);
    top = Math.min(top, box.top);
    right = Math.max(right, box.right);
    bottom = Math.max(bottom, box.bottom);
  }
  if (!Number.isFinite(left) || !Number.isFinite(top)) return null;
  return { left, top, width: right - left, height: bottom - top };
}

function sameRect(left: Rect | null, right: Rect | null): boolean {
  if (left === null || right === null) return left === right;
  return (
    left.left === right.left &&
    left.top === right.top &&
    left.width === right.width &&
    left.height === right.height
  );
}

/**
 * Where this placement is, kept current.
 *
 * Measured after EVERY render (no dependency list) because a piece re-rendering is the commonest
 * reason its box moves, and the state is only written when a number actually changed, so the
 * measure cannot drive a render of its own. A `ResizeObserver` on the drawn children covers the
 * changes that happen without a render - an image decoding, a font landing - and `tick` covers the
 * ones that happen outside the tree entirely, which are a window resize and a scroll.
 */
function usePlacementRect(hostRef: { current: HTMLElement | null }, tick: number): Rect | null {
  const [rect, setRect] = useState<Rect | null>(null);

  useLayoutEffect(() => {
    const next = measureContents(hostRef.current);
    setRect((previous) => (sameRect(previous, next) ? previous : next));
  });

  useEffect(() => {
    const host = hostRef.current;
    if (!host || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      const next = measureContents(hostRef.current);
      setRect((previous) => (sameRect(previous, next) ? previous : next));
    });
    for (const child of Array.from(host.children)) observer.observe(child);
    return () => observer.disconnect();
  }, [hostRef, tick]);

  return rect;
}

/* -------------------------------------------------------------------------- */
/*  the chrome installed into the renderer                                     */
/* -------------------------------------------------------------------------- */

/**
 * One placement, named for the editor and left otherwise exactly as it was.
 *
 * Installed as the renderer's placement chrome while arrange is on, and not installed at all
 * otherwise - so this component does not run, and the wrapper does not exist, outside edit mode.
 */
export function ArrangePlacementChrome({ placement, children }: PlacementChromeProps) {
  const surface = useArrangeSurface();
  const hostRef = useRef<HTMLDivElement>(null);
  const rect = usePlacementRect(hostRef, surface?.tick ?? 0);

  return (
    <>
      <div ref={hostRef} data-arrange-placement={placement.id} style={CONTENTS}>
        {children}
      </div>
      {surface && rect
        ? createPortal(
            <PlacementAffordance
              placementId={placement.id}
              pieceId={placement.piece}
              rect={rect}
              surface={surface}
            />,
            document.body,
          )
        : null}
    </>
  );
}

/** The handle, the outline behind it, and - during a drag - this placement's two drop positions. */
function PlacementAffordance({
  placementId,
  pieceId,
  rect,
  surface,
}: {
  placementId: string;
  pieceId: string;
  rect: Rect;
  surface: ArrangeSurfaceValue;
}) {
  const [hovered, setHovered] = useState(false);
  const name = pieceDisplayName(pieceId);
  const handleLabel = useText("design.handle", "Move {piece}", { piece: name });
  const dragged = surface.dragging === placementId;
  const opened = surface.menu?.placementId === placementId;
  const receiving = surface.dragging !== null && !dragged;
  const outlined = hovered || dragged || opened;

  const step = (direction: StepDirection) => {
    surface.edit(stepPlacement(surface.layout, placementId, direction));
  };

  return (
    <div
      className="pointer-events-none fixed z-[185]"
      style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
    >
      <div
        aria-hidden="true"
        className={
          "absolute inset-0 rounded-[3px] transition-colors " +
          (outlined ? "outline outline-1 outline-dashed outline-acc" : "")
        }
      />
      <button
        type="button"
        data-dev-id="design.placement-handle"
        data-arrange-placement={placementId}
        data-arrange-handle={placementId}
        aria-label={handleLabel}
        title={handleLabel}
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          event.preventDefault();
          surface.beginDrag(placementId);
        }}
        onPointerEnter={() => setHovered(true)}
        onPointerLeave={() => setHovered(false)}
        onFocus={() => setHovered(true)}
        onBlur={() => setHovered(false)}
        onKeyDown={(event) => {
          if (event.key === "ArrowUp") step(-1);
          else if (event.key === "ArrowDown") step(1);
          else if (event.key === "Enter" || event.key === " ") {
            surface.openMenu({ placementId, x: rect.left, y: rect.top });
          } else return;
          event.preventDefault();
        }}
        className={
          "pointer-events-auto absolute left-0 top-0 grid h-3.5 w-3.5 place-items-center " +
          "rounded-[3px] border text-2xs font-semibold leading-none " +
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 " +
          "focus-visible:outline-focus " +
          (dragged
            ? "border-transparent bg-acc text-acc-on"
            : "border-line2 bg-popover text-t2 hover:text-t1")
        }
      >
        <span aria-hidden="true">{"⠿"}</span>
      </button>
      {receiving ? (
        <>
          <DropPosition placementId={placementId} name={name} side="before" surface={surface} />
          <DropPosition placementId={placementId} name={name} side="after" surface={surface} />
        </>
      ) : null}
    </div>
  );
}

/**
 * One legal position, drawn only while something is being dragged.
 *
 * A `<button>` rather than a div with a pointer handler: it is a real target, it announces itself,
 * and a static element carrying an interaction is a defect this repository's lint reports. It is
 * taken OUT of the tab order (`tabIndex={-1}`) because it exists for the length of one drag and the
 * keyboard has its own complete path through the handle and the piece menu.
 */
function DropPosition({
  placementId,
  name,
  side,
  surface,
}: {
  placementId: string;
  name: string;
  side: DropSide;
  surface: ArrangeSurfaceValue;
}) {
  const [over, setOver] = useState(false);
  const beforeLabel = useText("design.drop-above", "Drop above {piece}", { piece: name });
  const afterLabel = useText("design.drop-under", "Drop under {piece}", { piece: name });
  const label = side === "before" ? beforeLabel : afterLabel;
  return (
    <button
      type="button"
      tabIndex={-1}
      data-dev-id="design.drop-target"
      data-arrange-drop={side}
      data-arrange-anchor={placementId}
      aria-label={label}
      title={label}
      onPointerEnter={() => setOver(true)}
      onPointerLeave={() => setOver(false)}
      onPointerUp={() => {
        const dragging = surface.dragging;
        if (!dragging) return;
        surface.edit(dropPlacement(surface.layout, dragging, placementId, side));
        surface.endDrag();
      }}
      className={
        "pointer-events-auto absolute inset-x-0 h-1/2 border-acc " +
        (side === "before" ? "top-0 border-t-2 " : "bottom-0 border-b-2 ") +
        (over ? "bg-acc/20" : "bg-transparent")
      }
    />
  );
}

/* -------------------------------------------------------------------------- */
/*  the piece menu                                                             */
/* -------------------------------------------------------------------------- */

/**
 * What one placement can be told, in one surface: what it IS, whether it is drawn, and where it
 * goes.
 *
 * Rendered ONCE by the provider rather than once per placement, because there is one open menu at a
 * time and 25 mounted-but-closed menus would be 25 subtrees of controls in the accessibility tree.
 */
function PieceMenu({ state }: { state: ArrangeMenuState }) {
  const surface = useArrangeSurface();
  const title = useText("design.piece-settings", "Piece Settings");
  const collapseLabel = useText("design.collapse", "Collapse");
  const expandLabel = useText("design.expand", "Expand");
  const hideLabel = useText("design.hide", "Hide");
  const showLabel = useText("design.show", "Show");
  const upLabel = useText("design.move-up", "Move Up");
  const downLabel = useText("design.move-down", "Move Down");
  const intoLabel = useText("design.move-into", "Move Into");
  const collapseNote = useText(
    "design.collapse-note",
    "Collapse draws nothing at all here: no piece states a header the renderer can draw on its own.",
  );
  if (!surface) return null;
  const seat = placementSeat(surface.layout, state.placementId);
  if (!seat) return null;
  const { placement } = seat;
  const collapsed = placement.collapsed === true;
  const hidden = placement.hidden === true;
  const regions = arrangeRegionChoices(surface.layout, state.placementId);

  return (
    <div
      data-dev-id="design.piece-menu"
      data-arrange-menu={state.placementId}
      role="group"
      aria-label={title}
      className="fixed z-[195] flex w-[220px] flex-col gap-1 rounded-control border border-line2 bg-popover p-2 shadow-pop"
      style={{ left: state.x, top: state.y }}
    >
      <div data-dev-id="design.piece-name" className="flex flex-col gap-0.5">
        <span className="truncate text-2xs font-semibold text-t1">
          {pieceDisplayName(placement.piece)}
        </span>
        <span className="truncate font-mono text-2xs text-t3" title={state.placementId}>
          {state.placementId}
        </span>
        <span className="truncate font-mono text-2xs text-t3" title={placement.piece}>
          {placement.piece}
        </span>
      </div>
      <div className="flex gap-1">
        <MenuButton
          devId="design.piece-collapse"
          pressed={collapsed}
          label={collapsed ? expandLabel : collapseLabel}
          onClick={() =>
            surface.edit(setPlacementCollapsed(surface.layout, { placement: state.placementId }, !collapsed))
          }
        />
        <MenuButton
          devId="design.piece-hide"
          pressed={hidden}
          label={hidden ? showLabel : hideLabel}
          onClick={() =>
            surface.edit(setPlacementHidden(surface.layout, { placement: state.placementId }, !hidden))
          }
        />
      </div>
      <p className="text-2xs leading-relaxed text-t3">{collapseNote}</p>
      <div className="flex gap-1">
        <MenuButton
          devId="design.piece-move-up"
          label={upLabel}
          disabled={!canStepPlacement(surface.layout, state.placementId, -1)}
          onClick={() => surface.edit(stepPlacement(surface.layout, state.placementId, -1))}
        />
        <MenuButton
          devId="design.piece-move-down"
          label={downLabel}
          disabled={!canStepPlacement(surface.layout, state.placementId, 1)}
          onClick={() => surface.edit(stepPlacement(surface.layout, state.placementId, 1))}
        />
      </div>
      <select
        data-dev-id="design.piece-move-into"
        aria-label={intoLabel}
        value={seat.regionId}
        onChange={(event) => {
          surface.edit(
            movePlacementIntoRegion(surface.layout, state.placementId, event.target.value),
          );
        }}
        className="rounded-control border border-line bg-field px-1.5 py-1 font-mono text-2xs text-t1 outline-none focus:border-acc"
      >
        {regions.map((choice) => (
          <option key={choice.id} value={choice.id}>
            {choice.id}
          </option>
        ))}
      </select>
    </div>
  );
}

function MenuButton({
  devId,
  label,
  onClick,
  pressed,
  disabled = false,
}: {
  devId: string;
  label: string;
  onClick: () => void;
  pressed?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      data-dev-id={devId}
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
      className={
        "flex-1 rounded-control border px-1.5 py-1 text-2xs font-semibold transition-colors " +
        "disabled:opacity-35 " +
        (pressed === true
          ? "border-transparent bg-acc text-acc-on"
          : "border-line text-t2 hover:text-t1")
      }
    >
      {label}
    </button>
  );
}

/* -------------------------------------------------------------------------- */
/*  region boundaries                                                          */
/* -------------------------------------------------------------------------- */

/**
 * The column band's geometry WHILE ARRANGE IS ON, or `null`.
 *
 * TWO DIFFERENT THINGS SHARE ONE HANDLE, and keeping them apart is the whole of this hook. Outside
 * arrange, dragging a column splitter states a WORKSTATION PREFERENCE: it is a property of the
 * monitor somebody is sitting at, it is kept in `localStorage` under `lib/workspaceColumns`'s own
 * key, and it never travels. Inside arrange the same drag edits the DOCUMENT's fractions, which are
 * what a committed redesign ships to every machine. Conflating the two would either make an owner's
 * redesign a local preference or make one person's monitor everybody's layout.
 *
 * So while arrange is on the band reads its proportions from the document rather than from storage,
 * and a drag writes them back with `setRegionSize`; `localStorage` is not read and not written.
 * Which set of numbers is edited follows the same condition the renderer picks by, so dragging a
 * boundary while looking at a component nobody has sourced edits the SPARSE geometry - the one
 * actually on screen - and leaves the resting geometry alone.
 */
export interface ArrangeColumnGeometry {
  fractions: StoredColumnFractions;
  commit: (widths: WorkspaceColumnWidths, total: number) => void;
}

export function useArrangeColumnGeometry(sparseSourcing: boolean): ArrangeColumnGeometry | null {
  const surface = useArrangeSurface();
  const layout = surface?.layout ?? null;
  const edit = surface?.edit;

  const fractions = useMemo(
    () => (layout ? workspaceColumnFractions(layout, sparseSourcing) : null),
    [layout, sparseSourcing],
  );

  const commit = useCallback(
    (widths: WorkspaceColumnWidths, total: number) => {
      if (!layout || !edit || !Number.isFinite(total) || total <= 0) return;
      const options = sparseSourcing
        ? { condition: WORKSPACE_CONDITION.sparseSourcing }
        : undefined;
      let next = layout;
      for (const id of WORKSPACE_COLUMN_IDS) {
        next = setRegionSize(
          next,
          WORKSPACE_COLUMN_REGION[id],
          { fraction: widths[id] / total },
          options,
        );
      }
      edit(next);
    },
    [layout, edit, sparseSourcing],
  );

  // Memoised, because the band hangs its width effect and its pointer listeners off this object:
  // a fresh one per render would re-bind a `pointermove` handler in the middle of every drag step.
  return useMemo(
    () => (fractions ? { fractions, commit } : null),
    [fractions, commit],
  );
}
