/**
 * The left column: CAD Assets.
 *
 * Three stacked modules whose headers are ALWAYS visible, a column toolbar that names the source
 * the whole coherent set comes from, and one way into the provider comparison. The column's job
 * is to answer "does this component have the drawings, and can they be trusted" without ever
 * naming an EDA application - which is what `Preferred Source` is for: one statement at column
 * level about where the set comes from, instead of the same provider sentence repeated under all
 * three assets.
 *
 * `Preferred Source` is a CONTROL, not a caption. It used to be inferred from the three attached
 * files and to say "Mixed" when they disagreed, which described the past and gave a person
 * looking at a mixed set nothing to do about it. It now records a decision, and the decision is
 * shown before it is taken.
 *
 * Expansion state persists per component in the ui session. `all` is the reading state: attached
 * drawings divide the available inspection space while missing assets remain compact identity
 * strips. Focusing one asset compacts the other two and never removes them.
 *
 * THE COLUMN IS FIVE PLACEMENTS NOW (plan Phase 1): a title strip, the preferred-source row, and
 * three placements of ONE module piece parameterised by representation kind. The document decides
 * the order and which kinds are drawn; `CadColumnChrome` supplies what all five need and nothing
 * else. The expansion state stays where it was - it is a per-component UI SESSION fact, a data need
 * of the module, not a per-placement setting - because a person focusing the footprint on one part
 * is not redesigning the workspace.
 */
import { createContext, useContext, useMemo } from "react";
import type { ComponentDossier, RepresentationKind } from "../../api/dossierTypes";
import { useWriteCadPreference } from "../../api/queries";
import { Text, useText } from "../../lib/copy";
import { useToast } from "../../lib/toast";
import type { PiecePartProps, RegionChromeProps } from "../../layout/LayoutRenderer";
import { useWorkspaceRender } from "../../layout/workspaceRenderContext";
import { BoardIcon } from "../icons";
import { Button } from "../primitives";
import { CadAssetModule } from "./CadAssetModule";
import { REPRESENTATION_KINDS } from "./cadAssetSet";
import { hasPreferredSourceInformation } from "./cadPreference";
import { PreferredSourceControl } from "./PreferredSourceControl";
import {
  WorkspaceColumnFrame,
  WorkspaceColumnTitleStrip,
} from "./WorkspaceColumns";
import { cadAssetStatus } from "./workspaceStatus";

/** How many of the three assets are actually attached. The column strip's right-hand count. */
function attachedCount(dossier: ComponentDossier): number {
  const representations = dossier.cadAssets.kinds;
  return REPRESENTATION_KINDS.filter((kind) => {
    const status = cadAssetStatus(representations[kind]);
    return status === "Validated" || status === "Available" || status === "Package Matched";
  }).length;
}

/**
 * The component's own pin count, so a drawn terminal count has a second side to compare against.
 *
 * Read from the projected key specifications rather than from the raw spec bag, because that is
 * where the category schema has already decided which field means "how many terminals does this
 * part have" - and a comparison against a field nobody normalized is not a comparison.
 */
function expectedPinCount(dossier: ComponentDossier): number | null {
  return numericSpecification(dossier, ["pin_count", "number_of_pins", "positions"]);
}

/** The package pitch the specification states, in millimetres, when it states one. */
function expectedPitch(dossier: ComponentDossier): number | null {
  return numericSpecification(dossier, ["pitch"]);
}

