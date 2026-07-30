/**
 * One inspection instrument for a component's three physical/logical projections.
 *
 * Symbol, Footprint, and 3D no longer compete as differently sized cards. They
 * occupy the same stage, preserve their view state while switching, and expand in
 * place so a 3D renderer is never replaced merely because the presentation grew.
 */
import { useCallback, useEffect, useState } from "react";
import { useLandPattern, usePreviewGlb, usePreviewSvg } from "../api/queries";
import { useModalDismiss } from "../lib/useModalDismiss";
import { Glb3DView, type ModelVisibility } from "./Glb3DView";
import { SvgViewport, type SvgVisibility } from "./SvgViewport";

export type InspectionProjection = "symbol" | "footprint" | "model";

export interface InspectionAvailability {
  symbol: boolean;
  footprint: boolean;
  model: boolean;
}

const PROJECTIONS: {
  id: InspectionProjection;
  label: string;
}[] = [
  { id: "symbol", label: "Symbol" },
  { id: "footprint", label: "Footprint" },
  { id: "model", label: "3D Model" },
];

function preferredProjection(
  available: InspectionAvailability,
): InspectionProjection | null {
  // Preserve the existing model-first specimen emphasis when a model can be
  // inspected, then degrade to the two real drawing projections.
  if (available.model) return "model";
  if (available.symbol) return "symbol";
  if (available.footprint) return "footprint";
  return null;
}

