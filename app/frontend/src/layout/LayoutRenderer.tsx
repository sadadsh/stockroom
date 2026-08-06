/**
 * THE RENDERER: a layout document, walked, as React elements.
 *
 * `document.ts` says what an arrangement IS; this says what drawing one MEANS. It is deliberately
 * the whole of that meaning and no more - it knows about regions, slots, placements, visibility,
 * repetition and per-placement parameters, and it knows nothing at all about the workspace. Every
 * appearance on the screen comes from a BINDING supplied by the caller: a piece id resolves to the
 * component that draws it, and a region id resolves to the chrome that wraps its slots. Swap the
 * bindings and the same walker renders a different surface, which is what Phase 6 and Phase 7 need
 * of it.
 *
 * FOUR RULES, each of which is the reason a line here exists.
 *
 *   THE DOCUMENT IS CONSTANT; THE RUNTIME IS NOT. A placement's `visibility.anyOf` is a list of
 *   condition IDS, and a `repeat.over` is the NAME of a collection. Neither is a value. The runtime
 *   supplies the answers through `LayoutRuntimeScope`, and a scope may be opened anywhere in the
 *   tree - which is what lets a column that owns a piece of state (the sourcing column's reveal
 *   preference, the specification column's search box) answer the conditions that depend on it
 *   without that state having to be hoisted out of the column it belongs to.
 *
 *   AN UNANSWERABLE QUESTION IS `false`, NOT AN ERROR. A condition nobody supplied reads as not
 *   holding and a collection nobody supplied reads as empty. `validateLayout` is where a document's
 *   problems are REPORTED; a renderer that threw would take the whole surface down over one bad
 *   placement, and the surface is what a person is trying to look at.
 *
 *   NOTHING IS RENDERED THAT THE DOCUMENT DOES NOT PLACE. There is no fallback that draws an
 *   unregistered piece, and no chrome that invents an element. A piece id with no binding renders
 *   nothing, which is exactly what makes the coverage gate meaningful: a section that appears on
 *   screen appeared because a placement put it there.
 *
 *   IDENTITY FOLLOWS THE DOCUMENT. Children are keyed by SLOT ID and repeated children by the
 *   collection's own key, so a node keeps its React identity - and therefore its local state and
 *   its DOM node - across every re-render in which the document did not change. A renderer that
 *   keyed by index would reset a collapsed section the first time a filter removed the group above
 *   it.
 */
import {
  createContext,
  useContext,
  useMemo,
  type ComponentType,
  type ReactNode,
} from "react";
import type { LayoutDocument, LayoutNode, LayoutRegion, LayoutSlot, PiecePlacement } from "./document";

/** One element of a repeated placement: the React key, and whatever the piece needs to draw it. */
export interface LayoutRepeatItem {
  key: string;
  value: unknown;
}

/**
 * Everything the document asks the running application, and nothing else.
 *
 * Both halves are plain records rather than functions so a scope can be merged with its parent by
 * spreading, and so a test can state the runtime a document is being rendered against as data.
 */
export interface LayoutRuntime {
  conditions: Readonly<Record<string, boolean>>;
  collections: Readonly<Record<string, readonly LayoutRepeatItem[]>>;
}

const EMPTY_RUNTIME: LayoutRuntime = { conditions: {}, collections: {} };

const RuntimeContext = createContext<LayoutRuntime>(EMPTY_RUNTIME);

/**
 * Answer some of the document's questions for everything drawn inside.
 *
 * Nested scopes MERGE with the one outside them and an inner answer wins, so the workspace can
 * answer "is this component's sourcing sparse" once at the top while the sourcing column answers
 * "has this workstation asked to see the blank sections" for its own subtree only.
 */
export function LayoutRuntimeScope({
  conditions,
  collections,
  children,
}: {
  conditions?: Readonly<Record<string, boolean>>;
  collections?: Readonly<Record<string, readonly LayoutRepeatItem[]>>;
  children: ReactNode;
}) {
  const outer = useContext(RuntimeContext);
  const value = useMemo<LayoutRuntime>(
    () => ({
      conditions: { ...outer.conditions, ...conditions },
      collections: { ...outer.collections, ...collections },
    }),
    [outer, conditions, collections],
  );
  return <RuntimeContext.Provider value={value}>{children}</RuntimeContext.Provider>;
}

/**
 * One of the document's named conditions, as the runtime currently answers it.
 *
 * For chrome that has to CHANGE SHAPE with a condition rather than merely appear or disappear - the
 * column band picks its widths from `sparseSourcing` - so the shape and the placements inside it are
 * decided from one answer rather than two evaluations of the same rule.
 */
export function useLayoutCondition(id: string): boolean {
  return useContext(RuntimeContext).conditions[id] === true;
}

