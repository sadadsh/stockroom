/**
 * The three-column band of an opened component, and the two 1px splitters between them.
 *
 * The band is the layout the whole surface is built around: CAD assets, specifications and
 * sourcing side by side, never stacked, never behind tabs, and never reduced from three to two
 * because the window got smaller. Each column owns its own scrollbar and the band itself never
 * scrolls vertically, so reading a long specification list can never push the symbol preview off
 * the screen.
 *
 * The splitters are a real pointer drag AND a real keyboard control, because a separator that only
 * responds to a mouse is a separator half the people using it cannot move.
 *
 * WHAT THE BAND NOW READS FROM THE LAYOUT DOCUMENT (plan Phase 1). The slot ORDER, the number of
 * columns, and every splitter - which two slots each handle sits between, how far a key press moves
 * it, and how wide the grab area is against the drawn rule - come from the region the document
 * describes. What has deliberately NOT moved is the pixel maths: `lib/workspaceColumns` still owns
 * `resolveColumnWidths`, `moveSplitter`, the floors and the stored fractions, under exactly the
 * storage key it always used. The document says where the boundaries ARE; that module says what
 * happens when one is dragged, and one of the two owning both would be a second answer to the same
 * question.
 *
 * The drawn rule stays a 1px `w-px` class rather than an inline width read off `lineThickness`. The
 * document records the thickness because the grab area is derived from it - a 9px handle straddling
 * a 1px line is 4px of negative margin either side - and a thicker rule is not something anything
 * can ask for until the style panel exists in Phase 3.
 */
import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useText } from "../../lib/copy";
import {
  columnMinimums,
  columnsMinTotal,
  moveSplitter,
  readColumnFractions,
  resolveColumnWidths,
  SPLITTER_NEIGHBOURS,
  writeColumnFractions,
  type StoredColumnFractions,
  type WorkspaceColumnId,
  type WorkspaceColumnWidths,
  type WorkspaceSplitterId,
} from "../../lib/workspaceColumns";
import type { LayoutRegion, LayoutSlot, SplitterSpec } from "../../layout/document";
import {
  DEFAULT_WORKSPACE_LAYOUT,
  WORKSPACE_COLUMN_REGION,
} from "../../layout/defaultWorkspaceLayout";
import { findRegion } from "../../layout/document";
import { WORKSPACE_REGION } from "../../layout/workspacePieces";
import { useArrangeColumnGeometry } from "../design-mode/ArrangeSurface";

/** The width the band assumes before it has been measured. Replaced on the first layout pass. */
const ASSUMED_TOTAL = 1366;

/** The band region of the shipped document: the slot order and the splitters, as data. */
const COLUMN_BAND_REGION: LayoutRegion | null = findRegion(
  DEFAULT_WORKSPACE_LAYOUT,
  WORKSPACE_REGION.columnBand,
);

/**
 * Which of the three geometry columns a slot holds.
 *
 * Read off the REGION the slot contains rather than off the slot's own id, so the mapping is the
 * one `WORKSPACE_COLUMN_REGION` already states and there is no second table of slot names to keep
 * in step with the document.
 */
function columnOfSlot(slot: LayoutSlot): WorkspaceColumnId | null {
  const content = slot.content;
  if (!content || content.kind !== "region") return null;
  const entry = (Object.entries(WORKSPACE_COLUMN_REGION) as [WorkspaceColumnId, string][]).find(
    ([, regionId]) => regionId === content.id,
  );
  return entry?.[0] ?? null;
}

/** One of the band's slots, with whatever the renderer produced for it. */
export interface BandSlotContent {
  slot: LayoutSlot;
  content: ReactNode;
}

/**
 * The band, drawn from a region.
 *
 * Every column is a `flex-none` box at a computed WIDTH except the one the document marks `grow`,
 * which takes the remainder with a MINIMUM instead - the asymmetry the sourcing column has always
 * had, now stated by the document rather than by the position of a variable in this file.
 */
