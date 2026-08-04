/**
 * One representation of the component: its symbol, its land pattern, or its 3D body.
 *
 * A module states only what a person can act on at a glance - what it looks like, which tool's
 * copy is in force, whether it is trustworthy, who supplied it, and AT MOST ONE thing that is
 * wrong with it. Everything else (per-check evidence, retained variants, the other tools' copies)
 * lives behind Details, because a card that tries to say everything says nothing from two metres
 * away, which is the distance this dock is read from.
 *
 * The previews are the app's existing ones. A second symbol renderer would be a second set of
 * theme, fit and fallback rules to keep in step with the first.
 */
import type { RepresentationKind, RepresentationView } from "../../api/workspaceTypes";
import { useLandPattern, usePreviewGlb } from "../../api/queries";
import { componentRepresentationDevId } from "../../lib/componentDevIds";
import { Text, useText } from "../../lib/copy";
import { CubeArt, FootprintArt, SymbolArt } from "../icons";
import { Glb3DView } from "../Glb3DView";
import { PreviewImage } from "../PreviewImage";
import { Badge } from "../primitives";
import { REPRESENTATION_STATUS_LABEL, statusTone } from "./workspaceStatus";

export const REPRESENTATION_KINDS: readonly RepresentationKind[] = [
  "symbol",
  "footprint",
  "model",
];

export const REPRESENTATION_LABEL: Record<RepresentationKind, string> = {
  symbol: "Symbol",
  footprint: "Footprint",
  model: "3D Model",
};

/** The tool whose copy this module shows: the persisted choice when it still exists, else the projection's. */
export function effectiveTool(view: RepresentationView, preferred: string): string {
  return view.tools.some((tool) => tool.tool === preferred) ? preferred : view.selectedTool;
}

export function RepresentationModule({
  componentId,
  kind,
  view,
  collapsed,
  selectedTool,
  onSelectTool,
  onFocusKind,
  onExpand,
  onDetails,
}: {
  componentId: string;
  kind: RepresentationKind;
  view: RepresentationView;
  /** A collapsed module is a rail: narrow, still visible, and still the way back to this kind. */
  collapsed: boolean;
  selectedTool: string;
  onSelectTool: (tool: string) => void;
  /** Make this kind the expanded one. A rail's whole surface is this control. */
  onFocusKind: () => void;
  onExpand: () => void;
  onDetails: () => void;
}) {
  const label = REPRESENTATION_LABEL[kind];
  const status = REPRESENTATION_STATUS_LABEL[view.status];
  const devId = componentRepresentationDevId(componentId, kind);
  const railLabel = useText("component-browser.representation-rail", `Show ${label}`);
  const noSource = useText("component-browser.representation-no-source", "No recorded source");
  const noTool = useText("component-browser.representation-no-tool", "No Tool");
  const source = sourceLine(view) || noSource;

  if (collapsed) {
    return (
      <div
        data-dev-id={devId}
        data-representation-kind={kind}
        className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-card border border-line bg-raise"
      >
        <button
          type="button"
          data-dev-id="component-browser.representation-rail"
          data-representation-control="true"
          onClick={onFocusKind}
          aria-label={railLabel}
          title={`${label}: ${status}`}
          className="flex min-h-0 w-full flex-1 flex-col items-center gap-2 rounded-card py-2 text-t3 transition-colors hover:bg-raise2 hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-acc"
        >
          <span className="flex-none">{kindArt(kind)}</span>
          <span
            className="min-h-0 flex-1 overflow-hidden whitespace-nowrap text-2xs font-medium"
            style={{ writingMode: "vertical-rl", transform: "rotate(180deg)" }}
          >
            {label}
          </span>
        </button>
      </div>
    );
  }

  return (
    <section
      data-dev-id={devId}
      data-representation-kind={kind}
      aria-label={label}
      className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-card border border-line bg-raise"
    >
      <div className="flex flex-none items-center gap-2 border-b border-line px-2.5 py-1.5">
        <button
          type="button"
          data-dev-id="component-browser.representation-title"
          data-representation-control="true"
          onClick={onFocusKind}
          className="min-w-0 truncate rounded-control text-xs font-semibold text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
        >
          {label}
        </button>
        <Badge size="sm" tone={statusTone(status)}>
          {status}
        </Badge>
        <span className="ml-auto flex-none">
          {view.tools.length > 1 ? (
            <select
              data-dev-id="component-browser.representation-tool"
              aria-label={`${label} tool`}
              value={effectiveTool(view, selectedTool)}
              onChange={(event) => onSelectTool(event.target.value)}
              className="h-6 rounded-control border border-line bg-field px-1.5 text-2xs text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
            >
              {view.tools.map((tool) => (
                <option key={tool.tool} value={tool.tool}>
                  {tool.toolLabel}
                </option>
              ))}
            </select>
          ) : (
            <span className="text-2xs text-t3">{view.tools[0]?.toolLabel ?? noTool}</span>
          )}
        </span>
      </div>

      <div
        data-dev-id="component-browser.representation-preview"
        className="flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-field"
      >
        <RepresentationPreview componentId={componentId} kind={kind} view={view} />
      </div>

      <div className="flex flex-none items-center gap-2 border-t border-line px-2.5 py-1.5">
        <span className="min-w-0 flex-1 truncate text-2xs text-t3" title={source}>
          {source}
        </span>
        <button
          type="button"
          data-dev-id="component-browser.representation-expand"
          onClick={onExpand}
          className="flex-none rounded-control px-1.5 py-1 text-2xs font-medium text-t2 transition-colors hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
        >
          <Text id="component-browser.representation-expand">Expand</Text>
        </button>
        <button
          type="button"
          data-dev-id="component-browser.representation-details"
          onClick={onDetails}
          className="flex-none rounded-control px-1.5 py-1 text-2xs font-medium text-t2 transition-colors hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
        >
          <Text id="component-browser.representation-details">Details</Text>
        </button>
      </div>

      {view.issue ? (
        <p
          data-dev-id="component-browser.representation-issue"
          className="flex-none truncate border-t border-line px-2.5 py-1 text-2xs text-warn"
          title={view.issue}
        >
          {view.issue}
        </p>
      ) : null}
    </section>
  );
}

