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
 */
import {
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
  SPLITTER_KEY_STEP,
  SPLITTER_NEIGHBOURS,
  writeColumnFractions,
  type StoredColumnFractions,
  type WorkspaceColumnId,
  type WorkspaceColumnWidths,
  type WorkspaceSplitterId,
} from "../../lib/workspaceColumns";

/** The width the band assumes before it has been measured. Replaced on the first layout pass. */
const ASSUMED_TOTAL = 1366;

export interface WorkspaceColumnsProps {
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
}

export function WorkspaceColumns({
  cad,
  specifications,
  sourcing,
  sparseSourcing = false,
}: WorkspaceColumnsProps) {
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
    const next = resolveColumnWidths(total, fractionsRef.current, sparseSourcing);
    widthsRef.current = next;
    setWidths(next);
  }, [total, sparseSourcing]);

  const commit = useCallback((next: WorkspaceColumnWidths) => {
    fractionsRef.current = {
      cad: next.cad,
      specifications: next.specifications,
      sourcing: next.sourcing,
    };
    writeColumnFractions(next);
  }, []);

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
        <div className="flex min-h-0 flex-none flex-col" style={{ width: widths.cad }}>
          {cad}
        </div>
        <ColumnSplitter
          splitter="cad-specifications"
          widths={widths}
          total={total}
          sparseSourcing={sparseSourcing}
          onDrag={drag}
        />
        <div
          className="flex min-h-0 flex-none flex-col"
          style={{ width: widths.specifications }}
        >
          {specifications}
        </div>
        <ColumnSplitter
          splitter="specifications-sourcing"
          widths={widths}
          total={total}
          sparseSourcing={sparseSourcing}
          onDrag={drag}
        />
        <div className="flex min-h-0 flex-1 flex-col" style={{ minWidth: widths.sourcing }}>
          {sourcing}
        </div>
      </div>
    </div>
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
 * The LINE is 1px. The grab area is not: an 8px transparent hit region straddles it so the handle
 * can actually be caught with a pointer, which is what a desktop splitter does and what a literal
 * 1px target does not. Nothing about the line moves on hover except its colour - a divider that
 * thickens under the pointer shifts both columns beside it.
 */
function ColumnSplitter({
  splitter,
  widths,
  total,
  sparseSourcing,
  onDrag,
}: {
  splitter: WorkspaceSplitterId;
  widths: WorkspaceColumnWidths;
  total: number;
  sparseSourcing: boolean;
  onDrag: (splitter: WorkspaceSplitterId, delta: number) => void;
}) {
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
        const step = event.shiftKey ? SPLITTER_KEY_STEP * 4 : SPLITTER_KEY_STEP;
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
      // The rendered rule is the 1px border; the 7px of transparent padding either side is the
      // grab area and paints nothing.
      style={{ width: 9, marginLeft: -4, marginRight: -4 }}
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
 * One column: a 24px title strip, then a body that owns its own scrollbar.
 *
 * The title strip is not a badge shelf. It carries the column's name at panel-title weight and, at
 * most, one right-aligned muted count or state - so `Specifications 42` reads as a heading with a
 * number, not as a heading with a control beside it.
 */
export function WorkspaceColumn({
  id,
  devId,
  title,
  meta,
  action,
  toolbar,
  scrollRef,
  children,
}: {
  id: WorkspaceColumnId;
  devId: string;
  title: ReactNode;
  /** The optional right-side count or state. 10px, muted, never badge-styled. */
  meta?: ReactNode;
  /**
   * At most ONE compact command button on the title line, between the name and the count.
   *
   * A column whose single action is a full toolbar row spends a whole row of vertical space on one
   * button; the layout has always drawn this as `CAD Assets [Compare Sources]`. It is one button,
   * not a shelf: a second one belongs in the toolbar or in a menu.
   */
  action?: ReactNode;
  /** A compact control row directly under the title strip, inside the column's own chrome. */
  toolbar?: ReactNode;
  scrollRef?: (node: HTMLDivElement | null) => void;
  children: ReactNode;
}) {
  return (
    <section
      data-dev-id={devId}
      data-workspace-column={id}
      className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden border-l border-line first:border-l-0"
    >
      <header className="flex h-[24px] flex-none items-center gap-2 border-b border-line bg-band px-2">
        <span className="ui-panel-title min-w-0 truncate">{title}</span>
        {action != null ? <span className="flex-none">{action}</span> : null}
        {meta != null ? (
          <span className="ui-component-metadata ml-auto flex-none">{meta}</span>
        ) : null}
      </header>
      {toolbar}
      <div
        ref={scrollRef}
        data-workspace-scroll={id}
        className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden"
      >
        {children}
      </div>
    </section>
  );
}
