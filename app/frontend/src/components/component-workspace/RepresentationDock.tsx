/**
 * The representation dock: symbol, land pattern and 3D body, side by side, always.
 *
 * The three are one question ("does this component's CAD agree with itself?") and answering it by
 * flipping between three tabs turns a comparison into a memory test. So expanding one never
 * REMOVES the other two: they narrow to rails that still name themselves and are still the way
 * back. Nothing here stacks into a taller page - the dock owns a fixed band of the workspace and
 * every module fits inside it or clips, because a component workspace that scrolls is a document,
 * not an instrument.
 */
import { useRef } from "react";
import type { RepresentationKind, RepresentationView } from "../../api/workspaceTypes";
import type { RepresentationLayout } from "../../lib/uiSession";
import { Text, useText } from "../../lib/copy";
import { SegmentedControl } from "../primitives";
import {
  REPRESENTATION_KINDS,
  REPRESENTATION_LABEL,
  RepresentationModule,
} from "./RepresentationModule";

/** Width of a collapsed module's rail. Wide enough for the glyph, the rotated name, and a focus ring. */
const RAIL_PX = 40;

/**
 * The dock's grid tracks for a layout, as a STRING fed to a CSS custom property.
 *
 * Never interpolated into a `grid-cols-[...]` class: Tailwind generates utilities by scanning
 * source text, so a class built from a template literal has no CSS behind it and the grid silently
 * collapses to one column per module. Only the VALUE moves; `grid-cols-[var(--sr-dock)]` is a
 * static, scannable class.
 */
export function dockTemplate(layout: RepresentationLayout): string {
  if (layout === "all") return "minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)";
  const rail = `${RAIL_PX}px`;
  return REPRESENTATION_KINDS.map((kind) => (kind === layout ? "minmax(0,1fr)" : rail)).join(" ");
}

export function RepresentationDock({
  componentId,
  representations,
  layout,
  onLayout,
  toolByKind,
  onSelectTool,
  onExpand,
  onDetails,
}: {
  componentId: string;
  representations: Record<RepresentationKind, RepresentationView>;
  layout: RepresentationLayout;
  onLayout: (layout: RepresentationLayout) => void;
  toolByKind: Record<RepresentationKind, string>;
  onSelectTool: (kind: RepresentationKind, tool: string) => void;
  onExpand: (kind: RepresentationKind) => void;
  onDetails: (kind: RepresentationKind) => void;
}) {
  const dockLabel = useText("component-browser.dock-label", "Representations");
  const layoutLabel = useText("component-browser.layout-label", "Representation layout");
  const gridRef = useRef<HTMLDivElement>(null);

  // Arrow keys walk the three modules whichever form they are in, so a keyboard user never has to
  // know that one of them is currently a rail. Focus MOVES; it does not re-lay-out the dock -
  // arrowing past a module should not collapse the one you were reading.
  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const keys = ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"];
    if (!keys.includes(event.key)) return;
    const controls = Array.from(
      gridRef.current?.querySelectorAll<HTMLElement>("[data-representation-control]") ?? [],
    );
    if (controls.length === 0) return;
    const current = controls.findIndex((node) => node === document.activeElement);
    const last = controls.length - 1;
    let next = current;
    if (event.key === "Home") next = 0;
    else if (event.key === "End") next = last;
    else if (event.key === "ArrowRight" || event.key === "ArrowDown")
      next = current >= last ? 0 : current + 1;
    else next = current <= 0 ? last : current - 1;
    event.preventDefault();
    controls[next]?.focus();
  }

  return (
    <section
      data-dev-id="component-browser.dock"
      aria-label={dockLabel}
      className="flex min-h-0 flex-[2_1_0%] flex-col overflow-hidden px-4 pt-2.5"
    >
      <div className="mb-1.5 flex flex-none items-center gap-3">
        <span className="text-xs font-semibold text-t1">
          <Text id="component-browser.dock-title">Representations</Text>
        </span>
        <span className="ml-auto flex-none">
          <SegmentedControl
            options={[
              { id: "all", label: "All" },
              { id: "symbol", label: REPRESENTATION_LABEL.symbol },
              { id: "footprint", label: REPRESENTATION_LABEL.footprint },
              { id: "model", label: REPRESENTATION_LABEL.model },
            ]}
            value={layout}
            onChange={(id) => onLayout(id as RepresentationLayout)}
            size="small"
            devIdBase="component-browser.layout"
            aria-label={layoutLabel}
          />
        </span>
      </div>
      <div
        ref={gridRef}
        onKeyDown={onKeyDown}
        className="grid min-h-0 flex-1 grid-cols-[var(--sr-dock)] gap-2 overflow-hidden pb-2.5"
        style={{ "--sr-dock": dockTemplate(layout) } as React.CSSProperties}
      >
        {REPRESENTATION_KINDS.map((kind) => (
          <RepresentationModule
            key={kind}
            componentId={componentId}
            kind={kind}
            view={representations[kind]}
            collapsed={layout !== "all" && layout !== kind}
            selectedTool={toolByKind[kind] ?? ""}
            onSelectTool={(tool) => onSelectTool(kind, tool)}
            // A rail returns to itself; the expanded module returns the dock to all three.
            onFocusKind={() => onLayout(layout === kind ? "all" : kind)}
            onExpand={() => onExpand(kind)}
            onDetails={() => onDetails(kind)}
          />
        ))}
      </div>
    </section>
  );
}