/** Provider and tool in one line. Never a URL: a provider page belongs behind Details, not on a tile. */
function sourceLine(view: RepresentationView): string {
  const tool = view.tools.find((entry) => entry.tool === view.selectedTool) ?? view.tools[0];
  const source = view.sourceLabel || tool?.sourceLabel || "";
  return source ? `From ${source}` : "";
}

function kindArt(kind: RepresentationKind) {
  if (kind === "symbol") return <SymbolArt />;
  if (kind === "footprint") return <FootprintArt />;
  return <CubeArt />;
}

/** The 2D previews reuse PreviewImage; the 3D body reuses Glb3DView through the same queries the detail sheet uses. */
function RepresentationPreview({
  componentId,
  kind,
  view,
}: {
  componentId: string;
  kind: RepresentationKind;
  view: RepresentationView;
}) {
  const present = view.tools.some((tool) => tool.present);
  if (!present) {
    return (
      <span className="flex flex-col items-center gap-1 text-t3">
        {kindArt(kind)}
        <span className="text-2xs">
          <Text id="component-browser.representation-absent">Nothing attached</Text>
        </span>
      </span>
    );
  }
  if (kind === "model") return <ModelPreview componentId={componentId} />;
  return (
    <div className="h-full w-full">
      <PreviewImage kind={kind} partId={componentId} fallback={kindArt(kind)} />
    </div>
  );
}

function ModelPreview({ componentId }: { componentId: string }) {
  const model = usePreviewGlb(componentId, true);
  const land = useLandPattern(componentId, true);
  return (
    <div className="h-full w-full">
      <Glb3DView
        data={model.data as ArrayBuffer | undefined}
        isLoading={model.isLoading}
        isError={model.isError}
        error={model.error}
        land={land.data ?? null}
        compact
      />
    </div>
  );
}