export function ComponentInspectionStage({
  partId,
  partName,
  available,
}: {
  partId: string;
  partName: string;
  available: InspectionAvailability;
}) {
  const [projection, setProjection] = useState<InspectionProjection | null>(() =>
    preferredProjection(available),
  );
  const [expanded, setExpanded] = useState(false);
  const close = useCallback(() => setExpanded(false), []);
  const dialogRef = useModalDismiss(expanded, close);

  useEffect(() => {
    if (!projection || !available[projection]) {
      setProjection(preferredProjection(available));
    }
  }, [available.footprint, available.model, available.symbol, projection]);

  // Keep the same stage element and projection children mounted when expanding.
  // ResizeObserver inside the 3D scene then reframes the existing renderer.
  return (
    <div
      data-dev-id="detail.inspection"
      className="relative h-[clamp(340px,54vh,560px)] min-h-0"
    >
      {expanded ? (
        <div
          className="fixed inset-0 z-[109] bg-black/50"
          role="presentation"
          onMouseDown={close}
        />
      ) : null}
      <div
        ref={dialogRef}
        role={expanded ? "dialog" : "region"}
        aria-modal={expanded ? true : undefined}
        aria-label={`Inspect ${partName}`}
        tabIndex={expanded ? -1 : undefined}
        className={
          "flex min-h-0 flex-col overflow-hidden rounded-card border bg-raise outline-none " +
          (expanded
            ? "fixed inset-3 z-[110] border-line2 shadow-pop"
            : "h-full w-full border-line")
        }
      >
        <header className="flex h-[38px] flex-none items-center gap-2 border-b border-line bg-band px-2">
          <div
            role="tablist"
            aria-label="Inspection Projection"
            className="flex min-w-0 items-center gap-1"
          >
            {PROJECTIONS.map((item) => {
              const enabled = available[item.id];
              const active = projection === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  disabled={!enabled}
                  onClick={() => setProjection(item.id)}
                  className={
                    "min-h-[30px] rounded-control px-2.5 text-xs font-semibold transition-colors " +
                    (active
                      ? "bg-raise2 text-t1 shadow-card"
                      : enabled
                        ? "text-t2 hover:bg-raise hover:text-t1"
                        : "cursor-not-allowed text-t3 opacity-45")
                  }
                >
                  {item.label}
                </button>
              );
            })}
          </div>
          <button
            data-dev-id="detail.inspection-expand"
            type="button"
            onClick={() => setExpanded((current) => !current)}
            aria-label={expanded ? "Close Inspection" : "Expand Inspection"}
            className="ml-auto flex-none rounded-control border border-line2 bg-field px-2.5 py-1 text-xs font-semibold text-t2 hover:bg-raise hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-acc"
          >
            {expanded ? "Close" : "Inspect"}
          </button>
        </header>

        <div
          data-dev-id="detail.inspection-stage"
          data-testid="inspection-stage"
          className="relative min-h-0 flex-1 bg-stage"
        >
          {available.symbol ? (
            <ProjectionShell active={projection === "symbol"}>
              <SvgProjection
                kind="symbol"
                partId={partId}
                expanded={expanded}
              />
            </ProjectionShell>
          ) : null}
          {available.footprint ? (
            <ProjectionShell active={projection === "footprint"}>
              <SvgProjection
                kind="footprint"
                partId={partId}
                expanded={expanded}
              />
            </ProjectionShell>
          ) : null}
          {available.model ? (
            <ProjectionShell active={projection === "model"}>
              <ModelProjection partId={partId} expanded={expanded} />
            </ProjectionShell>
          ) : null}
          {!available.symbol && !available.footprint && !available.model ? (
            <Centered>No visual representations are linked.</Centered>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function ProjectionShell({
  active,
  children,
}: {
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      aria-hidden={!active}
      className={"absolute inset-0 min-h-0 " + (active ? "block" : "hidden")}
    >
      {children}
    </div>
  );
}

function SvgProjection({
  kind,
  partId,
  expanded,
}: {
  kind: "symbol" | "footprint";
  partId: string;
  expanded: boolean;
}) {
  const query = usePreviewSvg(kind, partId);
  const [visibility, setVisibility] = useState<SvgVisibility>("checking");

  useEffect(() => setVisibility("checking"), [partId, query.data]);

  if (query.isLoading) {
    return <ProjectionFrame status={`Rendering ${title(kind).toLowerCase()}`}>
      <Centered>Rendering {kind}...</Centered>
    </ProjectionFrame>;
  }
  if (query.isError || !query.data) {
    return <ProjectionFrame status="Preview unavailable">
      <Centered>Could not render this {kind}.</Centered>
    </ProjectionFrame>;
  }

  return (
    <ProjectionFrame status={svgStatus(kind, visibility)}>
      <SvgViewport
        blob={query.data}
        alt={`${kind} preview`}
        downloadName={`${safeName(partId)}-${kind}.svg`}
        compact={!expanded}
        onVisibilityChange={setVisibility}
      />
    </ProjectionFrame>
  );
}

function ModelProjection({
  partId,
  expanded,
}: {
  partId: string;
  expanded: boolean;
}) {
  const model = usePreviewGlb(partId, true);
  const land = useLandPattern(partId, true);
  const [visibility, setVisibility] = useState<ModelVisibility>("checking");

  useEffect(() => setVisibility("checking"), [partId, model.data]);

  return (
    <ProjectionFrame status={modelStatus(visibility)}>
      <Glb3DView
        data={model.data}
        isLoading={model.isLoading}
        isError={model.isError}
        error={model.error}
        land={land.data ?? null}
        showViews
        showShading
        compact={!expanded}
        onVisibilityChange={setVisibility}
      />
    </ProjectionFrame>
  );
}

function ProjectionFrame({
  children,
  status,
}: {
  children: React.ReactNode;
  status: string;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="relative min-h-0 flex-1">{children}</div>
      <footer
        data-dev-id="detail.inspection-footer"
        className="flex h-8 flex-none items-center border-t border-line bg-band px-3"
      >
        <span className="text-2xs font-medium text-t2" aria-live="polite">
          {status}
        </span>
      </footer>
    </div>
  );
}

function svgStatus(kind: "symbol" | "footprint", visibility: SvgVisibility): string {
  if (visibility === "visible") {
    return `Visible ${title(kind).toLowerCase()} · Whole drawing fitted`;
  }
  if (visibility === "unavailable") return "Preview unavailable";
  return `Checking ${title(kind).toLowerCase()}`;
}

function modelStatus(visibility: ModelVisibility): string {
  if (visibility === "visible") return "Visible model · Whole object framed";
  if (visibility === "unavailable") return "Preview unavailable";
  return "Checking visible geometry";
}

function title(kind: "symbol" | "footprint"): string {
  return kind === "symbol" ? "Symbol" : "Footprint";
}

function safeName(value: string): string {
  return value.replace(/[^a-z0-9._-]+/gi, "-");
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full w-full items-center justify-center px-6 text-center text-sm text-t3">
      {children}
    </div>
  );
}