/** What a piece binding is handed. `item` and `index` are set only for a repeated placement. */
export interface PiecePartProps {
  placement: PiecePlacement;
  item?: unknown;
  index?: number;
}

/** The component that draws one registered piece. */
export type PiecePart = ComponentType<PiecePartProps>;

/** One of a region's slots, with what the renderer produced for it. */
export interface RenderedSlot {
  slot: LayoutSlot;
  content: ReactNode;
}

/**
 * What a region's chrome is handed.
 *
 * `children` is the slots in order and is what almost every chrome wants. `slots` is the same
 * content with each piece still attached to the slot it came from, which is what a chrome that
 * puts something BETWEEN its slots needs - a splitter, a separator, a numbered gutter.
 */
export interface RegionChromeProps {
  region: LayoutRegion;
  slots: readonly RenderedSlot[];
  children: ReactNode;
}

export type RegionChrome = ComponentType<RegionChromeProps>;

export interface LayoutBindings {
  /** Piece id to the component that draws it. */
  pieces: Readonly<Record<string, PiecePart>>;
  /** Region id to the element that wraps its slots. A region with no entry wraps in nothing. */
  chrome: Readonly<Record<string, RegionChrome>>;
}

const EMPTY_BINDINGS: LayoutBindings = { pieces: {}, chrome: {} };

const BindingsContext = createContext<LayoutBindings>(EMPTY_BINDINGS);

/** A region whose arrangement needs no element of its own. Its slots become its parent's flow. */
function TransparentChrome({ children }: RegionChromeProps) {
  return <>{children}</>;
}

/** Does the runtime put this placement on screen at all. */
function placementDraws(placement: PiecePlacement, runtime: LayoutRuntime): boolean {
  if (placement.hidden) return false;
  const anyOf = placement.visibility?.anyOf;
  // No `visibility` means unconditional. An EMPTY list is treated the same way rather than as
  // "never": a placement nobody can see is an editing accident, and hiding is what `hidden` is for.
  if (!anyOf || anyOf.length === 0) return true;
  return anyOf.some((id) => runtime.conditions[id] === true);
}

function LayoutPlacementView({ placement }: { placement: PiecePlacement }) {
  const runtime = useContext(RuntimeContext);
  const { pieces } = useContext(BindingsContext);
  const Part = pieces[placement.piece];
  // Unbound, hidden, or every condition false: nothing is drawn and nothing is reported here.
  // `validateLayout` is the module that names an unknown piece; this one just does not invent it.
  if (!Part || !placementDraws(placement, runtime)) return null;
  if (!placement.repeat) return <Part placement={placement} />;
  const items = runtime.collections[placement.repeat.over] ?? [];
  return (
    <>
      {items.map((item, index) => (
        <Part key={item.key} placement={placement} item={item.value} index={index} />
      ))}
    </>
  );
}

function LayoutRegionView({ region }: { region: LayoutRegion }) {
  const { chrome } = useContext(BindingsContext);
  const Chrome = chrome[region.id] ?? TransparentChrome;
  const rendered: RenderedSlot[] = region.slots.map((slot) => ({
    slot,
    // Keyed by the SLOT, not by position: a conditional placement that stops drawing must not
    // shift the identity of the ones after it.
    content: slot.content ? <LayoutNodeView key={slot.id} node={slot.content} /> : null,
  }));
  return (
    <Chrome region={region} slots={rendered}>
      {rendered.map((entry) => entry.content)}
    </Chrome>
  );
}

/** One node of the tree, whichever of the two drawable kinds it is. */
export function LayoutNodeView({ node }: { node: LayoutNode }) {
  return node.kind === "region" ? (
    <LayoutRegionView region={node} />
  ) : (
    <LayoutPlacementView placement={node} />
  );
}

/**
 * Draw a whole document.
 *
 * The bindings are supplied per document rather than imported, because the point of the layer is
 * that the same walker draws the workspace, the shell and every route after them from three
 * different binding tables.
 */
export function LayoutDocumentView({
  document,
  bindings,
}: {
  document: LayoutDocument;
  bindings: LayoutBindings;
}) {
  return (
    <BindingsContext.Provider value={bindings}>
      <LayoutNodeView node={document.root} />
    </BindingsContext.Provider>
  );
}

/**
 * Draw one region of a document on its own, with the same bindings.
 *
 * A surface is sometimes mounted a region at a time - one column rendered by itself in a test, and
 * later a single region dragged into a preview - and a walker that could only start at the root
 * would force those callers to hand-build the tree the document already describes.
 */
export function LayoutRegionScope({
  region,
  bindings,
}: {
  region: LayoutRegion;
  bindings: LayoutBindings;
}) {
  return (
    <BindingsContext.Provider value={bindings}>
      <LayoutNodeView node={region} />
    </BindingsContext.Provider>
  );
}