export function WorkspaceColumnBand({
  region,
  slots,
  sparseSourcing = false,
}: {
  region: LayoutRegion;
  slots: readonly BandSlotContent[];
  sparseSourcing?: boolean;
}) {
  const bandRef = useRef<HTMLDivElement>(null);
  const [total, setTotal] = useState(ASSUMED_TOTAL);
  const [widths, setWidths] = useState<WorkspaceColumnWidths>(() =>
    resolveColumnWidths(ASSUMED_TOTAL, readColumnFractions(), sparseSourcing),
  );
  // The stored preference is read ONCE. Re-reading it on every resize would let a mid-session drag
  // be undone by the next window change, which is exactly the bug a persisted layout is supposed
  // to prevent. `useRef` has no lazy-initializer form, so passing the call straight to it re-read
  // the stored preference on EVERY render and threw the answer away.
  //
  // The read is a `useMemo` and the ref is seeded from it, rather than the ref being filled in by a
  // guarded write during render: a render must not mutate a ref, because React can replay or discard
  // a render and the write would leak out of UI that never committed. Seeding is not mutating - the
  // initial value is the one thing `useRef` is allowed to be handed - and if React ever discards the
  // memo the recomputed value is simply unused, because the ref already holds the answer.
  const storedFractions = useMemo(() => readColumnFractions(), []);
  const fractionsRef = useRef<StoredColumnFractions | null>(storedFractions);

  // ARRANGE MODE EDITS THE DOCUMENT, NOT THIS WORKSTATION (plan 1.5, Phase 3B). `null` outside edit
  // mode, and then every line below takes exactly the path it always took. Inside it, the band's
  // proportions come from the arrangement being edited rather than from `localStorage`, and a drag
  // writes them back through `setRegionSize` - which is the difference between "I want this column
  // wider on THIS monitor" and "the sourcing column is wider in this design".
  const arrange = useArrangeColumnGeometry(sparseSourcing);
  const editedFractions = arrange?.fractions ?? null;

  // The authoritative widths, mirrored so a drag can derive the next widths WITHOUT computing them
  // inside a state updater. React may replay an updater, and this one used to persist the result and
  // write `fractionsRef` from in there - work that must happen exactly once per drag step.
  const widthsRef = useRef(widths);

  // Measure the band and re-derive the pixel widths from the remembered proportions. A layout
  // effect rather than an effect: the first painted frame should already be the right shape.
  useLayoutEffect(() => {
    const node = bandRef.current;
    if (!node) return;
    const measure = () => {
      const measured = node.clientWidth;
      if (measured > 0) setTotal(measured);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  // Re-derived when the sourcing column's content changes too: an offer arriving is the moment the
  // column has something to be wide for, and it should get the room then rather than on the next
  // resize.
  useLayoutEffect(() => {
    const next = resolveColumnWidths(
      total,
      editedFractions ?? fractionsRef.current,
      sparseSourcing,
    );
    widthsRef.current = next;
    setWidths(next);
  }, [total, sparseSourcing, editedFractions]);

  const commit = useCallback(
    (next: WorkspaceColumnWidths) => {
      // In arrange mode the boundary is a property of the DOCUMENT, so nothing is written to this
      // machine's storage and the remembered preference is left exactly as the owner last set it.
      if (arrange) {
        arrange.commit(next, total);
        return;
      }
      fractionsRef.current = {
        cad: next.cad,
        specifications: next.specifications,
        sourcing: next.sourcing,
      };
      writeColumnFractions(next);
    },
    [arrange, total],
  );

  // One drag step: derive, persist, then set. The derivation reads the mirrored widths rather than a
  // state updater's `current`, so persistence sits OUTSIDE the updater where it belongs and cannot
  // be run twice by a replay. It still happens synchronously within the same pointer event, so a
  // release-and-reload lands on the same layout it did before, and successive steps in one tick still
  // chain correctly because the mirror is advanced here.
  const drag = useCallback(
    (splitter: WorkspaceSplitterId, delta: number) => {
      const next = moveSplitter(widthsRef.current, splitter, delta, sparseSourcing);
      widthsRef.current = next;
      commit(next);
      setWidths(next);
    },
    [commit, sparseSourcing],
  );

  const splitters = region.splitters ?? [];

  return (
    <div
      ref={bandRef}
      data-dev-id="component-browser.columns"
      // The band is the fixed-height frame. `overflow-hidden` vertically is the whole contract:
      // nothing here may grow a page scrollbar, and the horizontal auto is the honest answer below
      // the combined minimum - a cramped window scrolls sideways rather than losing a column.
      className="flex min-h-0 min-w-0 flex-1 overflow-y-hidden overflow-x-auto"
      style={{ minWidth: 0 }}
    >
      <div
        className="flex min-h-0 flex-1"
        style={{ minWidth: columnsMinTotal(sparseSourcing) }}
      >
        {slots.map(({ slot, content }) => {
          const column = columnOfSlot(slot);
          if (!column) return null;
          const size = slot.content?.kind === "region" ? slot.content.size : undefined;
          // The handle that sits AFTER this slot, which is the one whose left neighbour it is.
          const after = splitters.find((splitter) => splitter.between[0] === slot.id);
          return (
            <Fragment key={slot.id}>
              {size?.grow ? (
                <div
                  className="flex min-h-0 flex-1 flex-col"
                  style={{ minWidth: widths[column] }}
                >
                  {content}
                </div>
              ) : (
                <div
                  className="flex min-h-0 flex-none flex-col"
                  style={{ width: widths[column] }}
                >
                  {content}
                </div>
              )}
              {after ? (
                <ColumnSplitter
                  spec={after}
                  widths={widths}
                  total={total}
                  sparseSourcing={sparseSourcing}
                  onDrag={drag}
                />
              ) : null}
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}

/**
 * The band, addressed by its three named columns.
 *
 * The shape the workspace has always been written against, kept because it is the honest signature
 * for "here are the three columns" - it names them rather than making a caller assemble slots. It
 * resolves the slot order and the splitters from the document, so a caller cannot get the order
 * wrong and the two ways in cannot draw different bands.
 */
export function WorkspaceColumns({
  cad,
  specifications,
  sourcing,
  sparseSourcing = false,
}: {
  cad: ReactNode;
  specifications: ReactNode;
  sourcing: ReactNode;
  /**
   * Nothing has been sourced for this component at all, so the sourcing column can only draw five
   * lifecycle rows however much room it is given.
   *
   * It narrows to what that content needs and the surplus goes to the other two columns. It does not
   * collapse, does not hide and does not lose its title strip - see `WORKSPACE_SOURCING_SPARSE_MIN`
   * for the measurement and for why a collapsed strip was the wrong answer. A stored splitter
   * position overrides this entirely.
   */
  sparseSourcing?: boolean;
}) {
  const region = COLUMN_BAND_REGION;
  if (!region) return null;
  const byColumn: Record<WorkspaceColumnId, ReactNode> = { cad, specifications, sourcing };
  const slots: BandSlotContent[] = region.slots.map((slot) => {
    const column = columnOfSlot(slot);
    return { slot, content: column ? byColumn[column] : null };
  });
  return (
    <WorkspaceColumnBand region={region} slots={slots} sparseSourcing={sparseSourcing} />
  );
}

const SPLITTER_COPY: Record<WorkspaceSplitterId, { id: string; label: string }> = {
  "cad-specifications": {
    id: "component-browser.splitter-cad",
    label: "Resize CAD Assets and Specifications",
  },
  "specifications-sourcing": {
    id: "component-browser.splitter-sourcing",
    label: "Resize Specifications and Sourcing and Resources",
  },
};

/**
 * One 1px separator.
 *
 * The LINE is 1px. The grab area is not: a 9px transparent hit region straddles it so the handle
 * can actually be caught with a pointer, which is what a desktop splitter does and what a literal
 * 1px target does not. Nothing about the line moves on hover except its colour - a divider that
 * thickens under the pointer shifts both columns beside it.
 *
 * Both numbers come from the document's own splitter spec, and the negative margin either side is
 * derived from the two rather than typed: the transparent padding is exactly the difference between
 * the grab area and the rule it straddles, halved.
 */
function ColumnSplitter({
  spec,
  widths,
  total,
  sparseSourcing,
  onDrag,
}: {
  spec: SplitterSpec;
  widths: WorkspaceColumnWidths;
  total: number;
  sparseSourcing: boolean;
  onDrag: (splitter: WorkspaceSplitterId, delta: number) => void;
}) {
  const splitter = spec.id as WorkspaceSplitterId;
  const copy = SPLITTER_COPY[splitter];
  const label = useText(copy.id, copy.label);
  const [dragging, setDragging] = useState(false);
  const originRef = useRef(0);
  const [left, right] = SPLITTER_NEIGHBOURS[splitter];

  useEffect(() => {
    if (!dragging) return;
    const onMove = (event: PointerEvent) => {
      const delta = event.clientX - originRef.current;
      if (delta === 0) return;
      originRef.current = event.clientX;
      onDrag(splitter, delta);
    };
    const onUp = () => setDragging(false);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [dragging, onDrag, splitter]);

  // The travel this handle actually has, so a screen reader hears a position rather than a pixel
  // count that means nothing without knowing the window width.
  const min = columnMinimums(sparseSourcing);
  const lowest = min[left];
  const highest = Math.max(lowest, widths[left] + widths[right] - min[right]);
  const grab = spec.grabWidth;
  const padding = -(grab - spec.lineThickness) / 2;

  return (
    <div
      role="separator"
      tabIndex={0}
      aria-orientation="vertical"
      aria-label={label}
      aria-valuemin={Math.round(lowest)}
      aria-valuemax={Math.round(highest)}
      aria-valuenow={Math.round(widths[left])}
      data-dev-id="component-browser.column-splitter"
      data-splitter={splitter}
      data-total={Math.round(total)}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        originRef.current = event.clientX;
        setDragging(true);
      }}
      onKeyDown={(event) => {
        const step = event.shiftKey ? spec.keyStep * 4 : spec.keyStep;
        if (event.key === "ArrowLeft") onDrag(splitter, -step);
        else if (event.key === "ArrowRight") onDrag(splitter, step);
        else return;
        event.preventDefault();
      }}
      className={
        "group relative flex-none cursor-col-resize select-none " +
        "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 " +
        "focus-visible:outline-focus"
      }
      // The rendered rule is the 1px border; the transparent padding either side is the grab area
      // and paints nothing.
      style={{ width: grab, marginLeft: padding, marginRight: padding }}
    >
      <span
        aria-hidden
        className={
          "pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 " +
          (dragging ? "bg-line2" : "bg-line group-hover:bg-line2")
        }
      />
    </div>
  );
}

/**
 * A column's frame: the bordered box that owns the whole column and clips it.
 *
 * Split out of the old single `WorkspaceColumn` component so a column can be COMPOSED from the
 * document - a title strip, an optional toolbar and a scroller are three placements now, not three
 * props - while the element each of them draws stays in one place. `first:border-l-0` is why the
 * three read as one contiguous surface rather than as three panels with a gap.
 */
export function WorkspaceColumnFrame({
  id,
  devId,
  children,
}: {
  id: WorkspaceColumnId;
  devId: string;
  children: ReactNode;
}) {
  return (
    <section
      data-dev-id={devId}
      data-workspace-column={id}
      className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden border-l border-line first:border-l-0"
    >
      {children}
    </section>
  );
}

/**
 * A column's 24px title strip.
 *
 * Not a badge shelf. It carries the column's name at panel-title weight and, at most, one
 * right-aligned muted count or state - so `Specifications 42` reads as a heading with a number, not
 * as a heading with a control beside it. At most ONE compact command button sits on the line,
 * between the name and the count: a column whose single action is a full toolbar row spends a whole
 * row of vertical space on one button, and a second button belongs in a toolbar or a menu.
 */
export function WorkspaceColumnTitleStrip({
  title,
  meta,
  action,
}: {
  title: ReactNode;
  /** The optional right-side count or state. 10px, muted, never badge-styled. */
  meta?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <header className="flex h-[24px] flex-none items-center gap-2 border-b border-line bg-band px-2">
      <span className="ui-panel-title min-w-0 truncate">{title}</span>
      {action != null ? <span className="flex-none">{action}</span> : null}
      {meta != null ? (
        <span className="ui-component-metadata ml-auto flex-none">{meta}</span>
      ) : null}
    </header>
  );
}

/** The one thing in a column that scrolls. Exactly one per column; the band never scrolls down. */
export function WorkspaceColumnScroller({
  id,
  scrollRef,
  children,
}: {
  id: WorkspaceColumnId;
  scrollRef?: (node: HTMLDivElement | null) => void;
  children: ReactNode;
}) {
  return (
    <div
      ref={scrollRef}
      data-workspace-scroll={id}
      className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden"
    >
      {children}
    </div>
  );
}