function numericSpecification(dossier: ComponentDossier, keys: string[]): number | null {
  const rows = [
    ...dossier.keySpecifications,
    ...dossier.specificationGroups.flatMap((group) => group.specifications),
  ];
  for (const key of keys) {
    const row = rows.find((record) => record.key === key);
    const value = row?.normalizedValue;
    if (typeof value === "number" && Number.isFinite(value)) return value;
    const parsed = Number.parseFloat(String(row?.displayValue ?? ""));
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

/** What the column derives once and its pieces read. Never a second copy of the dossier. */
interface CadColumnState {
  attached: number;
  pins: number | null;
  pitch: number | null;
  setAssetRef: Record<RepresentationKind, (node: HTMLElement | null) => void>;
  writing: boolean;
  choose: (provider: string) => void;
  clear: () => void;
}

const CadColumnContext = createContext<CadColumnState | null>(null);

/** The column's frame, and the one derivation its pieces share. */
export function CadColumnChrome({ children }: RegionChromeProps) {
  const workspace = useWorkspaceRender();
  const componentId = workspace?.componentId ?? "";
  const write = useWriteCadPreference(componentId);
  const { toast } = useToast();
  const failed = useText(
    "component-browser.cad-source-failed",
    "Could not record the preferred source.",
  );
  const assetRefs = workspace?.cad.assetRefs;
  // Stable per-kind callback refs, so a re-render does not detach and reattach every module.
  const setAssetRef = useMemo(
    () =>
      Object.fromEntries(
        REPRESENTATION_KINDS.map((kind) => [
          kind,
          (node: HTMLElement | null) => {
            if (assetRefs) assetRefs.current[kind] = node;
          },
        ]),
      ) as Record<RepresentationKind, (node: HTMLElement | null) => void>,
    [assetRefs],
  );
  const dossier = workspace?.dossier;
  const state = useMemo<CadColumnState | null>(() => {
    if (!dossier) return null;
    const report = (error: unknown) =>
      toast(error instanceof Error ? error.message : failed, "err");
    return {
      attached: attachedCount(dossier),
      pins: expectedPinCount(dossier),
      pitch: expectedPitch(dossier),
      setAssetRef,
      writing: write.isPending,
      choose: (provider: string) =>
        write.mutate({ kind: "set-set-source", provider }, { onError: report }),
      clear: () => write.mutate({ kind: "clear-set-source" }, { onError: report }),
    };
  }, [dossier, failed, setAssetRef, toast, write]);

  if (!state) return null;
  return (
    <WorkspaceColumnFrame id="cad" devId="component-browser.column-cad">
      <CadColumnContext.Provider value={state}>{children}</CadColumnContext.Provider>
    </WorkspaceColumnFrame>
  );
}

/** `CAD Assets  2/3` — inspection stays here; acquisition lives in Assets. */
export function CadTitleStripPart() {
  const workspace = useWorkspaceRender();
  const state = useContext(CadColumnContext);
  if (!workspace || !state) return null;
  return (
    <WorkspaceColumnTitleStrip
      title={
        <span className="flex items-center gap-1.5">
          <BoardIcon className="h-3.5 w-3.5 text-t3" />
          <Text id="component-browser.column-cad">CAD Assets</Text>
        </span>
      }
      meta={`${state.attached}/${REPRESENTATION_KINDS.length}`}
    />
  );
}

/**
 * ONE row, and the set decision owns it.
 *
 * The preferred source is the only fact here whose VALUE has to be readable, so it gets the elastic
 * width rather than sharing it with a button that has a permanent home on the line above.
 */
export function CadPreferredSourcePart() {
  const workspace = useWorkspaceRender();
  const state = useContext(CadColumnContext);
  if (!workspace || !state) return null;
  const { layout, onLayout } = workspace.cad;
  const preference = workspace.dossier.cadAssets.preference;
  const showPreference = hasPreferredSourceInformation(preference);
  const showAll = layout !== "all";
  // An empty “Preferred Source: None recorded” row communicates no provider fact and offers no
  // action. Remove only that case; a refused option, mixed set or per-asset provider keeps the row.
  if (!showPreference && !showAll) {
    // Keep the registered piece addressable to the layout/Design Studio manifest without painting
    // an empty toolbar row in the product.
    return <div data-dev-id="component-browser.preferred-source" hidden aria-hidden />;
  }
  return (
    <div
      data-dev-id="component-browser.preferred-source"
      className="flex min-w-0 flex-none items-center gap-2 border-b border-line px-2 py-1"
    >
      {showPreference ? (
        <span className="flex min-w-0 flex-1 items-center">
          <PreferredSourceControl
            preference={preference}
            busy={state.writing}
            onChoose={state.choose}
            onClear={state.clear}
          />
        </span>
      ) : null}
      {/* The way back to the reading state. Offered only when one module is focused, because
          a control that puts the column into the state it is already in is a dead click. */}
      {showAll ? (
        <Button
          small
          data-dev-id="component-browser.show-all-assets"
          onClick={() => onLayout("all")}
          className="ml-auto flex-none"
        >
          <Text id="component-browser.show-all-assets">Show All Three</Text>
        </Button>
      ) : null}
    </div>
  );
}

/**
 * The three assets always fit the pane. Attached expanded modules divide the available height;
 * missing modules reserve only a compact strip until focused. Focusing one keeps two compact
 * previews and gives the remaining space to the focused asset.
 * `data-workspace-scroll` stays as the stable column-body address, but CAD deliberately owns no
 * scrollbar: a drawing preview scales, while specifications and evidence retain scrolling.
 */
export function CadBodyChrome({ children }: RegionChromeProps) {
  const columnTitle = useText("component-browser.column-cad", "CAD Assets");
  return (
    <div data-workspace-scroll="cad" className="min-h-0 flex-1 overflow-hidden">
      <div aria-label={columnTitle} role="group" className="flex h-full min-h-0 flex-col">
        {children}
      </div>
    </div>
  );
}

/**
 * One representation module, named by the placement.
 *
 * `params.representation` is what distinguishes three appearances of one piece. A kind the document
 * asks for that the projection does not carry draws nothing rather than an empty module.
 */
export function CadAssetModulePart({ placement }: PiecePartProps) {
  const workspace = useWorkspaceRender();
  const state = useContext(CadColumnContext);
  if (!workspace || !state) return null;
  const kind = placement.params?.representation as RepresentationKind | undefined;
  if (!kind) return null;
  const view = workspace.dossier.cadAssets.kinds[kind];
  if (!view) return null;
  const { layout, onLayout, onOpenFullPreview } = workspace.cad;
  return (
    <CadAssetModule
      componentId={workspace.componentId}
      kind={kind}
      view={view}
      preference={workspace.dossier.cadAssets.preference}
      expectedPins={state.pins}
      expectedPitch={state.pitch}
      expanded={layout === "all" || layout === kind}
      focused={layout === kind}
      onToggle={() => onLayout(layout === kind ? "all" : kind)}
      onOpenFullPreview={() => onOpenFullPreview(kind)}
      focusRef={state.setAssetRef[kind]}
    />
  );
}
